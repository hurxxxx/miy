"""Transaction fencing for one suite owner; operational cutover stays closed.

These functions are core-only. A transaction GUC is a trusted runtime assertion,
not a credential or a substitute for separate database roles.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from miy_api.core.db import official_writer_unavailable
from miy_api.domains.auth.dependencies import AuthContext, resolve_auth_context_from_session_id
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from miy_api.domains.official_apps.writer_models import RuntimeOwnership, RuntimeTransition

COVERED_SCOPES = frozenset({SUITE_SCOPE})


class WriterControlError(ValueError):
    pass


@dataclass(frozen=True)
class WriterIdentity:
    scope: str
    owner: Literal["legacy", "official-suite"]
    generation: int
    artifact: str | None = None

    def __post_init__(self):
        if (
            self.scope not in COVERED_SCOPES
            or self.owner not in {"legacy", "official-suite"}
            or type(self.generation) is not int
            or self.generation < 1
            or (
                self.artifact is not None
                and not re.fullmatch(r"sha256:[a-f0-9]{64}", self.artifact)
            )
        ):
            raise WriterControlError("writer_identity_invalid")


# Fixed compatibility composition identity. Never discover/adopt a database
# generation at startup or reconnect. Keep this common boundary independent of
# API-only collaboration libraries so API, Worker and Beat use the same fence.
LEGACY_WRITER_IDENTITY = WriterIdentity(SUITE_SCOPE, "legacy", 1)


def snapshot(record: RuntimeOwnership) -> dict:
    return {
        "scope": record.scope,
        "owner": record.active_owner,
        "generation": record.generation,
        "artifact": record.artifact,
        "state": record.state,
    }


def _admin(db: Session, context: AuthContext) -> AuthContext:
    current = resolve_auth_context_from_session_id(db, context.session.id)
    if (
        current.user.id != context.user.id
        or current.impersonator_user_id is not None
        or "platform_admin" not in current.system_roles
    ):
        raise WriterControlError("writer_admin_required")
    return current


def bind_transaction(db: Session, identity: WriterIdentity) -> None:
    """Pin trusted identity to this existing SQL transaction; never discover/adopt the current generation."""
    # Rebinding an already pinned transaction could combine two artifact identities.
    value = json.dumps(asdict(identity), sort_keys=True, separators=(",", ":"))
    with db.no_autoflush:
        existing = db.scalar(text("SELECT current_setting('miy.official_writer', true)"))
        if existing and existing != value:
            raise WriterControlError("writer_transaction_already_bound")
        db.execute(
            text("SELECT set_config('miy.official_writer', :identity, true)"), {"identity": value}
        )


def require_active_writer(db: Session, identity: WriterIdentity) -> None:
    """Read-only early refusal, not a lock/commit fence or generation discovery.

    Final source triggers still compare the transaction identity under FOR SHARE.
    Even unchanged collaboration snapshots must not be reported saved in drain.
    """
    with db.no_autoflush:
        record = db.get(RuntimeOwnership, identity.scope, populate_existing=True)
        if record is None or snapshot(record) != asdict(identity) | {"state": "active"}:
            raise official_writer_unavailable()


def transition(
    db: Session,
    context: AuthContext,
    *,
    request_id: UUID,
    expected: WriterIdentity,
    expected_state: Literal["active", "draining"],
    owner: Literal["legacy", "official-suite"],
    state: Literal["active", "draining"],
    artifact: str | None,
    reason: str,
) -> dict:
    """CAS ownership+audit in caller's transaction; no endpoint, implicit commit or activation bypass."""
    # Complete runtime/queue/role coverage has not been established. No caller or
    # environment variable can enable the new owner through this initial API.
    if owner != "legacy":
        raise WriterControlError("official_activation_unavailable")
    result_identity = WriterIdentity(expected.scope, owner, expected.generation + 1, artifact)
    if state not in {"active", "draining"} or expected_state not in {"active", "draining"}:
        raise WriterControlError("writer_state_invalid")
    if not reason.strip() or len(reason) > 300:
        raise WriterControlError("writer_reason_required")
    request_id = str(UUID(str(request_id)))
    with db.no_autoflush:
        # Snapshot isolation can keep a revoked login/role visible even after
        # populate_existing and a long ownership-lock wait. AUTOCOMMIT would
        # also split ownership and audit writes into separate transactions.
        if db.connection().connection.driver_connection.autocommit:
            raise WriterControlError("writer_transition_requires_transaction")
        if db.scalar(text("SELECT current_setting('transaction_isolation')")) != "read committed":
            raise WriterControlError("writer_transition_requires_read_committed")
        actor = _admin(db, context)
        payload = {
            "expected": asdict(expected) | {"state": expected_state},
            "resulting": asdict(result_identity) | {"state": state},
            "actor_user_id": actor.user.id,
            "source_session_id": actor.session.id,
            "reason": reason,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        # Take the same ownership row exclusively; in-flight source transactions
        # retain FOR SHARE until commit/rollback and therefore finish before CAS.
        record = db.scalar(
            select(RuntimeOwnership)
            .where(RuntimeOwnership.scope == expected.scope)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        # Waiting for source transactions may outlive a login or role grant.
        # Refresh authority after the fence, before either mutation or replay.
        _admin(db, context)
        previous = db.get(RuntimeTransition, request_id, populate_existing=True)
        if previous:
            if previous.request_hash != digest:
                raise WriterControlError("writer_request_conflict")
            return previous.resulting
        if record is None or snapshot(record) != payload["expected"]:
            raise WriterControlError("writer_compare_and_swap_conflict")
        record.active_owner, record.generation, record.artifact, record.state = (
            owner,
            result_identity.generation,
            artifact,
            state,
        )
        record.updated_at = utcnow_naive()
        db.add(
            RuntimeTransition(
                request_id=request_id,
                scope=expected.scope,
                request_hash=digest,
                actor_user_id=actor.user.id,
                source_session_id=actor.session.id,
                previous=payload["expected"],
                resulting=payload["resulting"],
                reason=reason,
            )
        )
        db.flush()
        return payload["resulting"]
