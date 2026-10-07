"""Add inactive suite writer control and PostgreSQL fences for covered source tables."""

from alembic import op
import sqlalchemy as sa

revision = "official_writer_fence_20261006"
down_revision = "official_auth_binding_20261006"
branch_labels = None
depends_on = None

# Frozen schema snapshot; current inventory is writer_contracts.COVERED_SOURCE_TABLES.
# A coverage test compares model metadata, this migration and installed triggers.
_SOURCES = (
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
)


def upgrade() -> None:
    op.create_table(
        "official_runtime_ownership",
        sa.Column("scope", sa.String(80), primary_key=True),
        sa.Column("active_owner", sa.String(32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("artifact", sa.String(71), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("generation >= 1", name="ck_official_writer_generation"),
        sa.CheckConstraint(
            "active_owner IN ('legacy', 'official-suite')", name="ck_official_writer_owner"
        ),
        sa.CheckConstraint("state IN ('active', 'draining')", name="ck_official_writer_state"),
    )
    op.execute(
        "INSERT INTO official_runtime_ownership VALUES ('official.suite', 'legacy', 1, NULL, 'active', CURRENT_TIMESTAMP)"
    )
    op.create_table(
        "official_runtime_transitions",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column(
            "scope",
            sa.String(80),
            sa.ForeignKey("official_runtime_ownership.scope"),
            nullable=False,
        ),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "source_session_id", sa.String(36), sa.ForeignKey("auth_sessions.id"), nullable=False
        ),
        sa.Column("previous", sa.JSON(), nullable=False),
        sa.Column("resulting", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_official_runtime_transitions_scope", "official_runtime_transitions", ["scope"]
    )
    # The fixed FK also makes data restore order explicit: control precedes source.
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
    op.execute("""
        CREATE FUNCTION public.miy_guard_official_source_writer() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
        DECLARE
            ownership public.official_runtime_ownership%ROWTYPE;
            asserted jsonb;
        BEGIN
            IF TG_NARGS <> 1 OR TG_ARGV[0] <> 'official.suite' THEN
                RAISE EXCEPTION 'official_writer_scope_invalid' USING ERRCODE = '55000';
            END IF;
            SELECT * INTO ownership FROM public.official_runtime_ownership
                WHERE scope = TG_ARGV[0] FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'official_writer_control_missing' USING ERRCODE = '55000';
            END IF;
            asserted := COALESCE(NULLIF(current_setting('miy.official_writer', true), '')::jsonb,
                jsonb_build_object('scope', TG_ARGV[0], 'owner', 'legacy',
                    'generation', 1, 'artifact', NULL));
            IF ownership.state <> 'active' OR asserted IS DISTINCT FROM jsonb_build_object(
                'scope', ownership.scope, 'owner', ownership.active_owner,
                'generation', ownership.generation, 'artifact', ownership.artifact)
            THEN
                RAISE EXCEPTION 'official_writer_fenced' USING ERRCODE = '55000';
            END IF;
            RETURN NULL;
        END;
        $$
    """)
    for source in _SOURCES:
        # Identifiers are exclusively the frozen core-owned schema list above.
        op.execute(f"""
            CREATE TRIGGER miy_official_source_writer
            BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{source}
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.miy_guard_official_source_writer('official.suite')
        """)


def downgrade() -> None:
    for source in reversed(_SOURCES):
        op.execute(f"DROP TRIGGER miy_official_source_writer ON public.{source}")
        op.drop_constraint(f"ck_{source}_writer_scope", source, type_="check")
        op.drop_constraint(f"fk_{source}_writer_scope", source, type_="foreignkey")
        op.drop_column(source, "writer_scope")
    op.execute("DROP FUNCTION public.miy_guard_official_source_writer()")
    op.drop_table("official_runtime_transitions")
    op.drop_table("official_runtime_ownership")
