"""Core-owned, versioned PostgreSQL storage for independent app records.

The app never receives a database credential or chooses SQL/actor identity. RLS
is defence in depth around a gateway whose DML credential is held by the core.
Provisioning is explicit executor work; a data request cannot create a database.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from typing import Iterator
from uuid import UUID, uuid4, uuid5

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from miy_api.domains.independent_apps.contracts import AppIdentityOut

PROFILE = "web-api-postgres-v1"
VERSION = 1
MIGRATION = """
CREATE SCHEMA miy_data;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE TABLE miy_data.installation (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 installation_id uuid NOT NULL, app_id text NOT NULL,
 environment text NOT NULL CHECK(environment IN ('development','production')),
 version integer NOT NULL, checksum text NOT NULL
);
CREATE TABLE miy_data.migrations (
 request_id uuid PRIMARY KEY, artifact_digest text NOT NULL,
 version integer NOT NULL, checksum text NOT NULL,
 applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE miy_data.records (
 id uuid PRIMARY KEY, collection varchar(64) NOT NULL, owner_id text NOT NULL,
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload) = 'object'),
 version integer NOT NULL DEFAULT 1 CHECK(version > 0),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX records_owner_collection ON miy_data.records(owner_id,collection,id);
ALTER TABLE miy_data.records ENABLE ROW LEVEL SECURITY;
ALTER TABLE miy_data.records FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_records ON miy_data.records
 USING(owner_id = current_setting('miy.actor_id', true))
 WITH CHECK(owner_id = current_setting('miy.actor_id', true));
"""
CHECKSUM = "sha256:" + hashlib.sha256(MIGRATION.encode()).hexdigest()
# The original data v1 checksum and migration journal are immutable. Search is an
# explicitly prepared additive extension, not an implicit upgrade on a data read.
SEARCH_VERSION = 1
SEARCH_MIGRATION = """
CREATE TABLE miy_data.search_schema (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 version integer NOT NULL, checksum text NOT NULL);
CREATE TABLE miy_data.search_migrations (request_id uuid PRIMARY KEY, artifact_digest text NOT NULL,
 version integer NOT NULL, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE miy_data.search_generations (generation integer PRIMARY KEY CHECK(generation>0),
 workspace_id uuid NOT NULL, search_spec_sha256 text NOT NULL, active boolean NOT NULL DEFAULT true);
CREATE TABLE miy_data.projection_heads (
 collection varchar(64) NOT NULL, owner_id text NOT NULL, record_id uuid NOT NULL,
 sequence bigint NOT NULL CHECK(sequence>0), deleted boolean NOT NULL,
 PRIMARY KEY(collection,owner_id,record_id));
CREATE TABLE miy_data.search_outbox (
 generation integer NOT NULL REFERENCES miy_data.search_generations(generation),
 collection varchar(64) NOT NULL, owner_id text NOT NULL, record_id uuid NOT NULL,
 sequence bigint NOT NULL CHECK(sequence>0), keyword_applied boolean NOT NULL DEFAULT false,
 semantic_applied boolean NOT NULL DEFAULT false, completed boolean NOT NULL DEFAULT false,
 held boolean NOT NULL DEFAULT false,
 PRIMARY KEY(generation,collection,owner_id,record_id,sequence));
ALTER TABLE miy_data.projection_heads ENABLE ROW LEVEL SECURITY;
ALTER TABLE miy_data.search_outbox ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_projection_heads ON miy_data.projection_heads
 USING(owner_id=current_setting('miy.actor_id',true))
 WITH CHECK(owner_id=current_setting('miy.actor_id',true));
CREATE POLICY owner_search_outbox ON miy_data.search_outbox
 USING(owner_id=current_setting('miy.actor_id',true))
 WITH CHECK(owner_id=current_setting('miy.actor_id',true));
"""
SEARCH_CHECKSUM = "sha256:" + hashlib.sha256(SEARCH_MIGRATION.encode()).hexdigest()
_COLLECTION = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_APP = re.compile(r"[a-z][a-z0-9-]{1,63}")
_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
_RECORD_KEY_NAMESPACE = UUID("b4d3a844-3f26-5f54-80b5-0d30b15b9cb5")


class DataStoreError(Exception):
    """Safe public code, never a driver message/connection string."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def projection_lock(collection, owner_id, record_id):
    return json.dumps(
        ["miy-app-search", collection, owner_id, str(record_id)], separators=(",", ":")
    )


@dataclass(frozen=True)
class DataMigrationEvidence:
    installation_id: str
    request_id: str
    artifact_digest: str
    version: int = VERSION
    checksum: str = CHECKSUM


class PostgresAppData:
    def __init__(self, admin_dsn: str, credential_key: str):
        if len(credential_key) < 32:
            raise DataStoreError("data_configuration_invalid")
        self._dsn = admin_dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        self._key = credential_key.encode()

    @staticmethod
    def names(installation_id: str) -> tuple[str, str, str]:
        identity = UUID(installation_id).hex
        return "miy_app_" + identity, "miy_m_" + identity, "miy_d_" + identity

    def _password(self, role: str) -> str:
        return hmac.new(self._key, ("miy-app-data-v1:" + role).encode(), hashlib.sha256).hexdigest()

    def _connect(self, *, database=None, role=None, autocommit=False, provisioning=False):
        if provisioning and (database is not None or role is not None or not autocommit):
            raise DataStoreError("data_configuration_invalid")
        # CREATE DATABASE includes storage work, unlike a bounded app DML request.
        # Only explicit Core administrative preparation receives this fixed budget.
        statement_ms = 30000 if provisioning else 5000
        args = {
            "connect_timeout": 5,
            "options": f"-c statement_timeout={statement_ms} -c lock_timeout=3000",
        }
        if database is not None:
            args["dbname"] = database
        if role is not None:
            args.update(user=role, password=self._password(role))
        return psycopg.connect(make_conninfo(self._dsn, **args), autocommit=autocommit)

    @staticmethod
    def _preflight(conn, database: str | None = None, roles=()) -> None:
        # PostgreSQL gives PUBLIC CONNECT by default. Never "repair" other DBs.
        public = conn.execute(
            "SELECT datname FROM pg_database d, "
            "LATERAL aclexplode(coalesce(d.datacl, acldefault('d',d.datdba))) a "
            "WHERE datallowconn AND a.grantee=0 AND a.privilege_type='CONNECT'"
        ).fetchall()
        if public:
            raise DataStoreError("data_cluster_public_connect")
        for role in roles:
            if conn.execute(
                "SELECT 1 FROM pg_database WHERE datallowconn AND datname<>%s "
                "AND has_database_privilege(%s,oid,'CONNECT') LIMIT 1",
                (database, role),
            ).fetchone():
                raise DataStoreError("data_role_cross_database_access")

    def prepare(
        self,
        *,
        installation_id: str,
        app_id: str,
        environment: str,
        artifact_digest: str,
        request_id: str,
    ) -> DataMigrationEvidence:
        installation_id, request_id = str(UUID(installation_id)), str(UUID(request_id))
        if not _APP.fullmatch(app_id) or environment not in {"development", "production"}:
            raise DataStoreError("data_identity_invalid")
        if not _DIGEST.fullmatch(artifact_digest):
            raise DataStoreError("data_artifact_invalid")
        database, migrator, gateway = self.names(installation_id)
        marker = f"miy-independent-data-v1:{installation_id}:{app_id}:{environment}"
        try:
            with self._connect(autocommit=True, provisioning=True) as conn:
                # Session advisory lock also fences CREATE DATABASE (not transactional).
                conn.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (marker,))
                self._preflight(conn)
                with conn.transaction():
                    for role in (migrator, gateway):
                        existing = conn.execute(
                            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,"
                            "shobj_description(oid,'pg_authid'),rolcanlogin FROM pg_roles "
                            "WHERE rolname=%s",
                            (role,),
                        ).fetchone()
                        if existing is None:
                            conn.execute(
                                sql.SQL(
                                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                                    "NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD {}"
                                ).format(sql.Identifier(role), sql.Literal(self._password(role)))
                            )
                            conn.execute(
                                sql.SQL("COMMENT ON ROLE {} IS {}").format(
                                    sql.Identifier(role), sql.Literal(marker)
                                )
                            )
                        elif existing != (False, False, False, False, False, marker, True):
                            raise DataStoreError("data_role_identity_mismatch")
                        if conn.execute(
                            "SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles "
                            "WHERE rolname=%s) LIMIT 1",
                            (role,),
                        ).fetchone():
                            raise DataStoreError("data_role_membership")
                existing = conn.execute(
                    "SELECT pg_get_userbyid(datdba),shobj_description(oid,'pg_database') "
                    "FROM pg_database WHERE datname=%s",
                    (database,),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        sql.SQL(
                            "CREATE DATABASE {} OWNER {} TEMPLATE template0 ALLOW_CONNECTIONS false"
                        ).format(sql.Identifier(database), sql.Identifier(migrator))
                    )
                    with conn.transaction():
                        conn.execute(
                            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                                sql.Identifier(database)
                            )
                        )
                        conn.execute(
                            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                                sql.Identifier(database), sql.Identifier(gateway)
                            )
                        )
                        conn.execute(
                            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                                sql.Identifier(database), sql.Literal(marker)
                            )
                        )
                        conn.execute(
                            sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(
                                sql.Identifier(database)
                            )
                        )
                elif existing != (migrator, marker):
                    # A crash before the marker is committed requires operator inspection.
                    raise DataStoreError("data_database_identity_mismatch")
                self._preflight(conn, database, (migrator, gateway))
                self._migrate(
                    database,
                    migrator,
                    gateway,
                    installation_id,
                    app_id,
                    environment,
                    artifact_digest,
                    request_id,
                )
            return DataMigrationEvidence(installation_id, request_id, artifact_digest)
        except psycopg.Error as exc:
            raise DataStoreError("data_provision_unavailable") from exc

    def _migrate(
        self,
        database,
        migrator,
        gateway,
        installation_id,
        app_id,
        environment,
        artifact_digest,
        request_id,
    ):
        # A changed credential key cannot log in; no password rewrite is performed.
        with self._connect(database=database, role=migrator) as conn:
            if conn.execute("SELECT to_regnamespace('miy_data')").fetchone()[0] is None:
                conn.execute(MIGRATION)
                conn.execute(
                    "INSERT INTO miy_data.installation(installation_id,app_id,environment,"
                    "version,checksum) VALUES(%s,%s,%s,%s,%s)",
                    (installation_id, app_id, environment, VERSION, CHECKSUM),
                )
                conn.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA miy_data TO {}").format(sql.Identifier(gateway))
                )
                conn.execute(
                    sql.SQL("GRANT SELECT ON miy_data.installation TO {}").format(
                        sql.Identifier(gateway)
                    )
                )
                conn.execute(
                    sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON miy_data.records TO {}").format(
                        sql.Identifier(gateway)
                    )
                )
            self._identity(conn, installation_id, app_id, environment)
            previous = conn.execute(
                "SELECT artifact_digest,version,checksum FROM miy_data.migrations WHERE request_id=%s",
                (request_id,),
            ).fetchone()
            expected = (artifact_digest, VERSION, CHECKSUM)
            if previous is not None and previous != expected:
                raise DataStoreError("data_migration_request_conflict")
            if previous is None:
                conn.execute(
                    "INSERT INTO miy_data.migrations(request_id,artifact_digest,version,checksum) "
                    "VALUES(%s,%s,%s,%s)",
                    (request_id, *expected),
                )

    def prepare_search(
        self,
        *,
        installation_id,
        app_id,
        environment,
        artifact_digest,
        request_id,
        generation,
        workspace_id,
        search_spec_sha256,
    ):
        """Prepare fixed search tables under the existing installation migrator only."""
        installation_id, request_id = str(UUID(installation_id)), str(UUID(request_id))
        if not _DIGEST.fullmatch(artifact_digest):
            raise DataStoreError("data_artifact_invalid")
        workspace_id = str(UUID(workspace_id))
        if (
            type(generation) is not int
            or generation < 1
            or not re.fullmatch(r"[a-f0-9]{64}", search_spec_sha256)
        ):
            raise DataStoreError("data_identity_invalid")
        database, migrator, gateway = self.names(installation_id)
        try:
            with self._connect(database=database, role=migrator) as conn:
                self._preflight(conn, database, (migrator, gateway))
                self._identity(conn, installation_id, app_id, environment)
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ("miy-search-schema:" + installation_id,),
                )
                if (
                    conn.execute("SELECT to_regclass('miy_data.search_schema')").fetchone()[0]
                    is None
                ):
                    conn.execute(SEARCH_MIGRATION)
                    conn.execute(
                        "INSERT INTO miy_data.search_schema(version,checksum) VALUES(%s,%s)",
                        (SEARCH_VERSION, SEARCH_CHECKSUM),
                    )
                    conn.execute(
                        sql.SQL("GRANT SELECT ON miy_data.search_schema TO {}").format(
                            sql.Identifier(gateway)
                        )
                    )
                    conn.execute(
                        sql.SQL("GRANT SELECT ON miy_data.search_generations TO {}").format(
                            sql.Identifier(gateway)
                        )
                    )
                    for table in ("projection_heads", "search_outbox"):
                        conn.execute(
                            sql.SQL("GRANT SELECT,INSERT,UPDATE ON miy_data.{} TO {}").format(
                                sql.Identifier(table), sql.Identifier(gateway)
                            )
                        )
                    # This fixed owner migration holds ACCESS EXCLUSIVE until commit;
                    # gateway requests cannot observe the temporary owner-only RLS change.
                    conn.execute("ALTER TABLE miy_data.records NO FORCE ROW LEVEL SECURITY")
                    conn.execute(
                        "INSERT INTO miy_data.projection_heads(collection,owner_id,record_id,sequence,deleted) "
                        "SELECT collection,owner_id,id,1,false FROM miy_data.records"
                    )
                    conn.execute("ALTER TABLE miy_data.records FORCE ROW LEVEL SECURITY")
                self._search_identity(conn)
                previous_generation = conn.execute(
                    "SELECT workspace_id::text,search_spec_sha256,active FROM miy_data.search_generations WHERE generation=%s",
                    (generation,),
                ).fetchone()
                if previous_generation is not None and previous_generation != (
                    workspace_id,
                    search_spec_sha256,
                    True,
                ):
                    raise DataStoreError("data_schema_identity_mismatch")
                if previous_generation is None:
                    conn.execute(
                        "INSERT INTO miy_data.search_generations(generation,workspace_id,search_spec_sha256) VALUES(%s,%s,%s)",
                        (generation, workspace_id, search_spec_sha256),
                    )
                    conn.execute(
                        "INSERT INTO miy_data.search_outbox(generation,collection,owner_id,record_id,sequence) "
                        "SELECT %s,collection,owner_id,record_id,sequence FROM miy_data.projection_heads",
                        (generation,),
                    )
                expected = (artifact_digest, SEARCH_VERSION, SEARCH_CHECKSUM)
                previous = conn.execute(
                    "SELECT artifact_digest,version,checksum FROM miy_data.search_migrations WHERE request_id=%s",
                    (request_id,),
                ).fetchone()
                if previous is not None and previous != expected:
                    raise DataStoreError("data_migration_request_conflict")
                if previous is None:
                    conn.execute(
                        "INSERT INTO miy_data.search_migrations(request_id,artifact_digest,version,checksum) VALUES(%s,%s,%s,%s)",
                        (request_id, *expected),
                    )
        except psycopg.Error as exc:
            raise DataStoreError("data_unavailable") from exc

    @staticmethod
    def _search_identity(conn):
        if conn.execute(
            "SELECT version,checksum FROM miy_data.search_schema WHERE singleton"
        ).fetchone() != (SEARCH_VERSION, SEARCH_CHECKSUM):
            raise DataStoreError("data_schema_identity_mismatch")

    def _record_projection(self, conn, identity, collection, record_id, *, deleted):
        if conn.execute("SELECT to_regclass('miy_data.search_schema')").fetchone()[0] is None:
            return
        # Generation backfill and record publication have one schema fence: a
        # concurrent new generation cannot miss a committed source write.
        conn.execute(
            "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
            ("miy-search-schema:" + identity.installation_id,),
        )
        self._search_identity(conn)
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (projection_lock(collection, identity.user_id, record_id),),
        )
        sequence = conn.execute(
            "INSERT INTO miy_data.projection_heads(collection,owner_id,record_id,sequence,deleted) "
            "VALUES(%s,%s,%s,1,%s) ON CONFLICT(collection,owner_id,record_id) "
            "DO UPDATE SET sequence=miy_data.projection_heads.sequence+1,deleted=EXCLUDED.deleted RETURNING sequence",
            (collection, identity.user_id, record_id, deleted),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO miy_data.search_outbox(generation,collection,owner_id,record_id,sequence) "
            "SELECT generation,%s,%s,%s,%s FROM miy_data.search_generations WHERE active",
            (collection, identity.user_id, record_id, sequence),
        )

    def stop_search_generation(self, *, installation_id, app_id, environment, generation):
        database, migrator, gateway = self.names(installation_id)
        with self._connect(database=database, role=migrator) as conn:
            self._preflight(conn, database, (migrator, gateway))
            self._identity(conn, installation_id, app_id, environment)
            self._search_identity(conn)
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("miy-search-schema:" + installation_id,),
            )
            conn.execute(
                "UPDATE miy_data.search_generations SET active=false WHERE generation=%s",
                (generation,),
            )

    def remove_temporary(
        self, *, installation_id, app_id, environment, receipt=None, persist_receipt=None
    ):
        """Core-only cleanup after merged delivery, writer stop and workspace ownership checks.

        The caller durably saves the bounded identity receipt before disabling access.
        A retry needs that original receipt; an unmarked/foreign object is never adopted.
        Production and ordinary installed data have no automatic removal path.
        """
        if environment != "development" or not _APP.fullmatch(app_id):
            raise DataStoreError("data_cleanup_denied")
        installation_id = str(UUID(installation_id))
        database, migrator, gateway = self.names(installation_id)
        marker = f"miy-independent-data-v1:{installation_id}:{app_id}:{environment}"
        if not callable(persist_receipt):
            raise DataStoreError("data_cleanup_receipt_required")
        try:
            with self._connect(autocommit=True) as conn:
                conn.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (marker,))
                row = conn.execute(
                    "SELECT oid,pg_get_userbyid(datdba),shobj_description(oid,'pg_database'),datallowconn "
                    "FROM pg_database WHERE datname=%s",
                    (database,),
                ).fetchone()
                roles = {}
                for role in (migrator, gateway):
                    item = conn.execute(
                        "SELECT oid,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,"
                        "shobj_description(oid,'pg_authid'),rolcanlogin FROM pg_roles WHERE rolname=%s",
                        (role,),
                    ).fetchone()
                    if item is None:
                        continue
                    if item[1:6] != (False, False, False, False, False) or item[6:] != (
                        marker,
                        True,
                    ):
                        raise DataStoreError("data_cleanup_identity_mismatch")
                    if conn.execute(
                        "SELECT 1 FROM pg_auth_members WHERE member=%s OR roleid=%s LIMIT 1",
                        (item[0], item[0]),
                    ).fetchone():
                        raise DataStoreError("data_cleanup_identity_mismatch")
                    if conn.execute(
                        "SELECT 1 FROM pg_database WHERE datdba=%s AND datname<>%s LIMIT 1",
                        (item[0], database),
                    ).fetchone():
                        raise DataStoreError("data_cleanup_identity_mismatch")
                    roles[role] = item[0]
                self._preflight(conn, database, tuple(roles))
                if row is None and not roles:
                    # Positive catalog absence is safe for a workspace that never
                    # reached provisioning. Mixed absence still needs the original
                    # identity receipt; foreign/existing objects are never adopted.
                    absent = {
                        "version": 1,
                        "installation_id": installation_id,
                        "app_id": app_id,
                        "environment": environment,
                        "database": database,
                        "database_oid": None,
                        "roles": {},
                        "marker": marker,
                        "checksum": CHECKSUM,
                        "search_checksum": None,
                        "phase": "absent",
                    }
                    if receipt is None or receipt == absent:
                        persist_receipt(dict(absent))
                        return absent
                if receipt is None:
                    if (
                        row is None
                        or row[1:3] != (migrator, marker)
                        or row[3] is not True
                        or len(roles) != 2
                    ):
                        raise DataStoreError("data_cleanup_identity_mismatch")
                    with self._connect(database=database, role=migrator) as owned:
                        self._identity(owned, installation_id, app_id, environment)
                        search_checksum = None
                        if (
                            owned.execute(
                                "SELECT to_regclass('miy_data.search_schema')"
                            ).fetchone()[0]
                            is not None
                        ):
                            self._search_identity(owned)
                            search_checksum = SEARCH_CHECKSUM
                    receipt = {
                        "version": 1,
                        "installation_id": installation_id,
                        "app_id": app_id,
                        "environment": environment,
                        "database": database,
                        "database_oid": row[0],
                        "roles": roles,
                        "marker": marker,
                        "checksum": CHECKSUM,
                        "search_checksum": search_checksum,
                        "phase": "verified",
                    }
                    persist_receipt(dict(receipt))
                expected_keys = {
                    "version",
                    "installation_id",
                    "app_id",
                    "environment",
                    "database",
                    "database_oid",
                    "roles",
                    "marker",
                    "checksum",
                    "search_checksum",
                    "phase",
                }
                if (
                    not isinstance(receipt, dict)
                    or set(receipt) != expected_keys
                    or (
                        receipt["version"],
                        receipt["installation_id"],
                        receipt["app_id"],
                        receipt["environment"],
                        receipt["database"],
                        receipt["marker"],
                        receipt["checksum"],
                    )
                    != (1, installation_id, app_id, environment, database, marker, CHECKSUM)
                ):
                    raise DataStoreError("data_cleanup_receipt_invalid")
                if (
                    type(receipt["database_oid"]) is not int
                    or receipt["database_oid"] <= 0
                    or receipt["phase"]
                    not in {"verified", "disabled", "database_removed", "removed"}
                ):
                    raise DataStoreError("data_cleanup_receipt_invalid")
                if (
                    not isinstance(receipt["roles"], dict)
                    or set(receipt["roles"]) != {migrator, gateway}
                    or any(type(oid) is not int or oid <= 0 for oid in receipt["roles"].values())
                    or any(receipt["roles"].get(role) != oid for role, oid in roles.items())
                    or receipt["search_checksum"] not in {None, SEARCH_CHECKSUM}
                ):
                    raise DataStoreError("data_cleanup_identity_mismatch")
                if row is not None:
                    if (row[0], row[1], row[2]) != (receipt["database_oid"], migrator, marker):
                        raise DataStoreError("data_cleanup_identity_mismatch")
                    if len(roles) != 2 or receipt["phase"] not in {"verified", "disabled"}:
                        raise DataStoreError("data_cleanup_identity_mismatch")
                    if row[3]:
                        # A retry before access was disabled must verify the live
                        # schema again; a saved receipt cannot authorize changed data.
                        with self._connect(database=database, role=migrator) as owned:
                            self._identity(owned, installation_id, app_id, environment)
                            present = (
                                owned.execute(
                                    "SELECT to_regclass('miy_data.search_schema')"
                                ).fetchone()[0]
                                is not None
                            )
                            if present != (receipt["search_checksum"] is not None):
                                raise DataStoreError("data_cleanup_identity_mismatch")
                            if present:
                                self._search_identity(owned)
                    # Do not terminate sessions or use DROP DATABASE FORCE.
                    if conn.execute(
                        "SELECT 1 FROM pg_stat_activity WHERE datname=%s LIMIT 1", (database,)
                    ).fetchone():
                        raise DataStoreError("data_cleanup_active_connections")
                    if row[3]:
                        conn.execute(
                            sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(
                                sql.Identifier(database)
                            )
                        )
                    receipt = {**receipt, "phase": "disabled"}
                    persist_receipt(dict(receipt))
                    if conn.execute(
                        "SELECT 1 FROM pg_stat_activity WHERE datname=%s LIMIT 1", (database,)
                    ).fetchone():
                        raise DataStoreError("data_cleanup_active_connections")
                    conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
                receipt = {**receipt, "phase": "database_removed"}
                persist_receipt(dict(receipt))
                for role in roles:
                    current = conn.execute(
                        "SELECT oid,shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=%s",
                        (role,),
                    ).fetchone()
                    if current != (receipt["roles"][role], marker):
                        raise DataStoreError("data_cleanup_identity_mismatch")
                    conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
                receipt = {**receipt, "phase": "removed"}
                persist_receipt(dict(receipt))
                return receipt
        except psycopg.Error as exc:
            raise DataStoreError("data_cleanup_held") from exc

    @staticmethod
    def _identity(conn, installation_id, app_id, environment):
        row = conn.execute(
            "SELECT installation_id::text,app_id,environment,version,checksum "
            "FROM miy_data.installation WHERE singleton"
        ).fetchone()
        if row != (installation_id, app_id, environment, VERSION, CHECKSUM):
            raise DataStoreError("data_schema_identity_mismatch")

    @contextmanager
    def _transaction(self, identity: AppIdentityOut) -> Iterator[psycopg.Connection]:
        database, _, gateway = self.names(identity.installation_id)
        try:
            with self._connect(database=database, role=gateway) as conn:
                self._preflight(conn, database, (gateway,))
                self._identity(
                    conn, identity.installation_id, identity.app_id, identity.environment
                )
                conn.execute("SELECT set_config('miy.actor_id',%s,true)", (identity.user_id,))
                yield conn
        except psycopg.Error as exc:
            raise DataStoreError("data_unavailable") from exc

    @staticmethod
    def _validate(collection: str, payload: dict | None = None):
        if not _COLLECTION.fullmatch(collection):
            raise DataStoreError("data_collection_invalid")
        if payload is not None:
            try:
                encoded = json.dumps(payload, allow_nan=False, ensure_ascii=False)
            except (TypeError, ValueError, RecursionError) as exc:
                raise DataStoreError("data_payload_invalid") from exc
            if not isinstance(payload, dict) or len(encoded.encode()) > 16384:
                raise DataStoreError("data_payload_invalid")

    def list_records(
        self,
        identity: AppIdentityOut,
        collection: str,
        *,
        after: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        self._validate(collection)
        if not 1 <= limit <= 100:
            raise DataStoreError("data_limit_invalid")
        cursor = UUID(after) if after else UUID(int=0)
        with self._transaction(identity) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id,payload,version,created_at,updated_at FROM miy_data.records "
                "WHERE owner_id=%s AND collection=%s AND id>%s ORDER BY id LIMIT %s",
                (identity.user_id, collection, cursor, limit),
            )
            return cur.fetchall()

    def read(self, identity: AppIdentityOut, collection: str, record_id: str) -> dict:
        self._validate(collection)
        with self._transaction(identity) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id,payload,version,created_at,updated_at FROM miy_data.records "
                "WHERE owner_id=%s AND collection=%s AND id=%s",
                (identity.user_id, collection, UUID(record_id)),
            )
            row = cur.fetchone()
            if row is None:
                raise DataStoreError("data_record_not_found")
            return row

    @staticmethod
    def _key_id(identity: AppIdentityOut, collection: str, record_key: str) -> UUID:
        if (
            not isinstance(record_key, str)
            or not record_key.strip()
            or not record_key.isprintable()
            or len(record_key.encode("utf-8")) > 256
        ):
            raise DataStoreError("data_payload_invalid")
        # This identity comes from current Core authorization, never request JSON.
        name = json.dumps(
            [identity.installation_id, identity.user_id, collection, record_key],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return uuid5(_RECORD_KEY_NAMESPACE, name)

    def read_by_key(self, identity: AppIdentityOut, collection: str, record_key: str) -> dict:
        self._validate(collection)
        return self.read(identity, collection, str(self._key_id(identity, collection, record_key)))

    def write(
        self,
        identity: AppIdentityOut,
        collection: str,
        payload: dict,
        *,
        record_id: str | None = None,
        expected_version: int | None = None,
        record_key: str | None = None,
    ) -> dict:
        self._validate(collection, payload)
        if record_key is not None and record_id is not None:
            raise DataStoreError("data_payload_invalid")
        keyed_id = (
            self._key_id(identity, collection, record_key) if record_key is not None else None
        )
        with self._transaction(identity) as conn, conn.cursor(row_factory=dict_row) as cur:
            if record_id is None:
                if keyed_id is None:
                    cur.execute(
                        "INSERT INTO miy_data.records(id,collection,owner_id,payload) VALUES(%s,%s,%s,%s) "
                        "RETURNING id,payload,version,created_at,updated_at",
                        (uuid4(), collection, identity.user_id, Jsonb(payload)),
                    )
                else:
                    cur.execute(
                        "INSERT INTO miy_data.records(id,collection,owner_id,payload) VALUES(%s,%s,%s,%s) "
                        "ON CONFLICT(id) DO NOTHING "
                        "RETURNING id,payload,version,created_at,updated_at",
                        (keyed_id, collection, identity.user_id, Jsonb(payload)),
                    )
            else:
                if expected_version is None or expected_version < 1:
                    raise DataStoreError("data_version_required")
                cur.execute(
                    "UPDATE miy_data.records SET payload=%s,version=version+1,updated_at=now() "
                    "WHERE owner_id=%s AND collection=%s AND id=%s AND version=%s "
                    "RETURNING id,payload,version,created_at,updated_at",
                    (
                        Jsonb(payload),
                        identity.user_id,
                        collection,
                        UUID(record_id),
                        expected_version,
                    ),
                )
            row = cur.fetchone()
            if row is None:
                raise DataStoreError("data_record_conflict")
            self._record_projection(conn, identity, collection, row["id"], deleted=False)
            return row

    def delete(
        self, identity: AppIdentityOut, collection: str, record_id: str, expected_version: int
    ):
        self._validate(collection)
        with self._transaction(identity) as conn:
            result = conn.execute(
                "DELETE FROM miy_data.records WHERE owner_id=%s AND collection=%s AND id=%s AND version=%s",
                (identity.user_id, collection, UUID(record_id), expected_version),
            )
            if result.rowcount != 1:
                raise DataStoreError("data_record_conflict")
            self._record_projection(conn, identity, collection, UUID(record_id), deleted=True)


def configured_store(settings) -> PostgresAppData:
    dsn = settings.independent_app_data_postgres_dsn.get_secret_value()
    key = settings.independent_app_data_credential_key.get_secret_value()
    if not dsn or not key:
        raise DataStoreError("data_configuration_required")
    return PostgresAppData(dsn, key)
