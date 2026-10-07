"""Prepare restricted writer principals without switching the legacy guard."""

from alembic import op
import sqlalchemy as sa

revision = "official_writer_roles_20261006"
down_revision = "official_writer_fence_20261006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "official_writer_principals",
        sa.Column("role_oid", sa.BigInteger(), primary_key=True),
        sa.Column("role_name", sa.String(63), unique=True, nullable=False),
        sa.Column(
            "scope",
            sa.String(80),
            sa.ForeignKey("official_runtime_ownership.scope"),
            nullable=False,
        ),
        sa.Column("owner", sa.String(32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("artifact", sa.String(71), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "approved_by_session_id",
            sa.String(36),
            sa.ForeignKey("auth_sessions.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("role_oid > 0", name="ck_official_principal_oid"),
        sa.CheckConstraint("scope = 'official.suite'", name="ck_official_principal_scope"),
        sa.CheckConstraint("owner = 'legacy'", name="ck_official_principal_owner"),
        sa.CheckConstraint("generation >= 1", name="ck_official_principal_generation"),
        sa.CheckConstraint(
            "artifact ~ '^sha256:[a-f0-9]{64}$'", name="ck_official_principal_artifact"
        ),
    )
    op.execute("""
        CREATE FUNCTION public.miy_immutable_official_writer_principal() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,pg_temp AS $$
        BEGIN
            IF TG_OP='DELETE' OR
               (to_jsonb(NEW)-'revoked_at') IS DISTINCT FROM (to_jsonb(OLD)-'revoked_at') OR
               (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
            THEN RAISE EXCEPTION 'official_writer_identity_immutable' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION public.miy_immutable_official_writer_principal() FROM PUBLIC"
    )
    op.execute(
        "CREATE TRIGGER miy_official_principal_immutable BEFORE UPDATE OR DELETE ON public.official_writer_principals FOR EACH ROW EXECUTE FUNCTION public.miy_immutable_official_writer_principal()"
    )
    op.execute("""
        CREATE FUNCTION public.miy_guard_official_source_writer_by_role() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        DECLARE
            ownership public.official_runtime_ownership%ROWTYPE;
            principal public.official_writer_principals%ROWTYPE;
        BEGIN
            IF TG_NARGS <> 1 OR TG_ARGV[0] <> 'official.suite' OR TG_TABLE_SCHEMA <> 'public'
            THEN RAISE EXCEPTION 'official_writer_fenced' USING ERRCODE='55000'; END IF;
            SELECT * INTO ownership FROM public.official_runtime_ownership
                WHERE scope=TG_ARGV[0] FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'official_writer_control_missing' USING ERRCODE='55000';
            END IF;
            SELECT p.* INTO principal FROM public.official_writer_principals p
                JOIN pg_catalog.pg_roles r ON r.oid::bigint=p.role_oid AND r.rolname=p.role_name
                WHERE r.rolname=SESSION_USER AND p.scope=TG_ARGV[0] FOR SHARE OF p;
            IF NOT FOUND OR principal.revoked_at IS NOT NULL OR ownership.state <> 'active'
               OR ownership.active_owner <> 'legacy' OR principal.owner <> 'legacy'
               OR (principal.scope,principal.owner,principal.generation,principal.artifact)
                  IS DISTINCT FROM (ownership.scope,ownership.active_owner,ownership.generation,ownership.artifact)
            THEN RAISE EXCEPTION 'official_writer_fenced' USING ERRCODE='55000'; END IF;
            RETURN NULL;
        END;
        $$
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION public.miy_guard_official_source_writer_by_role() FROM PUBLIC"
    )


def downgrade() -> None:
    # Switching a live hardened guard back to a forgeable GUC is not a schema rollback.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM pg_catalog.pg_trigger WHERE tgfoid='public.miy_guard_official_source_writer_by_role()'::regprocedure)
            THEN RAISE EXCEPTION 'official_writer_role_guard_requires_explicit_retirement'; END IF;
        END $$
    """)
    op.execute("DROP FUNCTION public.miy_guard_official_source_writer_by_role()")
    op.execute("DROP TRIGGER miy_official_principal_immutable ON public.official_writer_principals")
    op.execute("DROP FUNCTION public.miy_immutable_official_writer_principal()")
    op.drop_table("official_writer_principals")
