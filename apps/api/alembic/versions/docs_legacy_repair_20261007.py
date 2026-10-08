"""Fixed Core Docs legacy repair receipts, without source writes or role grants."""

from alembic import op
import sqlalchemy as sa

revision = "docs_legacy_repair_20261007"
down_revision = "official_projection_20261007"
branch_labels = None
depends_on = None

_RECEIPTS = "docs_legacy_projection_repairs"
_TARGETS = "docs_legacy_projection_repair_targets"


def _transaction():
    connection = op.get_bind()
    if (
        connection.connection.driver_connection.autocommit is True
        or connection.get_isolation_level() != "READ COMMITTED"
    ):
        raise RuntimeError("docs_repair_requires_read_committed")
    return connection


def upgrade() -> None:
    _transaction()
    op.create_table(
        _RECEIPTS,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "visibility_job_id",
            sa.String(36),
            sa.ForeignKey("rag_visibility_recompute_jobs.id", ondelete="RESTRICT"),
            unique=True,
            nullable=True,
        ),
        sa.Column(
            "rag_job_id",
            sa.String(36),
            sa.ForeignKey("rag_sync_jobs.id", ondelete="RESTRICT"),
            unique=True,
            nullable=True,
        ),
        sa.Column(
            "search_job_id",
            sa.String(36),
            sa.ForeignKey("search_index_jobs.id", ondelete="RESTRICT"),
            unique=True,
            nullable=True,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("input_payload", sa.Text(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("targets_payload", sa.Text(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("rag_enabled", sa.Boolean(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("schema_version = 1", name="ck_docs_repair_version"),
        sa.CheckConstraint("target_count BETWEEN 0 AND 100", name="ck_docs_repair_count"),
        sa.CheckConstraint(
            "(CASE WHEN visibility_job_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN rag_job_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN search_job_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_docs_repair_origin",
        ),
        sa.CheckConstraint(
            "octet_length(input_payload) <= 131072", name="ck_docs_repair_input_size"
        ),
        sa.CheckConstraint(
            "octet_length(targets_payload) <= 131072", name="ck_docs_repair_targets_size"
        ),
        sa.CheckConstraint("input_digest ~ '^[a-f0-9]{64}$'", name="ck_docs_repair_digest"),
    )
    op.create_table(
        _TARGETS,
        sa.Column(
            "receipt_id",
            sa.String(36),
            sa.ForeignKey(f"{_RECEIPTS}.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("resource_id", sa.String(255), primary_key=True),
        sa.Column(
            "core_event_sequence",
            sa.BigInteger(),
            sa.ForeignKey("retrieval_projection_events.event_sequence", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("operation", sa.String(24), nullable=False),
        sa.Column(
            "search_job_id",
            sa.String(36),
            sa.ForeignKey("search_index_jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "rag_job_id",
            sa.String(36),
            sa.ForeignKey("rag_sync_jobs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "operation IN ('upsert','visibility_update','delete')", name="ck_docs_repair_target_op"
        ),
    )
    # Reuse only the existing Core immutability function, not a source writer
    # guard. No source or runtime role receives any new privilege here.
    for table in (_RECEIPTS, _TARGETS):
        op.execute(
            f"CREATE TRIGGER miy_docs_repair_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION public.miy_keep_official_projection_immutable()"
        )
    op.execute("""
      CREATE FUNCTION public.miy_check_docs_repair_targets() RETURNS trigger
      LANGUAGE plpgsql SET search_path = pg_catalog AS $$
      DECLARE receipt public.docs_legacy_projection_repairs%ROWTYPE;
              reference_id text; actual_targets jsonb; actual_count bigint;
      BEGIN
        IF TG_TABLE_NAME = 'docs_legacy_projection_repairs' THEN
          reference_id := NEW.id;
        ELSE
          reference_id := NEW.receipt_id;
        END IF;
        SELECT * INTO STRICT receipt FROM public.docs_legacy_projection_repairs WHERE id=reference_id;
        SELECT count(*), COALESCE(jsonb_agg(resource_id ORDER BY resource_id), '[]'::jsonb)
          INTO actual_count, actual_targets FROM public.docs_legacy_projection_repair_targets
          WHERE receipt_id=reference_id;
        IF actual_count <> receipt.target_count OR actual_targets <> receipt.targets_payload::jsonb
           OR encode(sha256(convert_to(receipt.input_payload,'UTF8')),'hex') <> receipt.input_digest
           OR EXISTS (
             SELECT 1 FROM public.docs_legacy_projection_repair_targets t
             JOIN public.retrieval_projection_events e ON e.event_sequence=t.core_event_sequence
             WHERE t.receipt_id=reference_id AND (
               e.resource_type <> 'docs_native_doc' OR e.resource_id <> t.resource_id
               OR e.change_kind <> 'repair' OR (e.desired_state='deleted') <> (t.operation='delete')
               OR receipt.rag_enabled <> (t.rag_job_id IS NOT NULL)

             )
           ) THEN
          RAISE EXCEPTION 'docs_repair_target_contract' USING ERRCODE='23514';
        END IF;
        RETURN NULL;
      END; $$;
      REVOKE ALL ON FUNCTION public.miy_check_docs_repair_targets() FROM PUBLIC;
    """)
    for table in (_RECEIPTS, _TARGETS):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER miy_docs_repair_target_contract AFTER INSERT ON public.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.miy_check_docs_repair_targets()"
        )


def downgrade() -> None:
    connection = _transaction()
    connection.exec_driver_sql(
        f"LOCK TABLE public.{_RECEIPTS}, public.{_TARGETS} IN ACCESS EXCLUSIVE MODE"
    )
    if connection.execute(
        sa.text(
            f"SELECT EXISTS(SELECT 1 FROM public.{_RECEIPTS}) OR EXISTS(SELECT 1 FROM public.{_TARGETS})"
        )
    ).scalar():
        raise RuntimeError("docs_repair_retention_required")
    op.drop_table(_TARGETS)
    op.drop_table(_RECEIPTS)
    op.execute("DROP FUNCTION public.miy_check_docs_repair_targets()")
