"""Owned projection journal in the same database/transaction as source records."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from uuid import UUID

from psycopg.rows import dict_row
from miy_api.domains.independent_apps.data_store import PostgresAppData, projection_lock


def _row(conn, query, parameters):
    with conn.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(query, parameters).fetchone()


@dataclass(frozen=True)
class Projection:
    collection: str
    owner_id: str
    record_id: str
    sequence: int
    deleted: bool
    payload: dict
    keyword_applied: bool
    semantic_applied: bool

    @property
    def point_id(self):
        # UUID is derived by the Core, not chosen by an app query or engine hit.
        return str(
            UUID(
                bytes=hashlib.sha256(
                    projection_lock(self.collection, self.owner_id, self.record_id).encode()
                ).digest()[:16]
            )
        )


class SearchSourceStore:
    def __init__(self, data: PostgresAppData):
        self.data = data

    @contextmanager
    def connection(self, installation, binding):
        database, migrator, gateway = self.data.names(installation.id)
        with self.data._connect(database=database, role=migrator) as conn:
            self.data._preflight(conn, database, (migrator, gateway))
            self.data._identity(
                conn, installation.id, installation.app_id, installation.environment
            )
            self.data._search_identity(conn)
            actual = conn.execute(
                "SELECT workspace_id::text,search_spec_sha256,active FROM miy_data.search_generations WHERE generation=%s",
                (binding.generation,),
            ).fetchone()
            if actual != (binding.workspace_id, binding.search_spec_sha256, True):
                from miy_api.domains.independent_apps.data_store import DataStoreError

                raise DataStoreError("data_schema_identity_mismatch")
            yield conn

    @contextmanager
    def next_projection(self, installation, binding):
        generation = binding.generation
        with self.connection(installation, binding) as conn:
            key = conn.execute(
                "SELECT h.collection,h.owner_id,h.record_id FROM miy_data.projection_heads h "
                "JOIN miy_data.search_outbox o USING(collection,owner_id,record_id,sequence) "
                "WHERE o.generation=%s AND NOT o.completed AND NOT EXISTS(SELECT 1 FROM miy_data.search_outbox x "
                "WHERE x.generation=o.generation AND x.collection=h.collection AND x.owner_id=h.owner_id AND x.record_id=h.record_id AND x.held) "
                "ORDER BY h.collection,h.owner_id,h.record_id LIMIT 1",
                (generation,),
            ).fetchone()
            if key is None:
                yield None
                return
            lock = projection_lock(*key)
            if not conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,0))", (lock,)
            ).fetchone()[0]:
                yield None
                return
            try:
                conn.execute("SELECT set_config('miy.actor_id',%s,true)", (key[1],))
                row = _row(
                    conn,
                    "SELECT h.collection,h.owner_id,h.record_id,h.sequence,h.deleted,"
                    "o.keyword_applied,o.semantic_applied,r.payload "
                    "FROM miy_data.projection_heads h JOIN miy_data.search_outbox o "
                    "USING(collection,owner_id,record_id,sequence) "
                    "LEFT JOIN miy_data.records r ON r.id=h.record_id AND r.owner_id=h.owner_id AND r.collection=h.collection "
                    "WHERE h.collection=%s AND h.owner_id=%s AND h.record_id=%s AND o.generation=%s AND NOT o.completed AND NOT o.held "
                    "AND NOT EXISTS(SELECT 1 FROM miy_data.search_outbox x WHERE x.generation=o.generation AND x.collection=h.collection AND x.owner_id=h.owner_id AND x.record_id=h.record_id AND x.held)",
                    (*key, generation),
                )
                conn.commit()  # session advisory fence remains across acknowledged phase commits
                if row is None:
                    yield None
                else:
                    row["record_id"] = str(row["record_id"])
                    row["payload"] = row["payload"] or {}
                    yield conn, Projection(**row)
            finally:
                conn.rollback()
                conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock,))

    def has_held(self, installation, binding):
        with self.connection(installation, binding) as conn:
            return conn.execute(
                "SELECT EXISTS(SELECT 1 FROM miy_data.search_outbox WHERE generation=%s AND held)",
                (binding.generation,),
            ).fetchone()[0]

    @staticmethod
    def acknowledge(conn, projection, phase, generation):
        if phase not in {"keyword", "semantic", "complete", "held"}:
            raise ValueError("Unsupported projection phase")
        column = {
            "keyword": "keyword_applied",
            "semantic": "semantic_applied",
            "complete": "completed",
            "held": "held",
        }[phase]
        # SQL identifier comes exclusively from the fixed mapping above.
        conn.execute(
            f"UPDATE miy_data.search_outbox SET {column}=true WHERE generation=%s AND collection=%s AND owner_id=%s AND record_id=%s AND sequence=%s",
            (
                generation,
                projection.collection,
                projection.owner_id,
                UUID(projection.record_id),
                projection.sequence,
            ),
        )
        if phase == "complete":
            conn.execute(
                "UPDATE miy_data.search_outbox SET completed=true WHERE generation=%s AND collection=%s AND owner_id=%s AND record_id=%s AND sequence<%s AND NOT held",
                (
                    generation,
                    projection.collection,
                    projection.owner_id,
                    UUID(projection.record_id),
                    projection.sequence,
                ),
            )
        conn.commit()

    def current_records(self, identity, collection, candidates):
        """Never disclose engine payloads; hydrate each hit under source RLS/version."""
        result = []
        with self.data._transaction(identity) as conn:
            self.data._search_identity(conn)
            for candidate in candidates:
                row = _row(
                    conn,
                    "SELECT r.id,r.payload,r.version,r.created_at,r.updated_at,h.sequence FROM miy_data.records r "
                    "JOIN miy_data.projection_heads h ON h.record_id=r.id AND h.owner_id=r.owner_id AND h.collection=r.collection "
                    "WHERE r.id=%s AND r.collection=%s AND r.owner_id=%s AND NOT h.deleted AND h.sequence=%s",
                    (UUID(candidate.record_id), collection, identity.user_id, candidate.sequence),
                )
                if row is not None:
                    row.pop("sequence")
                    result.append({"record": row, "score": candidate.score})
        return result
