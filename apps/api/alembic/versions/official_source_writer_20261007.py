"""Complete the fixed official suite source inventory: 19 to 88."""

from alembic import op
import sqlalchemy as sa

revision = "official_source_writer_20261007"
down_revision = "official_dm_writer_20261007"
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
    "planner_events",
    "dm_conversations",
    "dm_conversation_participants",
    "dm_messages",
    "dm_message_attachments",
)
_SOURCES = (
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
_LEGACY = "miy_guard_official_source_writer"
_ROLE = "miy_guard_official_source_writer_by_role"


def _guard(tables, *, require_draining=True):
    connection = op.get_bind()
    if connection.connection.driver_connection.autocommit is True:
        raise RuntimeError("official_source_writer_requires_transaction")
    if connection.get_isolation_level() != "READ COMMITTED":
        raise RuntimeError("official_source_writer_requires_read_committed")
    # The ownership lock excludes a concurrent guard/CAS change for the whole
    # migration transaction. Source-trigger readers finish before this lock.
    ownership = connection.execute(
        sa.text(
            "SELECT active_owner,state FROM public.official_runtime_ownership "
            "WHERE scope='official.suite' FOR UPDATE"
        )
    ).one_or_none()
    if ownership is None or ownership[0] != "legacy":
        raise RuntimeError("official_source_writer_ownership_invalid")
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
        raise RuntimeError("official_source_writer_guard_inventory_invalid")
    guard = guards.pop()
    if guard == _ROLE:
        if require_draining and ownership[1] != "draining":
            raise RuntimeError("official_source_writer_requires_draining")
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
            raise RuntimeError("official_source_writer_role_guard_invalid")
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
        raise RuntimeError("official_source_writer_requires_explicit_retirement")
    for source in reversed(_SOURCES):
        op.execute(f"DROP TRIGGER miy_official_source_writer ON public.{source}")
        op.drop_constraint(f"ck_{source}_writer_scope", source, type_="check")
        op.drop_constraint(f"fk_{source}_writer_scope", source, type_="foreignkey")
        op.drop_column(source, "writer_scope")
