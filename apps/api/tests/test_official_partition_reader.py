"""Actual company-default read/SHARE authority in owned disposable PostgreSQL."""

from types import SimpleNamespace

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.orm import Session
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import ACTIVE, activate, move
from test_official_writer_roles import role_template as role_template
from test_official_writer_roles import world as world

from miy_api.domains.official_apps.projection_partition_roles import (
    READ_COMPANY_PARTITION,
    install_company_partition_reader,
    prepare_company_projection_core,
)
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from miy_api.domains.official_apps.writer_roles import prepare_principal
from miy_api.domains.retrieval.partitioning import (
    ensure_default_partition,
)


def read_default(conn, namespace="docs", binding=None):
    return str(
        conn.execute(
            "SELECT public.miy_read_official_company_partition(%s,%s::uuid)",
            (namespace, binding),
        ).fetchone()[0]
    )


def lock_core(conn, identifier, namespace="docs"):
    return str(
        conn.execute(
            "SELECT public.miy_lock_official_projection_partition(%s::uuid,%s)",
            (identifier, namespace),
        ).fetchone()[0]
    )


def unavailable(
    conn, namespace="docs", binding=None, message="official_projection_partition_unavailable"
):
    with pytest.raises(psycopg.Error) as caught:
        with conn.transaction():
            read_default(conn, namespace, binding)
    assert caught.value.sqlstate == "55000"
    assert caught.value.diag.message_primary == message


@pytest.fixture
def prepared(world):
    old_source, _, _ = activate(world)
    with Session(world.engine) as db:
        defaults = {
            namespace: ensure_default_partition(
                db, source_namespace=namespace, candidate_scope_kind="company"
            ).id
            for namespace in ("docs", "pms", "meeting")
        }
        db.commit()
    drain = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    reader = world.role(login=False)
    with Session(world.engine) as db:
        install_company_partition_reader(db, world.actor, reader_owner=reader, expected=drain)
        db.commit()
    source = world.role()
    identity = WriterIdentity(SUITE_SCOPE, "legacy", drain.generation + 1, "sha256:" + "b" * 64)
    with Session(world.engine) as db:
        principal = prepare_principal(
            db,
            world.actor,
            role_name=source,
            identity=identity,
            expected=drain,
            expected_state="draining",
            company_projection=True,
        )
        source_oid = principal.role_oid
        db.commit()
    assert move(world, drain, "draining", state="active", artifact=identity.artifact) == identity
    core = world.role()
    with Session(world.engine) as db:
        prepare_company_projection_core(
            db, world.actor, role_name=core, expected=identity, expected_state="active"
        )
        db.commit()
    return SimpleNamespace(
        source=source,
        old_source=old_source,
        source_oid=source_oid,
        reader=reader,
        core=core,
        identity=identity,
        defaults=defaults,
    )


def test_stale_open_connection_and_recreated_same_name_cannot_reuse_source_identity(
    world, prepared
):
    with world.connect(prepared.source) as retained:
        assert read_default(retained) == prepared.defaults["docs"]
        retained.commit()
        drain = move(
            world,
            prepared.identity,
            "active",
            state="draining",
            artifact=prepared.identity.artifact,
        )
        retained.execute(
            "SELECT set_config('miy.official_writer',%s,true)",
            ('{"owner":"legacy","generation":999}',),
        )
        unavailable(retained, message="official_writer_fenced")
        retained.rollback()
    with world.connect() as conn:
        conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(prepared.source)))
        conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(prepared.source)))
        from test_official_writer_roles import PASSWORD

        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(prepared.source), sql.Literal(PASSWORD))
        )
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(prepared.source))
        )
        conn.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                sql.SQL(READ_COMPANY_PARTITION), sql.Identifier(prepared.source)
            )
        )
    with world.connect(prepared.source) as recreated:
        unavailable(recreated, message="official_writer_fenced")
    with (
        Session(world.engine) as db,
        pytest.raises(WriterControlError, match="writer_role_identity_immutable"),
    ):
        prepare_principal(
            db,
            world.actor,
            role_name=prepared.source,
            identity=prepared.identity,
            expected=drain,
            expected_state="draining",
            company_projection=True,
        )


@pytest.mark.parametrize("isolation", ["REPEATABLE READ"])
def test_capability_rejects_stale_snapshot_isolation(world, prepared, isolation):
    with world.connect(prepared.source) as conn:
        conn.execute(sql.SQL("SET TRANSACTION ISOLATION LEVEL {}").format(sql.SQL(isolation)))
        unavailable(conn)
