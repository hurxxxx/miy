"""Private locked company-default capability; no runtime grant or activation."""

from alembic import op
import sqlalchemy as sa

revision = "official_partition_20261007"
down_revision = "recording_managed_20261007"
branch_labels = None
depends_on = None

_SIGNATURE = "public.miy_read_official_company_partition(text,uuid)"

# Frozen migration inventory: earlier migrations and runtime lists are not imported.
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
    "official_projection_outbox",
    "recording_stage_commands",
)


def _guard():
    connection = op.get_bind()
    if connection.connection.driver_connection.autocommit is True:
        raise RuntimeError("official_partition_reader_requires_transaction")
    if connection.get_isolation_level() != "READ COMMITTED":
        raise RuntimeError("official_partition_reader_requires_read_committed")
    ownership = connection.execute(
        sa.text(
            "SELECT active_owner,state FROM public.official_runtime_ownership "
            "WHERE scope='official.suite' FOR UPDATE"
        )
    ).one_or_none()
    if ownership is None or ownership[0] != "legacy":
        raise RuntimeError("official_partition_reader_ownership_invalid")
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
        {row[0] for row in rows} != set(_SOURCES)
        or len(guards) != 1
        or not guards
        <= {"miy_guard_official_source_writer", "miy_guard_official_source_writer_by_role"}
        or any(tuple(row[2:]) != ("public", "O", 62, 1, True) for row in rows)
    ):
        raise RuntimeError("official_partition_reader_guard_inventory_invalid")
    guard = guards.pop()
    if guard == "miy_guard_official_source_writer_by_role":
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
            raise RuntimeError("official_partition_reader_role_guard_invalid")
    return guard, ownership[1]


def upgrade() -> None:
    guard, state = _guard()
    if guard == "miy_guard_official_source_writer_by_role" and state != "draining":
        raise RuntimeError("official_partition_reader_requires_draining")
    op.execute(r"""
CREATE FUNCTION public.miy_read_official_company_partition(source_namespace text,bound_partition_id uuid DEFAULT NULL) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$
DECLARE actor record; principal record; descriptor uuid; inventory record; function_owner record;
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'official_projection_partition_unavailable' USING ERRCODE='55000';
  END IF;
  IF source_namespace IS NULL OR source_namespace NOT IN ('docs','pms','meeting') THEN
    RAISE EXCEPTION 'official_projection_partition_unavailable' USING ERRCODE='55000';
  END IF;
  SELECT r.* INTO STRICT actor FROM pg_catalog.pg_roles r WHERE r.rolname=session_user;
  IF NOT actor.rolcanlogin OR actor.rolsuper OR actor.rolinherit OR actor.rolcreatedb
     OR actor.rolcreaterole OR actor.rolreplication OR actor.rolbypassrls
     OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=actor.oid OR roleid=actor.oid)
  THEN RAISE EXCEPTION 'official_writer_fenced' USING ERRCODE='55000'; END IF;
  SELECT p.* INTO principal FROM public.official_writer_principals p
    WHERE p.role_oid=actor.oid::bigint AND p.role_name=session_user;
  IF NOT FOUND THEN RAISE EXCEPTION 'official_writer_fenced' USING ERRCODE='55000'; END IF;
  -- Reuse the existing authoritative ownership/principal SHARE admission.
  -- The wrapper derives every argument from actual session_user, never input.
  BEGIN
    PERFORM public.miy_recording_lock_producer(principal.role_oid,principal.role_name,
      principal.generation,principal.artifact);
  EXCEPTION WHEN no_data_found THEN
    RAISE EXCEPTION 'official_writer_fenced' USING ERRCODE='55000';
  WHEN SQLSTATE '55000' THEN
    IF SQLERRM IN ('recording_managed_source_authority_invalid','recording_managed_requires_read_committed') THEN
      RAISE EXCEPTION 'official_writer_fenced' USING ERRCODE='55000';
    ELSE RAISE; END IF;
  END;
  -- The ownership/principal SHARE locks now exclude a concurrent drain/retirement.
  SELECT count(*) AS count, array_agg(c.relname::text ORDER BY c.relname) AS tables,
    bool_and(p.oid='public.miy_guard_official_source_writer_by_role()'::regprocedure
      AND pn.nspname='public' AND t.tgenabled='O' AND t.tgtype=62 AND t.tgnargs=1
      AND t.tgargs=decode('6f6666696369616c2e737569746500','hex')) AS valid
    INTO inventory
    FROM pg_catalog.pg_trigger t
    JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
    JOIN pg_catalog.pg_namespace pn ON pn.oid=p.pronamespace
    WHERE n.nspname='public' AND t.tgname='miy_official_source_writer';
  IF inventory.count<>90 OR inventory.valid IS DISTINCT FROM true
     OR inventory.tables IS DISTINCT FROM ARRAY['announcements','bento_ai_job_inputs','bento_ai_jobs','bento_documents','community_channels','community_comments','community_post_reads','community_posts','diagrams','dm_conversation_participants','dm_conversations','dm_message_attachments','dm_messages','docs_collab_documents','docs_collections','docs_doc_targets','docs_group_shares','docs_meeting_access','docs_native_doc_link_shares','docs_native_doc_pages','docs_native_doc_user_shares','docs_native_docs','docs_user_item_prefs','file_manager_bulk_ingest_entries','file_manager_bulk_ingest_runs','file_manager_corpora','file_manager_file_access_grants','file_manager_file_source_metadata','file_manager_files','file_manager_folders','file_manager_storage_cleanup_jobs','mail_accounts','mail_attachments','mail_drafts','mail_mailboxes','mail_message_bodies','mail_messages','mail_send_attempts','mail_sync_jobs','mail_sync_states','meeting_attendees','meeting_doc_links','meeting_file_attachments','meeting_insights','meeting_recording_staging','meeting_recordings','meeting_task_links','meetings','official_projection_outbox','personal_memos','personal_todo_items','planner_events','pms_attachments','pms_checklist_items','pms_custom_field_values','pms_custom_fields','pms_folders','pms_labels','pms_milestones','pms_notifications','pms_space_group_bindings','pms_space_members','pms_space_statuses','pms_spaces','pms_task_activity_logs','pms_task_assignees','pms_task_comments','pms_task_doc_links','pms_task_followers','pms_task_labels','pms_task_list_statuses','pms_task_lists','pms_task_templates','pms_task_user_access','pms_tasks','pms_view_preferences','recording_publications','recording_results','recording_stage_commands','recording_staging','recording_targets','recordings','video_chat_sessions','whiteboard_collab_documents','whiteboard_group_shares','whiteboard_link_shares','whiteboard_targets','whiteboard_user_item_prefs','whiteboard_user_shares','whiteboards']::text[] THEN
    RAISE EXCEPTION 'official_writer_fenced' USING ERRCODE='55000';
  END IF;
  IF EXISTS(SELECT 1 FROM pg_catalog.pg_proc p
    WHERE p.oid IN ('public.miy_guard_official_source_writer_by_role()'::regprocedure,
      'public.miy_recording_lock_producer(bigint,text,integer,text)'::regprocedure,
      'public.miy_read_official_company_partition(text,uuid)'::regprocedure)
      AND (NOT p.prosecdef OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']
        OR EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
          WHERE a.grantee=0 AND a.privilege_type='EXECUTE'))) THEN
    RAISE EXCEPTION 'official_projection_partition_unavailable' USING ERRCODE='55000';
  END IF;
  SELECT r.* INTO STRICT function_owner FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_roles r ON r.oid=p.proowner
    WHERE p.oid='public.miy_read_official_company_partition(text,uuid)'::regprocedure;
  IF function_owner.rolcanlogin OR function_owner.rolsuper OR function_owner.rolinherit
     OR function_owner.rolcreatedb OR function_owner.rolcreaterole OR function_owner.rolreplication
     OR function_owner.rolbypassrls
     OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=function_owner.oid OR roleid=function_owner.oid)
  THEN RAISE EXCEPTION 'official_projection_partition_unavailable' USING ERRCODE='55000'; END IF;
  BEGIN
    SELECT p.id INTO STRICT descriptor FROM public.retrieval_partitions p
      WHERE p.source_namespace=miy_read_official_company_partition.source_namespace
        AND p.candidate_scope_kind='company' AND p.candidate_user_id IS NULL
        AND p.state='active' AND p.is_default_ingest AND p.metadata_version>=1
      FOR SHARE OF p;
  EXCEPTION WHEN no_data_found OR too_many_rows THEN
    RAISE EXCEPTION 'official_projection_partition_unavailable' USING ERRCODE='55000';
  END;
  IF bound_partition_id IS NOT NULL AND bound_partition_id IS DISTINCT FROM descriptor THEN
    RAISE EXCEPTION 'official_projection_partition_unavailable' USING ERRCODE='55000';
  END IF;
  RETURN descriptor;
END $body$;
REVOKE ALL ON FUNCTION public.miy_read_official_company_partition(text,uuid) FROM PUBLIC;

CREATE FUNCTION public.miy_lock_official_projection_partition(partition_id uuid,source_namespace text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$
DECLARE actor record; descriptor uuid; function_owner record;
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed'
    OR partition_id IS NULL OR source_namespace IS NULL OR source_namespace NOT IN ('docs','pms','meeting') THEN
    RAISE EXCEPTION 'official_projection_partition_unavailable' USING ERRCODE='55000';
  END IF;
  SELECT r.* INTO STRICT actor FROM pg_catalog.pg_roles r WHERE r.rolname=session_user;
  IF NOT actor.rolcanlogin OR actor.rolsuper OR actor.rolinherit OR actor.rolcreatedb
    OR actor.rolcreaterole OR actor.rolreplication OR actor.rolbypassrls
    OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=actor.oid OR roleid=actor.oid)
    OR EXISTS(SELECT 1 FROM public.official_writer_principals p
      WHERE p.role_oid=actor.oid::bigint AND p.role_name=session_user)
    OR NOT pg_catalog.has_table_privilege(session_user,'public.official_projection_receipts','INSERT')
    OR NOT pg_catalog.has_table_privilege(session_user,'public.retrieval_projection_heads','UPDATE')
    OR NOT pg_catalog.has_table_privilege(session_user,'public.retrieval_projection_events','INSERT') THEN
    RAISE EXCEPTION 'projection_core_authority_required' USING ERRCODE='42501';
  END IF;
  IF EXISTS(SELECT 1 FROM pg_catalog.pg_proc p
    WHERE p.oid='public.miy_lock_official_projection_partition(uuid,text)'::regprocedure
      AND (NOT p.prosecdef OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']
        OR EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
          WHERE a.grantee=0 AND a.privilege_type='EXECUTE'))) THEN
    RAISE EXCEPTION 'official_projection_partition_unavailable' USING ERRCODE='55000';
  END IF;
  SELECT r.* INTO STRICT function_owner FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_roles r ON r.oid=p.proowner
    WHERE p.oid='public.miy_lock_official_projection_partition(uuid,text)'::regprocedure;
  IF function_owner.rolcanlogin OR function_owner.rolsuper OR function_owner.rolinherit
    OR function_owner.rolcreatedb OR function_owner.rolcreaterole OR function_owner.rolreplication
    OR function_owner.rolbypassrls
    OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=function_owner.oid OR roleid=function_owner.oid)
  THEN RAISE EXCEPTION 'official_projection_partition_unavailable' USING ERRCODE='55000'; END IF;
  BEGIN
    SELECT p.id INTO STRICT descriptor FROM public.retrieval_partitions p
      WHERE p.id=partition_id AND p.source_namespace=miy_lock_official_projection_partition.source_namespace
        AND p.candidate_scope_kind='company' AND p.candidate_user_id IS NULL
        AND p.state='active' AND p.metadata_version>=1
      FOR SHARE OF p;
  EXCEPTION WHEN no_data_found OR too_many_rows THEN
    RAISE EXCEPTION 'official_projection_partition_unavailable' USING ERRCODE='55000';
  END;
  RETURN descriptor;
END $body$;
REVOKE ALL ON FUNCTION public.miy_lock_official_projection_partition(uuid,text) FROM PUBLIC;
    """)


def downgrade() -> None:
    _guard()
    if op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p,
            LATERAL pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
            WHERE p.oid IN ('public.miy_read_official_company_partition(text,uuid)'::regprocedure,
                'public.miy_lock_official_projection_partition(uuid,text)'::regprocedure)
            AND a.grantee<>p.proowner AND a.privilege_type='EXECUTE')
    """)
    ):
        raise RuntimeError("official_projection_partition_requires_explicit_retirement")
    op.execute("DROP FUNCTION public.miy_lock_official_projection_partition(uuid,text)")
    op.execute(f"DROP FUNCTION {_SIGNATURE}")
