"""Extend the existing suite writer boundary to personal Planner events."""

from alembic import op
import sqlalchemy as sa

revision = "official_planner_writer_20261006"
down_revision = "official_widget_writer_20261006"
branch_labels = None
depends_on = None

# Frozen migration snapshots, not runtime imports. Existing principals retain
# their existing grants; a later explicit preparation uses the expanded inventory.
_EXISTING_SOURCES = (
    "announcements",
    "docs_collections",
    "docs_native_docs",
    "docs_doc_targets",
    "docs_native_doc_pages",
    "docs_native_doc_user_shares",
    "docs_native_doc_link_shares",
    "docs_meeting_access",
    "docs_user_item_prefs",
    "docs_collab_documents",
    "docs_group_shares",
    "pms_task_doc_links",
    "personal_todo_items",
    "personal_memos",
)
_SOURCES = ("planner_events",)
_LEGACY = "miy_guard_official_source_writer"
_ROLE = "miy_guard_official_source_writer_by_role"


def _guard(tables, *, require_draining=True):
    connection = op.get_bind()
    if connection.connection.driver_connection.autocommit is True:
        raise RuntimeError("official_planner_writer_requires_transaction")
    if connection.get_isolation_level() != "READ COMMITTED":
        raise RuntimeError("official_planner_writer_requires_read_committed")
    # The ownership lock excludes a concurrent guard/CAS change for the whole
    # migration transaction. Source-trigger readers finish before this lock.
    ownership = connection.execute(
        sa.text(
            "SELECT active_owner,state FROM public.official_runtime_ownership "
            "WHERE scope='official.suite' FOR UPDATE"
        )
    ).one_or_none()
    if ownership is None or ownership[0] != "legacy":
        raise RuntimeError("official_planner_writer_ownership_invalid")
    rows = connection.execute(
        sa.text("""
        SELECT c.relname,p.proname,pn.nspname,t.tgenabled,t.tgtype,t.tgnargs,
               t.tgargs=decode('6f6666696369616c2e737569746500','hex')
        FROM pg_catalog.pg_trigger t
        JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
        JOIN pg_catalog.pg_namespace pn ON pn.oid=p.pronamespace
        WHERE n.nspname='public' AND t.tgname='miy_official_source_writer'
    """)
    ).all()
    guards = {row[1] for row in rows}
    if (
        {row[0] for row in rows} != set(tables)
        or len(guards) != 1
        or not guards <= {_LEGACY, _ROLE}
        or any(tuple(row[2:]) != ("public", "O", 62, 1, True) for row in rows)
    ):
        raise RuntimeError("official_planner_writer_guard_inventory_invalid")
    guard = guards.pop()
    if guard == _ROLE:
        if require_draining and ownership[1] != "draining":
            raise RuntimeError("official_planner_writer_requires_draining")
        contract = connection.execute(
            sa.text("""
            SELECT p.prosecdef,p.proconfig,
                   EXISTS(SELECT 1 FROM pg_catalog.aclexplode(
                       COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
                       WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
            FROM pg_catalog.pg_proc p
            WHERE p.oid='public.miy_guard_official_source_writer_by_role()'::regprocedure
        """)
        ).one()
        if tuple(contract) != (True, ["search_path=pg_catalog, pg_temp"], False):
            raise RuntimeError("official_planner_writer_role_guard_invalid")
    return guard


def upgrade() -> None:
    guard = _guard(_EXISTING_SOURCES)
    for source in _SOURCES:
        op.add_column(
            source,
            sa.Column(
                "writer_scope", sa.String(80), server_default="official.suite", nullable=False
            ),
        )
        op.create_foreign_key(
            f"fk_{source}_writer_scope",
            source,
            "official_runtime_ownership",
            ["writer_scope"],
            ["scope"],
        )
        op.create_check_constraint(
            f"ck_{source}_writer_scope", source, "writer_scope = 'official.suite'"
        )
        op.execute(f"""
            CREATE TRIGGER miy_official_source_writer
            BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{source}
            FOR EACH STATEMENT EXECUTE FUNCTION public.{guard}('official.suite')
        """)


def downgrade() -> None:
    guard = _guard((*_EXISTING_SOURCES, *_SOURCES), require_draining=False)
    if guard == _ROLE:
        raise RuntimeError("official_planner_writer_requires_explicit_retirement")
    for source in reversed(_SOURCES):
        op.execute(f"DROP TRIGGER miy_official_source_writer ON public.{source}")
        op.drop_constraint(f"ck_{source}_writer_scope", source, type_="check")
        op.drop_constraint(f"fk_{source}_writer_scope", source, type_="foreignkey")
        op.drop_column(source, "writer_scope")
