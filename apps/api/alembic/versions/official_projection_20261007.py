"""Fixed official projection transport, without a runtime activation or role grant."""

from alembic import op
import sqlalchemy as sa

revision = "official_projection_20261007"
down_revision = "official_source_writer_20261007"
branch_labels = None
depends_on = None

_LEGACY = "miy_guard_official_source_writer"
_ROLE = "miy_guard_official_source_writer_by_role"
_OUTBOX = "official_projection_outbox"
_RECEIPTS = "official_projection_receipts"
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
    "planner_events",
    "dm_conversations",
    "dm_conversation_participants",
    "dm_messages",
    "dm_message_attachments",
    "bento_documents",
    "bento_ai_jobs",
    "bento_ai_job_inputs",
    "community_channels",
    "community_posts",
    "community_post_reads",
    "community_comments",
    "diagrams",
    "file_manager_corpora",
    "file_manager_folders",
    "file_manager_files",
    "file_manager_file_source_metadata",
    "file_manager_file_access_grants",
    "file_manager_storage_cleanup_jobs",
    "file_manager_bulk_ingest_runs",
    "file_manager_bulk_ingest_entries",
    "mail_accounts",
    "mail_mailboxes",
    "mail_messages",
    "mail_message_bodies",
    "mail_attachments",
    "mail_drafts",
    "mail_send_attempts",
    "mail_sync_states",
    "mail_sync_jobs",
    "meetings",
    "meeting_attendees",
    "meeting_task_links",
    "meeting_doc_links",
    "meeting_file_attachments",
    "meeting_recordings",
    "meeting_insights",
    "meeting_recording_staging",
    "pms_folders",
    "pms_view_preferences",
    "pms_space_statuses",
    "pms_task_lists",
    "pms_task_list_statuses",
    "pms_milestones",
    "pms_labels",
    "pms_tasks",
    "pms_task_labels",
    "pms_task_comments",
    "pms_task_activity_logs",
    "pms_attachments",
    "pms_checklist_items",
    "pms_notifications",
    "pms_task_templates",
    "pms_custom_fields",
    "pms_custom_field_values",
    "pms_task_assignees",
    "pms_task_followers",
    "pms_task_user_access",
    "pms_spaces",
    "pms_space_members",
    "pms_space_group_bindings",
    "recordings",
    "recording_results",
    "recording_publications",
    "recording_staging",
    "recording_targets",
    "video_chat_sessions",
    "whiteboards",
    "whiteboard_targets",
    "whiteboard_user_shares",
    "whiteboard_link_shares",
    "whiteboard_collab_documents",
    "whiteboard_user_item_prefs",
    "whiteboard_group_shares",
)


def _guard(tables, *, require_draining=True):
    connection = op.get_bind()
    if connection.connection.driver_connection.autocommit is True:
        raise RuntimeError("official_projection_requires_transaction")
    if connection.get_isolation_level() != "READ COMMITTED":
        raise RuntimeError("official_projection_requires_read_committed")
    # The ownership lock excludes a concurrent guard/CAS change for the whole
    # migration transaction. Source-trigger readers finish before this lock.
    ownership = connection.execute(
        sa.text(
            "SELECT active_owner,state FROM public.official_runtime_ownership "
            "WHERE scope='official.suite' FOR UPDATE"
        )
    ).one_or_none()
    if ownership is None or ownership[0] != "legacy":
        raise RuntimeError("official_projection_ownership_invalid")
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
        raise RuntimeError("official_projection_guard_inventory_invalid")
    guard = guards.pop()
    if guard == _ROLE:
        if require_draining and ownership[1] != "draining":
            raise RuntimeError("official_projection_requires_draining")
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
            raise RuntimeError("official_projection_role_guard_invalid")
    return guard


def upgrade() -> None:
    guard = _guard(_EXISTING_SOURCES)
    op.create_table(
        _OUTBOX,
        sa.Column("event_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("producer_generation", sa.Integer(), nullable=False),
        sa.Column("producer_artifact", sa.String(71), nullable=True),
        sa.Column("producer_role_oid", sa.BigInteger(), nullable=False),
        sa.Column("producer_role_name", sa.String(63), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("writer_scope", sa.String(80), server_default="official.suite", nullable=False),
        sa.ForeignKeyConstraint(
            ["writer_scope"],
            ["official_runtime_ownership.scope"],
            name="fk_official_projection_outbox_writer_scope",
        ),
        sa.CheckConstraint(
            "writer_scope = 'official.suite'", name="ck_official_projection_outbox_writer_scope"
        ),
        sa.UniqueConstraint(
            "resource_type",
            "resource_id",
            "source_revision",
            name="uq_official_projection_stream_revision",
        ),
        sa.CheckConstraint("source_revision >= 1", name="ck_official_projection_source_revision"),
        sa.CheckConstraint(
            "resource_type IN ('docs_native_doc','pms_task','meeting','file_manager_file')",
            name="ck_official_projection_source_type",
        ),
        sa.CheckConstraint(
            "octet_length(payload) <= 8192", name="ck_official_projection_payload_size"
        ),
        sa.CheckConstraint(
            "payload_digest ~ '^[a-f0-9]{64}$'", name="ck_official_projection_payload_digest"
        ),
        sa.CheckConstraint(
            "producer_generation >= 1 AND producer_role_oid > 0",
            name="ck_official_projection_producer",
        ),
    )
    op.create_index("ix_official_projection_pending_order", _OUTBOX, ["created_at", "event_id"])
    op.create_table(
        _RECEIPTS,
        sa.Column(
            "event_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("official_projection_outbox.event_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "core_event_sequence",
            sa.BigInteger(),
            sa.ForeignKey("retrieval_projection_events.event_sequence", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "resource_type",
            "resource_id",
            "source_revision",
            name="uq_official_projection_receipt_revision",
        ),
        sa.CheckConstraint("source_revision >= 1", name="ck_official_projection_receipt_revision"),
        sa.CheckConstraint(
            "status IN ('accepted','superseded')", name="ck_official_projection_receipt_status"
        ),
        sa.CheckConstraint(
            "(status = 'accepted') = (core_event_sequence IS NOT NULL)",
            name="ck_official_projection_receipt_event",
        ),
    )
    op.execute(
        f"CREATE TRIGGER miy_official_source_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{_OUTBOX} FOR EACH STATEMENT EXECUTE FUNCTION public.{guard}('official.suite')"
    )
    op.execute("""
      CREATE FUNCTION public.miy_stamp_official_projection_event() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$
      DECLARE previous_revision bigint; ownership record;
      BEGIN
        IF current_setting('transaction_isolation') <> 'read committed' THEN
          RAISE EXCEPTION 'official_projection_requires_read_committed' USING ERRCODE='55000';
        END IF;
        PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('official.projection.event:' || NEW.event_id::text, 0));
        PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
          'official.projection:' || NEW.resource_type || ':' || NEW.resource_id, 0));
        SELECT source_revision INTO previous_revision FROM public.official_projection_outbox
          WHERE resource_type=NEW.resource_type AND resource_id=NEW.resource_id
          ORDER BY source_revision DESC LIMIT 1;
        IF NEW.source_revision <> COALESCE(previous_revision, 0)+1 THEN
          RAISE EXCEPTION 'official_projection_revision_conflict' USING ERRCODE='23514';
        END IF;
        IF NEW.payload_digest <> pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(NEW.payload,'UTF8')), 'hex')
          OR NEW.payload::jsonb->>'resource_type' IS DISTINCT FROM NEW.resource_type
          OR NEW.payload::jsonb->>'resource_id' IS DISTINCT FROM NEW.resource_id THEN
          RAISE EXCEPTION 'official_projection_payload_invalid' USING ERRCODE='23514';
        END IF;
        SELECT generation,artifact INTO STRICT ownership FROM public.official_runtime_ownership
          WHERE scope='official.suite' AND state='active' AND active_owner='legacy' FOR SHARE;
        NEW.producer_generation := ownership.generation;
        NEW.producer_artifact := ownership.artifact;
        NEW.producer_role_name := session_user;
        SELECT oid::bigint INTO STRICT NEW.producer_role_oid FROM pg_catalog.pg_roles WHERE rolname=session_user;
        NEW.created_at := pg_catalog.timezone('UTC', pg_catalog.clock_timestamp());
        RETURN NEW;
      END $body$;
      REVOKE ALL ON FUNCTION public.miy_stamp_official_projection_event() FROM PUBLIC;
      CREATE TRIGGER miy_official_projection_stamp BEFORE INSERT ON public.official_projection_outbox
        FOR EACH ROW EXECUTE FUNCTION public.miy_stamp_official_projection_event();
      CREATE FUNCTION public.miy_keep_official_projection_immutable() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $body$
      BEGIN
        RAISE EXCEPTION 'official_projection_immutable' USING ERRCODE='55000';
      END $body$;
      REVOKE ALL ON FUNCTION public.miy_keep_official_projection_immutable() FROM PUBLIC;
    """)
    for table in (_OUTBOX, _RECEIPTS):
        op.execute(
            f"CREATE TRIGGER miy_official_projection_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION public.miy_keep_official_projection_immutable()"
        )


def downgrade() -> None:
    guard = _guard((*_EXISTING_SOURCES, _OUTBOX), require_draining=False)
    if guard == _ROLE:
        raise RuntimeError("official_projection_requires_explicit_retirement")
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM public.official_projection_outbox) OR EXISTS(SELECT 1 FROM public.official_projection_receipts)"
        )
    ):
        raise RuntimeError("official_projection_requires_record_retention")
    op.drop_table(_RECEIPTS)
    op.drop_table(_OUTBOX)
    op.execute("DROP FUNCTION public.miy_stamp_official_projection_event()")
    op.execute("DROP FUNCTION public.miy_keep_official_projection_immutable()")
