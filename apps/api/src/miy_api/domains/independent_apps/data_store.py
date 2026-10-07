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
from uuid import UUID, uuid4

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
_COLLECTION = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_APP = re.compile(r"[a-z][a-z0-9-]{1,63}")
_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")


class DataStoreError(Exception):
    """Safe public code, never a driver message/connection string."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


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

    def _connect(self, *, database=None, role=None, autocommit=False):
        args = {"connect_timeout": 5, "options": "-c statement_timeout=5000 -c lock_timeout=3000"}
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
            with self._connect(autocommit=True) as conn:
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

    def write(
        self,
        identity: AppIdentityOut,
        collection: str,
        payload: dict,
        *,
        record_id: str | None = None,
        expected_version: int | None = None,
    ) -> dict:
        self._validate(collection, payload)
        with self._transaction(identity) as conn, conn.cursor(row_factory=dict_row) as cur:
            if record_id is None:
                cur.execute(
                    "INSERT INTO miy_data.records(id,collection,owner_id,payload) VALUES(%s,%s,%s,%s) "
                    "RETURNING id,payload,version,created_at,updated_at",
                    (uuid4(), collection, identity.user_id, Jsonb(payload)),
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


def configured_store(settings) -> PostgresAppData:
    dsn = settings.independent_app_data_postgres_dsn.get_secret_value()
    key = settings.independent_app_data_credential_key.get_secret_value()
    if not dsn or not key:
        raise DataStoreError("data_configuration_required")
    return PostgresAppData(dsn, key)
