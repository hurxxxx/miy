"""Fixed extraction transport on actual restricted disposable Source principals."""

import json
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from _migration_revision_fixtures import migration_revision_world
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    ACTIVE,
    activate,
    move,
    role_template as role_template,
    world as current_head_world,  # noqa: F401
)
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.official_apps.file_extraction_roles import (
    ADMIT,
    POLICY_READ_COLUMNS,
    RESULT_DIGEST,
    file_extraction_guard_contract,
    install_file_extraction_guard,
    prepare_file_extraction_principal,
)
from miy_api.domains.official_apps.projection_contracts import ProjectionIntent
from miy_api.domains.official_apps.projection_outbox import append_projection_intent
from miy_api.domains.official_apps.writer import WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from miy_api.domains.retrieval.partitioning import ensure_default_partition

POLICY = "files-retrieval-v2/local-only-10m-v1"


@pytest.fixture
def world(current_head_world, request, tmp_path, monkeypatch):  # noqa: F811
    return migration_revision_world(
        current_head_world,
        request,
        tmp_path,
        monkeypatch,
        expected_revision="file_effect_20261007",
    )


@pytest.fixture
def extraction_prepared(world):
    old_source, _, _ = activate(world)
    # Allocation is a separate privileged Core setup, never a Source grant.
    with Session(world.engine) as db:
        partition = str(
            ensure_default_partition(
                db, source_namespace="files", candidate_scope_kind="company"
            ).id
        )
        db.commit()
    drain = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    owner = world.role(login=False)
    with Session(world.engine) as db:
        install_file_extraction_guard(db, world.actor, guard_owner=owner, expected=drain)
        db.commit()
    source = world.role()
    identity = WriterIdentity(SUITE_SCOPE, "legacy", drain.generation + 1, "sha256:" + "c" * 64)
    with Session(world.engine) as db:
        prepared = prepare_file_extraction_principal(
            db,
            world.actor,
            role_name=source,
            identity=identity,
            expected=drain,
            expected_state="draining",
        )
        assert prepared.profile_prepared
        source_oid = prepared.principal.role_oid
        db.commit()
    assert move(world, drain, "draining", state="active", artifact=identity.artifact) == identity
    return SimpleNamespace(
        source=source,
        old_source=old_source,
        owner=owner,
        identity=identity,
        partition=partition,
        source_oid=source_oid,
    )


def compact(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def seeded_request(world, prepared):
    identifier = str(uuid4())
    # Genuine Source initial pending intent is established independently before prepare.
    from test_file_projection_roles import reader_engine

    engine = reader_engine(world, prepared.source)
    try:
        with Session(engine) as db:
            file = FileManagerFile(
                id=identifier,
                owner_id=world.user_id,
                filename="Synthetic.txt",
                content_type="text/plain",
                size_bytes=14,
                storage_key="synthetic-owned/" + identifier,
                visibility="private",
                retrieval_partition_id=prepared.partition,
                extraction_status="pending",
                extraction_blocks=[],
                extraction_metadata={},
            )
            db.add(file)
            db.flush()
            event = append_projection_intent(
                db,
                intent=ProjectionIntent(
                    resource_type="file_manager_file",
                    resource_id=identifier,
                    retrieval_partition_id=prepared.partition,
                    change_kind="content",
                    desired_state="active",
                    operation="upsert",
                ),
                event_id=uuid4(),
            )
            input_data = dict(
                storage_key=file.storage_key,
                size_bytes=file.size_bytes,
                updated_at=file.updated_at.isoformat(timespec="microseconds"),
                filename=file.filename,
                content_type=file.content_type,
                owner_id=file.owner_id,
                visibility=file.visibility,
                corpus_id=None,
                folder_id=None,
                retrieval_partition_id=prepared.partition,
                source_version=None,
                source_content_checksum=None,
                pending_event_id=str(event.event_id),
                pending_event_digest=event.payload_digest,
            )
            db.commit()
    finally:
        engine.dispose()
    request_id, result_id, event_id = map(str, (uuid4(), uuid4(), uuid4()))
    input_canonical = compact(input_data)
    payload = compact(
        dict(
            protocol_version=1,
            request_id=request_id,
            result_id=result_id,
            event_id=event_id,
            file_id=identifier,
            actor_user_id=world.user_id,
            execution_ref=world.session_id,
            parser_policy=POLICY,
            input_canonical=input_canonical,
        )
    )
    return dict(
        request_id=request_id,
        result_id=result_id,
        event_id=event_id,
        file_id=identifier,
        actor_user_id=world.user_id,
        execution_ref=world.session_id,
        parser_policy=POLICY,
        request_payload=payload,
        request_digest=sha256(payload.encode()).hexdigest(),
        input_fingerprint=sha256(input_canonical.encode()).hexdigest(),
        state="prepared",
    )


def insert_request(conn, values):
    from psycopg import sql

    keys = list(values)
    return conn.execute(
        sql.SQL(
            "INSERT INTO file_extraction_requests ({}) VALUES ({}) RETURNING request_id"
        ).format(
            sql.SQL(",").join(map(sql.Identifier, keys)),
            sql.SQL(",").join([sql.Placeholder()] * len(keys)),
        ),
        list(values.values()),
    ).fetchone()[0]


def test_migration_preserves_canonical_inventory(world):
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 90
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_name='file_extraction_requests' AND column_name='writer_scope'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT prosecdef FROM pg_proc WHERE oid=%s::regprocedure", (RESULT_DIGEST,)
            ).fetchone()[0]
            is False
        )


def test_deferred_trigger_definition(world):
    with world.connect() as conn:
        row = conn.execute(
            "SELECT pg_get_triggerdef(oid),tgdeferrable,tginitdeferred FROM pg_trigger WHERE tgname='miy_file_extraction_terminal'"
        ).fetchone()
        assert row[1:] == (True, True)
        assert "CREATE CONSTRAINT TRIGGER" in row[0]
        assert "DEFERRABLE INITIALLY DEFERRED" in row[0]
        assert "WHEN (((new.state)::text = ANY" in row[0]


def test_actual_fresh_profile_and_request(extraction_prepared, world):
    prepared = extraction_prepared
    values = seeded_request(world, prepared)
    with world.connect(prepared.source) as conn:
        conn.execute("SELECT public.miy_file_extraction_admit(NULL)")
        assert str(insert_request(conn, values)) == values["request_id"]
        assert conn.execute(
            "SELECT producer_role_oid,producer_role_name,state FROM file_extraction_requests WHERE request_id=%s",
            (values["request_id"],),
        ).fetchone() == (prepared.source_oid, prepared.source, "prepared")
        for table, columns in POLICY_READ_COLUMNS.items():
            assert not conn.execute(
                "SELECT has_table_privilege(current_user,%s,'SELECT')", (table,)
            ).fetchone()[0]
            for column in columns:
                assert conn.execute(
                    "SELECT has_column_privilege(current_user,%s,%s,'SELECT')", (table, column)
                ).fetchone()[0]
    with Session(world.engine) as db:
        file_extraction_guard_contract(db)


def test_actual_claim_bind(extraction_prepared, world):
    values = seeded_request(world, extraction_prepared)
    token = str(uuid4())
    raw_sha = sha256(b"Synthetic text").hexdigest()
    with world.connect(extraction_prepared.source) as conn:
        insert_request(conn, values)
    with world.connect(extraction_prepared.source) as conn:
        conn.execute(
            "UPDATE file_extraction_requests SET state=%s,claim_token=%s WHERE request_id=%s",
            ("claimed", token, values["request_id"]),
        )
    with world.connect(extraction_prepared.source) as conn:
        conn.execute(
            "UPDATE file_extraction_requests SET state=%s,input_sha256=%s,input_byte_count=14 WHERE request_id=%s",
            ("input_bound", raw_sha, values["request_id"]),
        )
        assert conn.execute(
            "SELECT state,claim_token,input_sha256 FROM file_extraction_requests WHERE request_id=%s",
            (values["request_id"],),
        ).fetchone() == ("input_bound", __import__("uuid").UUID(token), raw_sha)


def bind_request(world, prepared, values):
    token = str(uuid4())
    raw_sha = sha256(b"Synthetic text").hexdigest()
    with world.connect(prepared.source) as conn:
        insert_request(conn, values)
    with world.connect(prepared.source) as conn:
        conn.execute(
            "UPDATE file_extraction_requests SET state='claimed',claim_token=%s WHERE request_id=%s",
            (token, values["request_id"]),
        )
    with world.connect(prepared.source) as conn:
        conn.execute(
            "UPDATE file_extraction_requests SET state='input_bound',input_sha256=%s,input_byte_count=14 WHERE request_id=%s",
            (raw_sha, values["request_id"]),
        )
    return token, raw_sha


def terminal_parts(
    conn,
    values,
    checksum,
    *,
    outcome="ready",
    event=True,
    text_value="Synthetic text",
    metadata=None,
):
    from psycopg.types.json import Json

    content_checksum = checksum if outcome == "ready" else None
    error = (
        None
        if outcome == "ready"
        else "unsupported_source"
        if outcome == "unsupported"
        else "local_parser_failed"
    )
    blocks = (
        [
            {
                "document_id": values["file_id"],
                "block_id": values["file_id"] + ":1",
                "locator_kind": "paragraph",
                "locator_label": "Paragraph1",
                "block_kind": "paragraph",
                "text": "Synthetic text",
            }
        ]
        if outcome == "ready"
        else []
    )
    conn.execute(
        "UPDATE file_manager_files SET extraction_status=%s,extraction_content_checksum=%s,extraction_text=%s,extraction_blocks=%s,extraction_metadata=%s,extraction_error_code=%s,extracted_at=timezone('UTC',clock_timestamp()),updated_at=timezone('UTC',clock_timestamp()) WHERE id=%s",
        (
            outcome,
            content_checksum,
            text_value if outcome == "ready" else None,
            Json(blocks),
            Json(metadata or {}),
            error,
            values["file_id"],
        ),
    )
    if event:
        intent = ProjectionIntent(
            resource_type="file_manager_file",
            resource_id=values["file_id"],
            retrieval_partition_id=json.loads(
                json.loads(values["request_payload"])["input_canonical"]
            )["retrieval_partition_id"],
            change_kind="content" if outcome == "ready" else "delete",
            desired_state="active" if outcome == "ready" else "deleted",
            operation="upsert" if outcome == "ready" else "delete",
            content_checksum=content_checksum,
        )
        revision = (
            conn.execute(
                "SELECT max(source_revision) FROM official_projection_outbox WHERE resource_type='file_manager_file' AND resource_id=%s",
                (values["file_id"],),
            ).fetchone()[0]
            + 1
        )
        conn.execute(
            "INSERT INTO official_projection_outbox(event_id,resource_type,resource_id,source_revision,payload,payload_digest) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                values["event_id"],
                intent.resource_type,
                intent.resource_id,
                revision,
                intent.canonical(),
                intent.digest(),
            ),
        )
    return error


def finish(conn, values, outcome, error=None, *, bad_digest=False):
    digest = conn.execute(
        "SELECT public.miy_file_extraction_result_digest(%s::uuid,%s)",
        (values["request_id"], outcome),
    ).fetchone()[0]
    conn.execute(
        "UPDATE file_extraction_requests SET state=%s,result_digest=%s,error_code=%s WHERE request_id=%s",
        (outcome, "a" * 64 if bad_digest else digest, error, values["request_id"]),
    )
    return digest


@pytest.mark.parametrize("outcome", ["ready", "unsupported", "failed"])
def test_actual_terminal_same_outer_transaction(extraction_prepared, world, outcome):
    values = seeded_request(world, extraction_prepared)
    _, checksum = bind_request(world, extraction_prepared, values)
    with world.connect(extraction_prepared.source) as conn:
        assert conn.execute("SELECT pg_current_xact_id()::xid IS NOT NULL").fetchone()[0]
        error = terminal_parts(conn, values, checksum, outcome=outcome, event=outcome != "failed")
        digest = finish(conn, values, outcome, error)
    with world.connect(extraction_prepared.source) as conn:
        row = conn.execute(
            "SELECT state,result_digest,completed_at FROM file_extraction_requests WHERE request_id=%s",
            (values["request_id"],),
        ).fetchone()
        assert row[0:2] == (outcome, digest) and row[2] is not None
        assert conn.execute(
            "SELECT count(*) FROM official_projection_outbox WHERE event_id=%s",
            (values["event_id"],),
        ).fetchone()[0] == int(outcome != "failed")
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM official_projection_receipts WHERE event_id=%s",
                (values["event_id"],),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM retrieval_projection_events WHERE resource_type='file_manager_file' AND resource_id=%s",
                (values["file_id"],),
            ).fetchone()[0]
            == 0
        )
    # The database result uses PostgreSQL JSONB text, not Python compact JSON.
    assert len(digest) == 64


@pytest.mark.parametrize(
    "boundary",
    [
        "no_artifact",
        "no_intent",
        "prior_artifact",
        "prior_intent",
        "bad_digest",
        "nested",
        "outer_rollback",
        "after_terminal_rewrite",
        "after_terminal_tip_rewrite",
    ],
)
def test_terminal_correlation_and_rollback(extraction_prepared, world, boundary):
    import psycopg

    values = seeded_request(world, extraction_prepared)
    _, checksum = bind_request(world, extraction_prepared, values)
    if boundary in ("prior_artifact", "prior_intent"):
        with world.connect(extraction_prepared.source) as conn:
            terminal_parts(conn, values, checksum, event=boundary == "prior_intent")
    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises((psycopg.Error, RuntimeError)) as caught:
            with conn.transaction():
                if boundary == "nested":
                    conn.execute("SELECT pg_current_xact_id()")
                    with conn.transaction():
                        terminal_parts(conn, values, checksum)
                        finish(conn, values, "ready")
                else:
                    if boundary not in ("no_artifact", "prior_intent"):
                        if boundary == "prior_artifact":
                            # Add only the intent now, retaining an old artifact xmin.
                            # A rewrite is intentionally absent; manually append fixed event.
                            intent = ProjectionIntent(
                                resource_type="file_manager_file",
                                resource_id=values["file_id"],
                                retrieval_partition_id=extraction_prepared.partition,
                                change_kind="content",
                                desired_state="active",
                                operation="upsert",
                                content_checksum=checksum,
                            )
                            conn.execute(
                                "INSERT INTO official_projection_outbox(event_id,resource_type,resource_id,source_revision,payload,payload_digest) VALUES(%s,%s,%s,2,%s,%s)",
                                (
                                    values["event_id"],
                                    intent.resource_type,
                                    intent.resource_id,
                                    intent.canonical(),
                                    intent.digest(),
                                ),
                            )
                        else:
                            terminal_parts(conn, values, checksum, event=boundary != "no_intent")
                    finish(conn, values, "ready", bad_digest=boundary == "bad_digest")
                    if boundary == "after_terminal_rewrite":
                        conn.execute(
                            "UPDATE file_manager_files SET extraction_text='changed after terminal' WHERE id=%s",
                            (values["file_id"],),
                        )
                    if boundary == "after_terminal_tip_rewrite":
                        intent = ProjectionIntent(
                            resource_type="file_manager_file",
                            resource_id=values["file_id"],
                            retrieval_partition_id=extraction_prepared.partition,
                            change_kind="delete",
                            desired_state="deleted",
                            operation="delete",
                            content_checksum=None,
                        )
                        conn.execute(
                            "INSERT INTO official_projection_outbox(event_id,resource_type,resource_id,source_revision,payload,payload_digest) VALUES(%s,%s,%s,3,%s,%s)",
                            (
                                str(uuid4()),
                                intent.resource_type,
                                intent.resource_id,
                                intent.canonical(),
                                intent.digest(),
                            ),
                        )
                    if boundary == "outer_rollback":
                        raise RuntimeError("outer_after_terminal_failure")
        if boundary != "outer_rollback":
            assert caught.value.sqlstate in ("23514", "55000")
    with world.connect(extraction_prepared.source) as conn:
        assert conn.execute(
            "SELECT state,result_digest FROM file_extraction_requests WHERE request_id=%s",
            (values["request_id"],),
        ).fetchone() == ("input_bound", None)
        if boundary not in ("prior_artifact", "prior_intent"):
            assert (
                conn.execute(
                    "SELECT extraction_status FROM file_manager_files WHERE id=%s",
                    (values["file_id"],),
                ).fetchone()[0]
                == "pending"
            )
            assert (
                conn.execute(
                    "SELECT count(*) FROM official_projection_outbox WHERE event_id=%s",
                    (values["event_id"],),
                ).fetchone()[0]
                == 0
            )


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT password_hash FROM users",
        "SELECT token_hash FROM auth_sessions",
        "SELECT * FROM auth_sessions",
        "UPDATE users SET login_blocked=true WHERE false",
        "SELECT id FROM users FOR SHARE",
        "SELECT id FROM retrieval_partitions",
        "SELECT generation FROM official_runtime_ownership",
        "SELECT * FROM official_writer_principals",
        "SELECT * FROM audit_logs",
        "UPDATE retrieval_projection_heads SET projection_version=projection_version WHERE false",
        "INSERT INTO rag_sync_jobs(id) SELECT gen_random_uuid() WHERE false",
        "SELECT public.miy_read_official_company_partition('docs',NULL)",
        "SELECT public.miy_lock_official_projection_partition(gen_random_uuid(),'files')",
        "SELECT public.miy_recording_lock_producer(1,session_user,1,NULL)",
        "DELETE FROM file_extraction_requests WHERE false",
        "TRUNCATE file_extraction_requests",
    ],
)
def test_actual_profile_denies_core_private_and_history(extraction_prepared, world, statement):
    import psycopg

    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                conn.execute(statement)
        assert caught.value.sqlstate == "42501"


def test_old_source_profile_replay_never_upgrades(extraction_prepared, world):
    from test_file_projection_roles import grants

    before = grants(world, extraction_prepared.old_source)
    with world.connect() as conn:
        before_audit = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(world.engine) as db:
        result = prepare_file_extraction_principal(
            db,
            world.actor,
            role_name=extraction_prepared.old_source,
            identity=ACTIVE,
            expected=extraction_prepared.identity,
            expected_state="active",
        )
        assert not result.profile_prepared
        db.commit()
    assert grants(world, extraction_prepared.old_source) == before
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == before_audit
    with world.connect(extraction_prepared.old_source) as conn:
        assert not conn.execute(
            "SELECT has_table_privilege(current_user,%s,%s)", ("file_extraction_requests", "SELECT")
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_function_privilege(current_user,%s,%s)", (ADMIT, "EXECUTE")
        ).fetchone()[0]


def test_old_company_profile_replay_never_upgrades(world):
    from test_official_partition_reader import prepared as company_fixture

    # Build the existing exact reviewed company profile using its original fixture.
    previous = company_fixture.__wrapped__(world)
    from test_file_projection_roles import grants

    before = grants(world, previous.source)
    with world.connect() as conn:
        before_audit = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(world.engine) as db:
        result = prepare_file_extraction_principal(
            db,
            world.actor,
            role_name=previous.source,
            identity=previous.identity,
            expected=previous.identity,
            expected_state="active",
        )
        assert not result.profile_prepared
        db.commit()
    assert grants(world, previous.source) == before
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == before_audit


def test_same_header_body_drift_refused_before_grant(extraction_prepared, world):
    from test_file_projection_roles import grants

    role = world.role()
    before = grants(world, role)
    with world.connect() as conn:
        conn.execute(
            "CREATE OR REPLACE FUNCTION public.miy_file_extraction_admit(r_id uuid DEFAULT NULL) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN RETURN; END $$"
        )
    from miy_api.domains.official_apps.writer import WriterControlError

    with Session(world.engine) as db:
        with pytest.raises(WriterControlError, match="file_extraction_function_contract_invalid"):
            prepare_file_extraction_principal(
                db,
                world.actor,
                role_name=role,
                identity=extraction_prepared.identity,
                expected=extraction_prepared.identity,
                expected_state="active",
            )
        db.rollback()
    assert grants(world, role) == before


@pytest.mark.parametrize("drift", ["immediate", "false_predicate", "disabled", "extra_trigger"])
def test_terminal_trigger_drift_refused_before_grant(extraction_prepared, world, drift):
    from test_file_projection_roles import grants
    from miy_api.domains.official_apps.writer import WriterControlError

    role = world.role()
    before = grants(world, role)
    with world.connect() as conn:
        before_audit = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
        if drift == "disabled":
            conn.execute(
                "ALTER TABLE file_extraction_requests DISABLE TRIGGER miy_file_extraction_terminal"
            )
        elif drift == "extra_trigger":
            conn.execute(
                "CREATE TRIGGER unexpected_extraction_trigger AFTER UPDATE ON file_extraction_requests FOR EACH ROW EXECUTE FUNCTION public.miy_file_extraction_request_guard()"
            )
        else:
            conn.execute("DROP TRIGGER miy_file_extraction_terminal ON file_extraction_requests")
            if drift == "immediate":
                conn.execute(
                    "CREATE TRIGGER miy_file_extraction_terminal AFTER UPDATE ON file_extraction_requests FOR EACH ROW WHEN (NEW.state IN ('ready','unsupported','failed')) EXECUTE FUNCTION public.miy_file_extraction_request_guard()"
                )
            else:
                conn.execute(
                    "CREATE CONSTRAINT TRIGGER miy_file_extraction_terminal AFTER UPDATE ON file_extraction_requests DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (false) EXECUTE FUNCTION public.miy_file_extraction_request_guard()"
                )
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError, match="file_extraction_trigger_contract_invalid"):
            prepare_file_extraction_principal(
                db,
                world.actor,
                role_name=role,
                identity=extraction_prepared.identity,
                expected=extraction_prepared.identity,
                expected_state="active",
            )
        db.rollback()
    assert grants(world, role) == before
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == before_audit
        assert (
            conn.execute(
                "SELECT count(*) FROM official_writer_principals WHERE role_name=%s", (role,)
            ).fetchone()[0]
            == 0
        )


def test_concurrent_claim_has_one_token(extraction_prepared, world):
    from concurrent.futures import ThreadPoolExecutor

    values = seeded_request(world, extraction_prepared)
    with world.connect(extraction_prepared.source) as conn:
        insert_request(conn, values)
    tokens = [str(uuid4()), str(uuid4())]

    def claim(token):
        with world.connect(extraction_prepared.source) as conn:
            return conn.execute(
                "UPDATE file_extraction_requests SET state='claimed',claim_token=%s WHERE request_id=%s AND state='prepared' RETURNING claim_token",
                (token, values["request_id"]),
            ).fetchone()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, tokens))
    assert sum(row is not None for row in results) == 1
    winner = next(row[0] for row in results if row)
    with world.connect(extraction_prepared.source) as conn:
        assert (
            conn.execute(
                "SELECT claim_token FROM file_extraction_requests WHERE request_id=%s",
                (values["request_id"],),
            ).fetchone()[0]
            == winner
        )


@pytest.mark.parametrize(
    "change",
    [
        "request_digest='a'||substring(request_digest,2)",
        "result_id=gen_random_uuid()",
        "actor_user_id='other-actor'",
        "claim_token=gen_random_uuid()",
        "input_sha256=repeat('a',64)",
    ],
)
def test_bound_identity_and_token_are_immutable(extraction_prepared, world, change):
    import psycopg
    from psycopg import sql

    values = seeded_request(world, extraction_prepared)
    bind_request(world, extraction_prepared, values)
    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                conn.execute(
                    sql.SQL("UPDATE file_extraction_requests SET {} WHERE request_id=%s").format(
                        sql.SQL(change)
                    ),
                    (values["request_id"],),
                )
        assert caught.value.sqlstate == "23514"


@pytest.mark.parametrize(
    "change",
    [
        "filename='Changed.txt'",
        "deleted_at=timezone('UTC',clock_timestamp())",
        "owner_id='missing-owner'",
    ],
)
def test_input_change_refuses_without_terminal(extraction_prepared, world, change):
    import psycopg
    from psycopg import sql

    values = seeded_request(world, extraction_prepared)
    bind_request(world, extraction_prepared, values)
    # The owner FK case instead uses another existing actor.
    if change.startswith("owner_id"):
        with Session(world.engine) as db:
            from miy_api.domains.auth.models import User

            other = str(uuid4())
            db.add(
                User(
                    id=other,
                    login_id=other,
                    email="synthetic-other@example.test",
                    password_hash="synthetic",
                    full_name="Other",
                )
            )
            db.commit()
        change = "owner_id='" + other + "'"
    with world.connect(extraction_prepared.source) as conn:
        conn.execute(
            sql.SQL("UPDATE file_manager_files SET {} WHERE id=%s").format(sql.SQL(change)),
            (values["file_id"],),
        )
    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                terminal_parts(conn, values, sha256(b"Synthetic text").hexdigest())
                finish(conn, values, "ready")
        assert caught.value.sqlstate == "55000"
        assert caught.value.diag.message_primary == "file_extraction_input_stale"


@pytest.mark.parametrize(
    "ambient",
    [
        "GRANT SELECT (password_hash) ON users TO {role}",
        "GRANT SELECT ON users TO {role}",
        "GRANT SELECT (token_hash) ON auth_sessions TO {role}",
        "GRANT SELECT (login_id) ON users TO PUBLIC",
        "GRANT UPDATE (status) ON users TO {role}",
        "GRANT SELECT ON retrieval_partitions TO {role}",
        "GRANT EXECUTE ON FUNCTION public.miy_file_extraction_admit(uuid) TO {role} WITH GRANT OPTION",
    ],
)
def test_ambient_expansion_refused_without_grant(extraction_prepared, world, ambient):
    from psycopg import sql
    from test_file_projection_roles import grants
    from miy_api.domains.official_apps.writer import WriterControlError

    role = world.role()
    with world.connect() as conn:
        conn.execute(sql.SQL(ambient).format(role=sql.Identifier(role)))
    before = grants(world, role)
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError):
            prepare_file_extraction_principal(
                db,
                world.actor,
                role_name=role,
                identity=extraction_prepared.identity,
                expected=extraction_prepared.identity,
                expected_state="active",
            )
        db.rollback()
    assert grants(world, role) == before
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM official_writer_principals WHERE role_name=%s", (role,)
            ).fetchone()[0]
            == 0
        )


def test_current_source_revocation_and_read_admission(extraction_prepared, world):
    import psycopg
    from miy_api.domains.official_apps.writer_roles import revoke_principal

    values = seeded_request(world, extraction_prepared)
    bind_request(world, extraction_prepared, values)
    with Session(world.engine) as db:
        revoke_principal(
            db,
            world.actor,
            role_oid=extraction_prepared.source_oid,
            expected=extraction_prepared.identity,
            expected_state="active",
        )
        db.commit()
    with world.connect(extraction_prepared.source) as conn:
        for identifier in (None, values["request_id"]):
            with pytest.raises(psycopg.Error) as caught:
                with conn.transaction():
                    conn.execute("SELECT public.miy_file_extraction_admit(%s::uuid)", (identifier,))
            assert caught.value.sqlstate == "55000"


def test_admission_holds_current_principal_through_commit(extraction_prepared, world):
    from concurrent.futures import ThreadPoolExecutor
    from test_official_writer_roles import wait_for_blocker

    holder = world.connect(extraction_prepared.source)
    writer = world.connect()
    try:
        holder.execute("SELECT public.miy_file_extraction_admit(NULL)")
        holder_pid = holder.info.backend_pid

        def revoke():
            writer.execute(
                "UPDATE official_writer_principals SET revoked_at=timezone('UTC',clock_timestamp()) WHERE role_oid=%s",
                (extraction_prepared.source_oid,),
            )
            writer.commit()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(revoke)
            try:
                wait_for_blocker(world, holder_pid)
                assert not future.done()
            finally:
                holder.commit()
            future.result(timeout=5)
    finally:
        holder.close()
        writer.close()


def test_history_survives_source_identity_replacement(extraction_prepared, world):
    import psycopg

    values = seeded_request(world, extraction_prepared)
    _, checksum = bind_request(world, extraction_prepared, values)
    with world.connect(extraction_prepared.source) as conn:
        error = terminal_parts(conn, values, checksum)
        digest = finish(conn, values, "ready", error)
    drain = move(
        world,
        extraction_prepared.identity,
        "active",
        state="draining",
        artifact=extraction_prepared.identity.artifact,
    )
    identity = WriterIdentity(SUITE_SCOPE, "legacy", drain.generation + 1, "sha256:" + "d" * 64)
    source = world.role()
    with Session(world.engine) as db:
        assert prepare_file_extraction_principal(
            db,
            world.actor,
            role_name=source,
            identity=identity,
            expected=drain,
            expected_state="draining",
        ).profile_prepared
        db.commit()
    move(world, drain, "draining", state="active", artifact=identity.artifact)
    with world.connect(source) as conn:
        conn.execute("SELECT public.miy_file_extraction_admit(NULL)")
        assert (
            conn.execute(
                "SELECT result_digest FROM file_extraction_requests WHERE request_id=%s",
                (values["request_id"],),
            ).fetchone()[0]
            == digest
        )
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                conn.execute(
                    "SELECT public.miy_file_extraction_admit(%s::uuid)", (values["request_id"],)
                )
        assert caught.value.sqlstate == "55000"


@pytest.mark.parametrize("malformed", ["blank", "oversized_text", "oversized_metadata"])
def test_sql_terminal_artifact_bounds(extraction_prepared, world, malformed):
    import psycopg

    values = seeded_request(world, extraction_prepared)
    _, checksum = bind_request(world, extraction_prepared, values)
    text_value = (
        " "
        if malformed == "blank"
        else "x" * 240001
        if malformed == "oversized_text"
        else "Synthetic text"
    )
    metadata = {"synthetic": "x" * 65537} if malformed == "oversized_metadata" else {}
    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                terminal_parts(conn, values, checksum, text_value=text_value, metadata=metadata)
                finish(conn, values, "ready")
        assert caught.value.sqlstate == "23514"
        assert caught.value.diag.message_primary == "file_extraction_result_invalid"


def test_copy_terminal_forgery_refused(extraction_prepared, world):
    import psycopg

    values = seeded_request(world, extraction_prepared)
    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                with conn.cursor().copy(
                    "COPY file_extraction_requests(request_id,result_id,event_id,file_id,actor_user_id,execution_ref,parser_policy,request_payload,request_digest,input_fingerprint,state) FROM STDIN"
                ) as copy:
                    copy.write_row(
                        [
                            values[key]
                            for key in (
                                "request_id",
                                "result_id",
                                "event_id",
                                "file_id",
                                "actor_user_id",
                                "execution_ref",
                                "parser_policy",
                                "request_payload",
                                "request_digest",
                                "input_fingerprint",
                            )
                        ]
                        + ["ready"]
                    )
        assert caught.value.sqlstate == "23514"
        assert caught.value.diag.message_primary == "file_extraction_transition_invalid"


def test_empty_core_statement_and_raw_guc_cannot_admit(world):
    import psycopg

    with world.connect() as conn:
        for statement in (
            "INSERT INTO file_extraction_requests(request_id) SELECT gen_random_uuid() WHERE false",
            "TRUNCATE file_extraction_requests",
        ):
            with pytest.raises(psycopg.Error) as caught:
                with conn.transaction():
                    conn.execute("SELECT set_config('miy.official_writer_owner','legacy',true)")
                    conn.execute(statement)
            assert caught.value.sqlstate == "55000"


def test_sql_terminal_history_never_rewrites(extraction_prepared, world):
    import psycopg

    values = seeded_request(world, extraction_prepared)
    _, checksum = bind_request(world, extraction_prepared, values)
    with world.connect(extraction_prepared.source) as conn:
        terminal_parts(conn, values, checksum)
        digest = finish(conn, values, "ready")
    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                conn.execute(
                    "UPDATE file_extraction_requests SET result_digest=result_digest WHERE request_id=%s",
                    (values["request_id"],),
                )
        assert caught.value.sqlstate == "55000"
        assert caught.value.diag.message_primary == "file_extraction_terminal_immutable"
        assert (
            conn.execute(
                "SELECT result_digest FROM file_extraction_requests WHERE request_id=%s",
                (values["request_id"],),
            ).fetchone()[0]
            == digest
        )


def test_new_history_capture_refuses_before_dump(extraction_prepared, world, tmp_path):
    import conftest

    values = seeded_request(world, extraction_prepared)
    with world.connect(extraction_prepared.source) as conn:
        insert_request(conn, values)
    target = tmp_path / "not-created.dump"
    with pytest.raises(RuntimeError, match="protocol fixture baseline must be empty"):
        conftest._capture_application_postgres_state(
            world.engine.url.render_as_string(hide_password=False), target
        )
    assert not target.exists()
    with world.connect(extraction_prepared.source) as conn:
        assert conn.execute("SELECT count(*) FROM file_extraction_requests").fetchone()[0] == 1


def test_owned_new_history_reset_rollback_and_trigger_recovery(extraction_prepared, world):
    import conftest
    from sqlalchemy.exc import SQLAlchemyError

    values = seeded_request(world, extraction_prepared)
    _, checksum = bind_request(world, extraction_prepared, values)
    with world.connect(extraction_prepared.source) as conn:
        terminal_parts(conn, values, checksum)
        finish(conn, values, "ready")
        before_history = conn.execute(
            "SELECT to_jsonb(r) FROM file_extraction_requests r"
        ).fetchone()[0]
        before_guards = conn.execute(
            "SELECT tgname,tgenabled,pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid='file_extraction_requests'::regclass ORDER BY tgname"
        ).fetchall()
    with pytest.raises(SQLAlchemyError):
        with world.engine.begin() as connection:
            statements = conftest._truncate_test_database_statements(connection)
            disable = [s for s in statements if "file_extraction_requests DISABLE TRIGGER" in s]
            assert len(disable) == 2
            assert all(
                "miy_file_extraction_history" in s or "miy_file_extraction_writer" in s
                for s in disable
            )
            for statement in disable:
                connection.exec_driver_sql(statement)
            connection.exec_driver_sql("TRUNCATE public.file_extraction_requests")
            connection.exec_driver_sql("SELECT public.synthetic_new_history_restore_failure()")
    with world.connect(extraction_prepared.source) as conn:
        assert (
            conn.execute("SELECT to_jsonb(r) FROM file_extraction_requests r").fetchone()[0]
            == before_history
        )
        assert (
            conn.execute(
                "SELECT tgname,tgenabled,pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid='file_extraction_requests'::regclass ORDER BY tgname"
            ).fetchall()
            == before_guards
        )
    # Only this verified disposable test table is cleared. Canonical source and
    # outbox rows are retained; a real baseline with history was refused above.
    with world.engine.begin() as connection:
        statements = conftest._truncate_test_database_statements(connection)
        for statement in statements:
            if "file_extraction_requests DISABLE TRIGGER" in statement:
                connection.exec_driver_sql(statement)
        connection.exec_driver_sql("TRUNCATE public.file_extraction_requests")
        for statement in statements:
            if "file_extraction_requests ENABLE TRIGGER" in statement:
                connection.exec_driver_sql(statement)
    with world.connect(extraction_prepared.source) as conn:
        assert conn.execute("SELECT count(*) FROM file_extraction_requests").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM official_projection_outbox WHERE event_id=%s",
                (values["event_id"],),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT tgname,tgenabled,pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid='file_extraction_requests'::regclass ORDER BY tgname"
            ).fetchall()
            == before_guards
        )


@pytest.mark.parametrize("world", ["file_effect_20261007"], indirect=True)
def test_fresh_protocol_downgrade_round_trip_preserves_sources(world):
    from alembic import command
    from test_alembic_migrations import _migration_config

    config = _migration_config(world.engine.url.render_as_string(hide_password=False))
    command.downgrade(config, "official_partition_20261007")
    with world.connect() as conn:
        assert (
            conn.execute("SELECT to_regclass('public.file_extraction_requests')").fetchone()[0]
            is None
        )
        assert (
            conn.execute("SELECT count(*) FROM users WHERE id=%s", (world.user_id,)).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 90
        )
    command.upgrade(config, "head")
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM file_extraction_requests").fetchone()[0] == 0
        assert (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "file_effect_20261007"
        )


@pytest.mark.parametrize("world", ["file_effect_20261007"], indirect=True)
@pytest.mark.parametrize("boundary", ["active", "history", "grants"])
def test_protocol_downgrade_preserves_history_and_explicit_retirement(
    extraction_prepared, world, boundary
):
    from test_alembic_migrations import _migration_config

    config = _migration_config(world.engine.url.render_as_string(hide_password=False))
    if boundary == "history":
        values = seeded_request(world, extraction_prepared)
        with world.connect(extraction_prepared.source) as conn:
            insert_request(conn, values)
    if boundary != "active":
        move(
            world,
            extraction_prepared.identity,
            "active",
            state="draining",
            artifact=extraction_prepared.identity.artifact,
        )
    expected = {
        "active": "requires_draining",
        "history": "requires_record_retention",
        "grants": "requires_explicit_retirement",
    }[boundary]
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    # Keep this older owned migration gate independent of later append migrations.
    migration = ScriptDirectory.from_config(config).get_revision("file_extraction_20261007")
    with pytest.raises(RuntimeError, match=expected):
        with world.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.module.downgrade()
    with world.connect() as conn:
        assert (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "file_effect_20261007"
        )
        assert conn.execute("SELECT count(*) FROM file_extraction_requests").fetchone()[0] == (
            1 if boundary == "history" else 0
        )


@pytest.mark.parametrize("operation", ["exact_replay", "caller_rollback"])
def test_new_profile_preparation_transaction_and_replay(extraction_prepared, world, operation):
    from test_file_projection_roles import grants

    role = extraction_prepared.source if operation == "exact_replay" else world.role()
    before = grants(world, role)
    with world.connect() as conn:
        before_audit = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(world.engine) as db:
        result = prepare_file_extraction_principal(
            db,
            world.actor,
            role_name=role,
            identity=extraction_prepared.identity,
            expected=extraction_prepared.identity,
            expected_state="active",
        )
        assert result.profile_prepared
        if operation == "exact_replay":
            db.commit()
        else:
            db.rollback()
    assert grants(world, role) == before
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == before_audit
        assert conn.execute(
            "SELECT count(*) FROM official_writer_principals WHERE role_name=%s", (role,)
        ).fetchone()[0] == (1 if operation == "exact_replay" else 0)


def add_corpus_input(world, prepared, values, *, metadata=False):
    from test_file_projection_roles import reader_engine
    from miy_api.domains.files.models import FileManagerCorpus, FileManagerFileSourceMetadata

    corpus_id = str(uuid4())
    engine = reader_engine(world, prepared.source)
    try:
        with Session(engine) as db:
            db.add(
                FileManagerCorpus(
                    id=corpus_id,
                    created_by_id=world.user_id,
                    name="Synthetic",
                    access_scope_kind="company",
                    retrieval_partition_id=prepared.partition,
                )
            )
            db.flush()
            file = db.get(FileManagerFile, values["file_id"])
            file.corpus_id = corpus_id
            if metadata:
                db.add(
                    FileManagerFileSourceMetadata(
                        file_id=file.id,
                        corpus_id=corpus_id,
                        external_id="synthetic",
                        external_id_sha256="a" * 64,
                        source_kind="synthetic",
                        source_id="synthetic",
                        source_id_sha256="b" * 64,
                        source_version="synthetic-v1",
                        content_checksum=sha256(b"Synthetic text").hexdigest(),
                        raw_metadata={},
                        acl_resolved=True,
                    )
                )
            db.flush()
            envelope = json.loads(values["request_payload"])
            data = json.loads(envelope["input_canonical"])
            data.update(
                corpus_id=corpus_id,
                updated_at=file.updated_at.isoformat(timespec="microseconds"),
                source_version="synthetic-v1" if metadata else None,
                source_content_checksum=sha256(b"Synthetic text").hexdigest() if metadata else None,
            )
            envelope["input_canonical"] = compact(data)
            values["input_fingerprint"] = sha256(envelope["input_canonical"].encode()).hexdigest()
            values["request_payload"] = compact(envelope)
            values["request_digest"] = sha256(values["request_payload"].encode()).hexdigest()
            db.commit()
    finally:
        engine.dispose()
    return corpus_id


@pytest.mark.parametrize(
    "mutation",
    [
        "file_update",
        "file_delete",
        "tip",
        "metadata_insert",
        "metadata_version",
        "metadata_checksum",
        "metadata_delete",
        "corpus_partition",
        "corpus_scope",
        "corpus_delete",
    ],
)
@pytest.mark.parametrize("mode", ["before", "after"])
def test_actual_immediate_constraints_seal_all_captured_inputs(
    extraction_prepared, world, mutation, mode
):
    import psycopg

    values = seeded_request(world, extraction_prepared)
    corpus_id = add_corpus_input(
        world,
        extraction_prepared,
        values,
        metadata=mutation in {"metadata_version", "metadata_checksum", "metadata_delete"},
    )
    _, checksum = bind_request(world, extraction_prepared, values)
    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as error:
            with conn.transaction():
                if mode == "before":
                    conn.execute("SET CONSTRAINTS miy_file_extraction_terminal IMMEDIATE")
                terminal_parts(conn, values, checksum)
                finish(conn, values, "ready")
                if mode == "after":
                    conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
                if mutation == "file_update":
                    conn.execute(
                        "UPDATE file_manager_files SET extraction_text='invalid after terminal' WHERE id=%s",
                        (values["file_id"],),
                    )
                elif mutation == "file_delete":
                    conn.execute("DELETE FROM file_manager_files WHERE id=%s", (values["file_id"],))
                elif mutation == "tip":
                    intent = ProjectionIntent(
                        resource_type="file_manager_file",
                        resource_id=values["file_id"],
                        retrieval_partition_id=extraction_prepared.partition,
                        change_kind="delete",
                        desired_state="deleted",
                        operation="delete",
                    )
                    conn.execute(
                        "INSERT INTO official_projection_outbox(event_id,resource_type,resource_id,source_revision,payload,payload_digest) VALUES(%s,%s,%s,3,%s,%s)",
                        (
                            str(uuid4()),
                            intent.resource_type,
                            intent.resource_id,
                            intent.canonical(),
                            intent.digest(),
                        ),
                    )
                elif mutation == "metadata_insert":
                    conn.execute(
                        "INSERT INTO file_manager_file_source_metadata(file_id,corpus_id,external_id,external_id_sha256,source_kind,source_id,source_id_sha256,source_version,content_checksum,raw_metadata,acl_resolved,created_at,updated_at) VALUES(%s,%s,'synthetic',%s,'synthetic','synthetic',%s,'changed',%s,'{}',true,now(),now())",
                        (values["file_id"], corpus_id, "a" * 64, "b" * 64, checksum),
                    )
                elif mutation == "metadata_version":
                    conn.execute(
                        "UPDATE file_manager_file_source_metadata SET source_version='changed' WHERE file_id=%s",
                        (values["file_id"],),
                    )
                elif mutation == "metadata_checksum":
                    conn.execute(
                        "UPDATE file_manager_file_source_metadata SET content_checksum=%s WHERE file_id=%s",
                        ("d" * 64, values["file_id"]),
                    )
                elif mutation == "metadata_delete":
                    conn.execute(
                        "DELETE FROM file_manager_file_source_metadata WHERE file_id=%s",
                        (values["file_id"],),
                    )
                elif mutation == "corpus_partition":
                    conn.execute(
                        "UPDATE file_manager_corpora SET retrieval_partition_id=NULL WHERE id=%s",
                        (corpus_id,),
                    )
                elif mutation == "corpus_scope":
                    conn.execute(
                        "UPDATE file_manager_corpora SET access_scope_kind='owner' WHERE id=%s",
                        (corpus_id,),
                    )
                else:
                    conn.execute("DELETE FROM file_manager_corpora WHERE id=%s", (corpus_id,))
        assert error.value.sqlstate == "55000"
        assert error.value.diag.message_primary == "file_extraction_terminal_transaction_closed"
    with world.connect(extraction_prepared.source) as conn:
        assert conn.execute(
            "SELECT state,result_digest FROM file_extraction_requests WHERE request_id=%s",
            (values["request_id"],),
        ).fetchone() == ("input_bound", None)
        assert (
            conn.execute(
                "SELECT extraction_status FROM file_manager_files WHERE id=%s", (values["file_id"],)
            ).fetchone()[0]
            == "pending"
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM official_projection_outbox WHERE event_id=%s",
                (values["event_id"],),
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("mode", ["deferred", "immediate"])
def test_top_file_and_event_with_subtransaction_terminal_refused(extraction_prepared, world, mode):
    import psycopg

    values = seeded_request(world, extraction_prepared)
    _, checksum = bind_request(world, extraction_prepared, values)
    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as error:
            with conn.transaction():
                if mode == "immediate":
                    conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
                terminal_parts(conn, values, checksum)
                with conn.transaction():
                    finish(conn, values, "ready")
        assert error.value.sqlstate == "55000"
        assert error.value.diag.message_primary == "file_extraction_terminal_outer_required"
    with world.connect(extraction_prepared.source) as conn:
        assert (
            conn.execute(
                "SELECT state FROM file_extraction_requests WHERE request_id=%s",
                (values["request_id"],),
            ).fetchone()[0]
            == "input_bound"
        )


def test_metadata_reparent_into_terminal_is_sealed_and_other_file_is_allowed(
    extraction_prepared, world
):
    import psycopg
    from test_file_projection_roles import reader_engine
    from miy_api.domains.files.models import FileManagerFileSourceMetadata

    values = seeded_request(world, extraction_prepared)
    other = seeded_request(world, extraction_prepared)
    corpus_id = add_corpus_input(world, extraction_prepared, values)
    engine = reader_engine(world, extraction_prepared.source)
    try:
        with Session(engine) as db:
            db.add(
                FileManagerFileSourceMetadata(
                    file_id=other["file_id"],
                    corpus_id=corpus_id,
                    external_id="synthetic",
                    external_id_sha256="a" * 64,
                    source_kind="synthetic",
                    source_id="synthetic",
                    source_id_sha256="b" * 64,
                    source_version="v1",
                    content_checksum=sha256(b"Synthetic text").hexdigest(),
                    raw_metadata={},
                    acl_resolved=True,
                )
            )
            db.commit()
    finally:
        engine.dispose()
    _, checksum = bind_request(world, extraction_prepared, values)
    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as error:
            with conn.transaction():
                conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
                terminal_parts(conn, values, checksum)
                finish(conn, values, "ready")
                conn.execute(
                    "UPDATE file_manager_file_source_metadata SET source_version='other allowed' WHERE file_id=%s",
                    (other["file_id"],),
                )
                conn.execute(
                    "UPDATE file_manager_file_source_metadata SET file_id=%s WHERE file_id=%s",
                    (values["file_id"], other["file_id"]),
                )
        assert error.value.diag.message_primary == "file_extraction_terminal_transaction_closed"
    with world.connect(extraction_prepared.source) as conn:
        conn.execute(
            "UPDATE file_manager_file_source_metadata SET source_version='later allowed' WHERE file_id=%s",
            (other["file_id"],),
        )


def test_terminal_seal_allows_later_transaction_same_file_and_preserves_receipt(
    extraction_prepared, world
):
    from miy_api.domains.retrieval.partitioning import create_managed_partition

    values = seeded_request(world, extraction_prepared)
    corpus_id = add_corpus_input(world, extraction_prepared, values, metadata=True)
    _, checksum = bind_request(world, extraction_prepared, values)
    with world.connect(extraction_prepared.source) as conn:
        conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        terminal_parts(conn, values, checksum)
        digest = finish(conn, values, "ready")
        receipt = conn.execute(
            "SELECT to_jsonb(r) FROM file_extraction_requests r WHERE request_id=%s",
            (values["request_id"],),
        ).fetchone()[0]

    # Core allocation remains separate; the Source receives no partition authority.
    with Session(world.engine) as db:
        later_partition = str(
            create_managed_partition(
                db, source_namespace="files", candidate_scope_kind="company"
            ).id
        )
        db.commit()
    later_event_id = str(uuid4())
    intent = ProjectionIntent(
        resource_type="file_manager_file",
        resource_id=values["file_id"],
        retrieval_partition_id=later_partition,
        change_kind="content",
        desired_state="active",
        operation="upsert",
        content_checksum=checksum,
    )
    with world.connect(extraction_prepared.source) as conn:
        conn.execute(
            "UPDATE file_manager_corpora SET retrieval_partition_id=%s WHERE id=%s",
            (later_partition, corpus_id),
        )
        conn.execute(
            "UPDATE file_manager_files SET filename='Later.txt',retrieval_partition_id=%s,updated_at=timezone('UTC',clock_timestamp()) WHERE id=%s",
            (later_partition, values["file_id"]),
        )
        conn.execute(
            "UPDATE file_manager_file_source_metadata SET source_version='later-v2',content_checksum=%s WHERE file_id=%s",
            (checksum, values["file_id"]),
        )
        conn.execute(
            "INSERT INTO official_projection_outbox(event_id,resource_type,resource_id,source_revision,payload,payload_digest) VALUES(%s,%s,%s,3,%s,%s)",
            (
                later_event_id,
                intent.resource_type,
                intent.resource_id,
                intent.canonical(),
                intent.digest(),
            ),
        )
    with world.connect(extraction_prepared.source) as conn:
        conn.execute("SELECT public.miy_file_extraction_admit(NULL)")
        assert (
            conn.execute(
                "SELECT to_jsonb(r) FROM file_extraction_requests r WHERE request_id=%s",
                (values["request_id"],),
            ).fetchone()[0]
            == receipt
        )
        assert receipt["result_digest"] == digest
        assert conn.execute(
            "SELECT f.filename,f.retrieval_partition_id::text,c.retrieval_partition_id::text,m.source_version,m.content_checksum FROM file_manager_files f JOIN file_manager_corpora c ON c.id=f.corpus_id JOIN file_manager_file_source_metadata m ON m.file_id=f.id WHERE f.id=%s",
            (values["file_id"],),
        ).fetchone() == ("Later.txt", later_partition, later_partition, "later-v2", checksum)
        assert conn.execute(
            "SELECT source_revision,payload_digest FROM official_projection_outbox WHERE event_id=%s",
            (later_event_id,),
        ).fetchone() == (3, intent.digest())


@pytest.mark.parametrize("outcome", ["ready", "unsupported", "failed"])
def test_sql_terminal_cannot_retain_ocr_hold(extraction_prepared, world, outcome):
    import psycopg

    values = seeded_request(world, extraction_prepared)
    _, checksum = bind_request(world, extraction_prepared, values)
    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as error:
            with conn.transaction():
                terminal_parts(conn, values, checksum, outcome=outcome, event=outcome != "failed")
                digest = conn.execute(
                    "SELECT public.miy_file_extraction_result_digest(%s::uuid,%s)",
                    (values["request_id"], outcome),
                ).fetchone()[0]
                conn.execute(
                    "UPDATE file_extraction_requests SET state=%s,result_digest=%s,hold_reason='ocr_required' WHERE request_id=%s",
                    (outcome, digest, values["request_id"]),
                )
        assert error.value.sqlstate == "23514"
        assert error.value.diag.message_primary == "file_extraction_transition_invalid"
    with world.connect(extraction_prepared.source) as conn:
        assert conn.execute(
            "SELECT state,hold_reason,result_digest FROM file_extraction_requests WHERE request_id=%s",
            (values["request_id"],),
        ).fetchone() == ("input_bound", None, None)


@pytest.mark.parametrize("drift", ["disabled", "missing", "false_predicate", "body"])
def test_fixed_seal_drift_refused_before_profile_grants(extraction_prepared, world, drift):
    from test_file_projection_roles import grants
    from miy_api.domains.official_apps.writer import WriterControlError

    role = world.role()
    before = grants(world, role)
    with world.connect() as conn:
        audit = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
        if drift == "disabled":
            conn.execute(
                "ALTER TABLE file_manager_files DISABLE TRIGGER miy_file_extraction_seal_file"
            )
        elif drift == "missing":
            conn.execute(
                "DROP TRIGGER miy_file_extraction_seal_metadata ON file_manager_file_source_metadata"
            )
        elif drift == "false_predicate":
            conn.execute("DROP TRIGGER miy_file_extraction_seal_file ON file_manager_files")
            conn.execute(
                "CREATE TRIGGER miy_file_extraction_seal_file BEFORE UPDATE OR DELETE ON file_manager_files FOR EACH ROW WHEN (false) EXECUTE FUNCTION miy_file_extraction_seal_terminal()"
            )
        else:
            conn.execute(
                "CREATE OR REPLACE FUNCTION public.miy_file_extraction_seal_terminal() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN RETURN NEW; END $$"
            )
    with Session(world.engine) as db:
        with pytest.raises(
            WriterControlError, match="file_extraction_(function|trigger)_contract_invalid"
        ):
            prepare_file_extraction_principal(
                db,
                world.actor,
                role_name=role,
                identity=extraction_prepared.identity,
                expected=extraction_prepared.identity,
                expected_state="active",
            )
        db.rollback()
    assert grants(world, role) == before
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == audit
        assert (
            conn.execute(
                "SELECT count(*) FROM official_writer_principals WHERE role_name=%s", (role,)
            ).fetchone()[0]
            == 0
        )
