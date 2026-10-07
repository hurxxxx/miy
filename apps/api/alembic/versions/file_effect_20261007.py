"""Fixed Core Files unknown-effect history and lifecycle; no activation."""

from alembic import op
import sqlalchemy as sa

revision = "file_effect_20261007"
down_revision = "file_source_partition_20261007"
branch_labels = None
depends_on = None

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

_BODY_0 = """
DECLARE actor record; event record; keyword record; vector record; head record;
  source record; receipt record; file record; descriptor uuid; function_owner record;
BEGIN

  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'file_materialization_effect_requires_read_committed' USING ERRCODE='55000';
  END IF;
  SELECT r.* INTO STRICT actor FROM pg_catalog.pg_roles r WHERE r.rolname=session_user;
  IF NOT actor.rolcanlogin OR actor.rolsuper OR actor.rolinherit OR actor.rolcreatedb
    OR actor.rolcreaterole OR actor.rolreplication OR actor.rolbypassrls
    OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=actor.oid OR m.roleid=actor.oid)
    OR EXISTS(SELECT 1 FROM public.official_writer_principals p
      WHERE p.role_oid=actor.oid::bigint OR p.role_name=session_user)
  THEN RAISE EXCEPTION 'file_materialization_effect_authority_invalid' USING ERRCODE='55000'; END IF;
  IF NOT pg_catalog.has_function_privilege(session_user,
      'public.miy_lock_file_materialization(bigint,uuid,uuid,integer)','EXECUTE')
    OR EXISTS(SELECT 1 FROM (VALUES
      ('public.file_manager_files','id','SELECT'),
      ('public.file_manager_files','owner_id','SELECT'),
      ('public.file_manager_files','filename','SELECT'),
      ('public.file_manager_files','folder_id','SELECT'),
      ('public.file_manager_files','corpus_id','SELECT'),
      ('public.file_manager_files','content_type','SELECT'),
      ('public.file_manager_files','size_bytes','SELECT'),
      ('public.file_manager_files','visibility','SELECT'),
      ('public.file_manager_files','updated_at','SELECT'),
      ('public.file_manager_files','retrieval_partition_id','SELECT'),
      ('public.file_manager_files','deleted_at','SELECT'),
      ('public.file_manager_files','extraction_status','SELECT'),
      ('public.file_manager_files','extraction_content_checksum','SELECT'),
      ('public.file_manager_files','extraction_text','SELECT'),
      ('public.file_manager_files','extraction_blocks','SELECT'),
      ('public.file_manager_files','extraction_metadata','SELECT'),
      ('public.file_manager_files','extracted_at','SELECT'),
      ('public.users','id','SELECT'),
      ('public.users','display_name','SELECT'),
      ('public.users','full_name','SELECT'),
      ('public.file_manager_corpora','id','SELECT'),
      ('public.file_manager_corpora','access_scope_kind','SELECT'),
      ('public.file_manager_corpora','retrieval_partition_id','SELECT'),
      ('public.file_manager_file_source_metadata','file_id','SELECT'),
      ('public.file_manager_file_source_metadata','corpus_id','SELECT'),
      ('public.file_manager_file_source_metadata','source_kind','SELECT'),
      ('public.file_manager_file_source_metadata','title','SELECT'),
      ('public.file_manager_file_source_metadata','author','SELECT'),
      ('public.file_manager_file_source_metadata','authored_at','SELECT'),
      ('public.file_manager_file_source_metadata','department','SELECT'),
      ('public.file_manager_file_source_metadata','document_type','SELECT'),
      ('public.file_manager_file_source_metadata','source_updated_at','SELECT'),
      ('public.file_manager_file_source_metadata','content_checksum','SELECT'),
      ('public.official_projection_outbox','event_id','SELECT'),
      ('public.official_projection_outbox','resource_type','SELECT'),
      ('public.official_projection_outbox','resource_id','SELECT'),
      ('public.official_projection_outbox','source_revision','SELECT'),
      ('public.official_projection_outbox','payload_digest','SELECT'),
      ('public.official_projection_receipts','event_id','SELECT'),
      ('public.official_projection_receipts','resource_type','SELECT'),
      ('public.official_projection_receipts','resource_id','SELECT'),
      ('public.official_projection_receipts','source_revision','SELECT'),
      ('public.official_projection_receipts','payload_digest','SELECT'),
      ('public.official_projection_receipts','status','SELECT'),
      ('public.official_projection_receipts','core_event_sequence','SELECT'),
      ('public.retrieval_projection_events','event_sequence','SELECT'),
      ('public.retrieval_projection_events','resource_type','SELECT'),
      ('public.retrieval_projection_events','resource_id','SELECT'),
      ('public.retrieval_projection_events','projection_version','SELECT'),
      ('public.retrieval_projection_events','retrieval_partition_id','SELECT'),
      ('public.retrieval_projection_events','change_kind','SELECT'),
      ('public.retrieval_projection_events','desired_state','SELECT'),
      ('public.retrieval_projection_events','content_checksum','SELECT'),
      ('public.retrieval_projection_events','visibility_checksum','SELECT'),
      ('public.retrieval_projection_heads','resource_type','SELECT'),
      ('public.retrieval_projection_heads','resource_id','SELECT'),
      ('public.retrieval_projection_heads','projection_version','SELECT'),
      ('public.retrieval_projection_heads','retrieval_partition_id','SELECT'),
      ('public.retrieval_projection_heads','desired_state','SELECT'),
      ('public.retrieval_projection_heads','content_checksum','SELECT'),
      ('public.retrieval_projection_heads','visibility_checksum','SELECT'),
      ('public.official_writer_principals','role_oid','SELECT'),
      ('public.official_writer_principals','role_name','SELECT'),
      ('public.retrieval_projection_generations','id','SELECT'),
      ('public.retrieval_projection_generations','backend','SELECT'),
      ('public.retrieval_projection_generations','generation_key','SELECT'),
      ('public.retrieval_projection_generations','physical_name','SELECT'),
      ('public.retrieval_projection_generations','schema_version','SELECT'),
      ('public.retrieval_projection_generations','state','SELECT'),
      ('public.retrieval_partitions','id','SELECT'),
      ('public.retrieval_partitions','source_namespace','SELECT'),
      ('public.retrieval_partitions','candidate_scope_kind','SELECT'),
      ('public.retrieval_partitions','candidate_user_id','SELECT'),
      ('public.retrieval_partitions','state','SELECT'),
      ('public.retrieval_partitions','metadata_version','SELECT'),
      ('public.core_file_materialization_operations','operation_id','SELECT'),
      ('public.core_file_materialization_operations','event_sequence','SELECT'),
      ('public.core_file_materialization_operations','resource_type','SELECT'),
      ('public.core_file_materialization_operations','resource_id','SELECT'),
      ('public.core_file_materialization_operations','projection_version','SELECT'),
      ('public.core_file_materialization_operations','retrieval_partition_id','SELECT'),
      ('public.core_file_materialization_operations','partition_metadata_version','SELECT'),
      ('public.core_file_materialization_operations','change_kind','SELECT'),
      ('public.core_file_materialization_operations','desired_state','SELECT'),
      ('public.core_file_materialization_operations','content_checksum','SELECT'),
      ('public.core_file_materialization_operations','visibility_checksum','SELECT'),
      ('public.core_file_materialization_operations','source_event_id','SELECT'),
      ('public.core_file_materialization_operations','source_revision','SELECT'),
      ('public.core_file_materialization_operations','source_payload_digest','SELECT'),
      ('public.core_file_materialization_operations','source_extracted_at','SELECT'),
      ('public.core_file_materialization_operations','keyword_generation_id','SELECT'),
      ('public.core_file_materialization_operations','vector_generation_id','SELECT'),
      ('public.core_file_materialization_operations','generation_key','SELECT'),
      ('public.core_file_materialization_operations','keyword_physical_name','SELECT'),
      ('public.core_file_materialization_operations','vector_physical_name','SELECT'),
      ('public.core_file_materialization_operations','keyword_schema_version','SELECT'),
      ('public.core_file_materialization_operations','vector_schema_version','SELECT'),
      ('public.core_file_materialization_operations','issuer_role_oid','SELECT'),
      ('public.core_file_materialization_operations','issuer_role_name','SELECT'),
      ('public.core_file_materialization_operations','armed_xact_id','SELECT'),
      ('public.core_file_materialization_operations','header_digest','SELECT'),
      ('public.core_file_materialization_operations','state','SELECT'),
      ('public.core_file_materialization_operations','created_at','SELECT'),
      ('public.core_file_materialization_operations','completed_at','SELECT'),
      ('public.search_index_jobs','id','SELECT'),
      ('public.search_index_jobs','resource_type','SELECT'),
      ('public.search_index_jobs','entity_type','SELECT'),
      ('public.search_index_jobs','entity_id','SELECT'),
      ('public.search_index_jobs','projection_version','SELECT'),
      ('public.search_index_jobs','projection_event_sequence','SELECT'),
      ('public.search_index_jobs','retrieval_partition_id','SELECT'),
      ('public.search_index_jobs','desired_state','SELECT'),
      ('public.search_index_jobs','operation','SELECT'),
      ('public.search_index_jobs','status','SELECT'),
      ('public.search_index_jobs','attempts','SELECT'),
      ('public.rag_sync_jobs','id','SELECT'),
      ('public.rag_sync_jobs','resource_type','SELECT'),
      ('public.rag_sync_jobs','resource_id','SELECT'),
      ('public.rag_sync_jobs','projection_version','SELECT'),
      ('public.rag_sync_jobs','projection_event_sequence','SELECT'),
      ('public.rag_sync_jobs','retrieval_partition_id','SELECT'),
      ('public.rag_sync_jobs','desired_state','SELECT'),
      ('public.rag_sync_jobs','operation','SELECT'),
      ('public.rag_sync_jobs','status','SELECT'),
      ('public.rag_sync_jobs','attempts','SELECT'),
      ('public.core_file_materialization_operations','operation_id','INSERT'),
      ('public.core_file_materialization_operations','event_sequence','INSERT'),
      ('public.core_file_materialization_operations','resource_type','INSERT'),
      ('public.core_file_materialization_operations','resource_id','INSERT'),
      ('public.core_file_materialization_operations','projection_version','INSERT'),
      ('public.core_file_materialization_operations','retrieval_partition_id','INSERT'),
      ('public.core_file_materialization_operations','partition_metadata_version','INSERT'),
      ('public.core_file_materialization_operations','change_kind','INSERT'),
      ('public.core_file_materialization_operations','desired_state','INSERT'),
      ('public.core_file_materialization_operations','content_checksum','INSERT'),
      ('public.core_file_materialization_operations','visibility_checksum','INSERT'),
      ('public.core_file_materialization_operations','source_event_id','INSERT'),
      ('public.core_file_materialization_operations','source_revision','INSERT'),
      ('public.core_file_materialization_operations','source_payload_digest','INSERT'),
      ('public.core_file_materialization_operations','source_extracted_at','INSERT'),
      ('public.core_file_materialization_operations','keyword_generation_id','INSERT'),
      ('public.core_file_materialization_operations','vector_generation_id','INSERT'),
      ('public.core_file_materialization_operations','generation_key','INSERT'),
      ('public.core_file_materialization_operations','keyword_physical_name','INSERT'),
      ('public.core_file_materialization_operations','vector_physical_name','INSERT'),
      ('public.core_file_materialization_operations','keyword_schema_version','INSERT'),
      ('public.core_file_materialization_operations','vector_schema_version','INSERT'),
      ('public.core_file_materialization_operations','state','UPDATE'),
      ('public.search_index_jobs','status','UPDATE'),
      ('public.search_index_jobs','attempts','UPDATE'),
      ('public.search_index_jobs','last_error','UPDATE'),
      ('public.search_index_jobs','next_retry_at','UPDATE'),
      ('public.search_index_jobs','updated_at','UPDATE'),
      ('public.rag_sync_jobs','status','UPDATE'),
      ('public.rag_sync_jobs','attempts','UPDATE'),
      ('public.rag_sync_jobs','last_error','UPDATE'),
      ('public.rag_sync_jobs','next_retry_at','UPDATE'),
      ('public.rag_sync_jobs','updated_at','UPDATE')
    ) AS required(relation_name,column_name,privilege)
      WHERE NOT pg_catalog.has_column_privilege(session_user,relation_name,column_name,privilege))
  THEN RAISE EXCEPTION 'file_materialization_effect_authority_invalid' USING ERRCODE='55000'; END IF;

  IF event_sequence IS NULL OR event_sequence<1 OR keyword_generation_id IS NULL
    OR vector_generation_id IS NULL OR keyword_generation_id=vector_generation_id
    OR expected_partition_metadata_version IS NULL OR expected_partition_metadata_version<1
  THEN RAISE EXCEPTION 'file_materialization_effect_unavailable' USING ERRCODE='55000'; END IF;
  SELECT r.* INTO STRICT function_owner FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_roles r ON r.oid=p.proowner
    WHERE p.oid='public.miy_lock_file_materialization(bigint,uuid,uuid,integer)'::regprocedure;
  IF function_owner.rolcanlogin OR function_owner.rolsuper OR function_owner.rolinherit
    OR function_owner.rolcreatedb OR function_owner.rolcreaterole OR function_owner.rolreplication
    OR function_owner.rolbypassrls
    OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=function_owner.oid OR m.roleid=function_owner.oid)
  THEN RAISE EXCEPTION 'file_materialization_effect_owner_invalid' USING ERRCODE='55000'; END IF;
  SELECT e.event_sequence,e.resource_type,e.resource_id,e.projection_version,
    e.retrieval_partition_id,e.change_kind,e.desired_state,e.content_checksum,e.visibility_checksum
    INTO STRICT event FROM public.retrieval_projection_events e
    WHERE e.event_sequence=miy_lock_file_materialization.event_sequence
      AND e.resource_type='file_manager_file';
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'official.projection:file_manager_file:'||event.resource_id,0));
  SELECT p.id INTO STRICT descriptor FROM public.retrieval_partitions p
    WHERE p.id=event.retrieval_partition_id AND p.source_namespace='files'
      AND p.candidate_scope_kind='company' AND p.candidate_user_id IS NULL
      AND p.state='active' AND p.metadata_version=expected_partition_metadata_version
    FOR SHARE OF p;
  PERFORM pg_catalog.pg_advisory_xact_lock_shared(pg_catalog.hashtextextended(
    'retrieval-projection-generation-pair',0));
  SELECT g.id,g.backend,g.generation_key,g.physical_name,g.schema_version,g.state
    INTO STRICT keyword FROM public.retrieval_projection_generations g
    WHERE g.id=keyword_generation_id AND g.backend='opensearch' FOR SHARE OF g;
  SELECT g.id,g.backend,g.generation_key,g.physical_name,g.schema_version,g.state
    INTO STRICT vector FROM public.retrieval_projection_generations g
    WHERE g.id=vector_generation_id AND g.backend='qdrant' FOR SHARE OF g;
  IF keyword.state NOT IN ('baselining','replaying') OR keyword.state<>vector.state
    OR keyword.generation_key<>vector.generation_key
    OR keyword.schema_version<>3 OR vector.schema_version<>1
    OR length(trim(keyword.physical_name))=0 OR length(trim(vector.physical_name))=0
  THEN RAISE EXCEPTION 'file_materialization_effect_generation_invalid' USING ERRCODE='55000'; END IF;
  SELECT h.resource_type,h.resource_id,h.projection_version,h.retrieval_partition_id,
    h.desired_state,h.content_checksum,h.visibility_checksum INTO STRICT head
    FROM public.retrieval_projection_heads h
    WHERE h.resource_type='file_manager_file' AND h.resource_id=event.resource_id FOR SHARE OF h;
  IF ROW(head.resource_type,head.resource_id,head.projection_version,head.retrieval_partition_id,
      head.desired_state,head.content_checksum,head.visibility_checksum) IS DISTINCT FROM
    ROW(event.resource_type,event.resource_id,event.projection_version,event.retrieval_partition_id,
      event.desired_state,event.content_checksum,event.visibility_checksum)
  THEN RAISE EXCEPTION 'file_materialization_effect_head_changed' USING ERRCODE='55000'; END IF;

  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'file_materialization_effect_requires_read_committed' USING ERRCODE='55000';
  END IF;
  SELECT r.* INTO STRICT actor FROM pg_catalog.pg_roles r WHERE r.rolname=session_user;
  IF NOT actor.rolcanlogin OR actor.rolsuper OR actor.rolinherit OR actor.rolcreatedb
    OR actor.rolcreaterole OR actor.rolreplication OR actor.rolbypassrls
    OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=actor.oid OR m.roleid=actor.oid)
    OR EXISTS(SELECT 1 FROM public.official_writer_principals p
      WHERE p.role_oid=actor.oid::bigint OR p.role_name=session_user)
  THEN RAISE EXCEPTION 'file_materialization_effect_authority_invalid' USING ERRCODE='55000'; END IF;
  IF NOT pg_catalog.has_function_privilege(session_user,
      'public.miy_lock_file_materialization(bigint,uuid,uuid,integer)','EXECUTE')
    OR EXISTS(SELECT 1 FROM (VALUES
      ('public.file_manager_files','id','SELECT'),
      ('public.file_manager_files','owner_id','SELECT'),
      ('public.file_manager_files','filename','SELECT'),
      ('public.file_manager_files','folder_id','SELECT'),
      ('public.file_manager_files','corpus_id','SELECT'),
      ('public.file_manager_files','content_type','SELECT'),
      ('public.file_manager_files','size_bytes','SELECT'),
      ('public.file_manager_files','visibility','SELECT'),
      ('public.file_manager_files','updated_at','SELECT'),
      ('public.file_manager_files','retrieval_partition_id','SELECT'),
      ('public.file_manager_files','deleted_at','SELECT'),
      ('public.file_manager_files','extraction_status','SELECT'),
      ('public.file_manager_files','extraction_content_checksum','SELECT'),
      ('public.file_manager_files','extraction_text','SELECT'),
      ('public.file_manager_files','extraction_blocks','SELECT'),
      ('public.file_manager_files','extraction_metadata','SELECT'),
      ('public.file_manager_files','extracted_at','SELECT'),
      ('public.users','id','SELECT'),
      ('public.users','display_name','SELECT'),
      ('public.users','full_name','SELECT'),
      ('public.file_manager_corpora','id','SELECT'),
      ('public.file_manager_corpora','access_scope_kind','SELECT'),
      ('public.file_manager_corpora','retrieval_partition_id','SELECT'),
      ('public.file_manager_file_source_metadata','file_id','SELECT'),
      ('public.file_manager_file_source_metadata','corpus_id','SELECT'),
      ('public.file_manager_file_source_metadata','source_kind','SELECT'),
      ('public.file_manager_file_source_metadata','title','SELECT'),
      ('public.file_manager_file_source_metadata','author','SELECT'),
      ('public.file_manager_file_source_metadata','authored_at','SELECT'),
      ('public.file_manager_file_source_metadata','department','SELECT'),
      ('public.file_manager_file_source_metadata','document_type','SELECT'),
      ('public.file_manager_file_source_metadata','source_updated_at','SELECT'),
      ('public.file_manager_file_source_metadata','content_checksum','SELECT'),
      ('public.official_projection_outbox','event_id','SELECT'),
      ('public.official_projection_outbox','resource_type','SELECT'),
      ('public.official_projection_outbox','resource_id','SELECT'),
      ('public.official_projection_outbox','source_revision','SELECT'),
      ('public.official_projection_outbox','payload_digest','SELECT'),
      ('public.official_projection_receipts','event_id','SELECT'),
      ('public.official_projection_receipts','resource_type','SELECT'),
      ('public.official_projection_receipts','resource_id','SELECT'),
      ('public.official_projection_receipts','source_revision','SELECT'),
      ('public.official_projection_receipts','payload_digest','SELECT'),
      ('public.official_projection_receipts','status','SELECT'),
      ('public.official_projection_receipts','core_event_sequence','SELECT'),
      ('public.retrieval_projection_events','event_sequence','SELECT'),
      ('public.retrieval_projection_events','resource_type','SELECT'),
      ('public.retrieval_projection_events','resource_id','SELECT'),
      ('public.retrieval_projection_events','projection_version','SELECT'),
      ('public.retrieval_projection_events','retrieval_partition_id','SELECT'),
      ('public.retrieval_projection_events','change_kind','SELECT'),
      ('public.retrieval_projection_events','desired_state','SELECT'),
      ('public.retrieval_projection_events','content_checksum','SELECT'),
      ('public.retrieval_projection_events','visibility_checksum','SELECT'),
      ('public.retrieval_projection_heads','resource_type','SELECT'),
      ('public.retrieval_projection_heads','resource_id','SELECT'),
      ('public.retrieval_projection_heads','projection_version','SELECT'),
      ('public.retrieval_projection_heads','retrieval_partition_id','SELECT'),
      ('public.retrieval_projection_heads','desired_state','SELECT'),
      ('public.retrieval_projection_heads','content_checksum','SELECT'),
      ('public.retrieval_projection_heads','visibility_checksum','SELECT'),
      ('public.official_writer_principals','role_oid','SELECT'),
      ('public.official_writer_principals','role_name','SELECT'),
      ('public.retrieval_projection_generations','id','SELECT'),
      ('public.retrieval_projection_generations','backend','SELECT'),
      ('public.retrieval_projection_generations','generation_key','SELECT'),
      ('public.retrieval_projection_generations','physical_name','SELECT'),
      ('public.retrieval_projection_generations','schema_version','SELECT'),
      ('public.retrieval_projection_generations','state','SELECT'),
      ('public.retrieval_partitions','id','SELECT'),
      ('public.retrieval_partitions','source_namespace','SELECT'),
      ('public.retrieval_partitions','candidate_scope_kind','SELECT'),
      ('public.retrieval_partitions','candidate_user_id','SELECT'),
      ('public.retrieval_partitions','state','SELECT'),
      ('public.retrieval_partitions','metadata_version','SELECT'),
      ('public.core_file_materialization_operations','operation_id','SELECT'),
      ('public.core_file_materialization_operations','event_sequence','SELECT'),
      ('public.core_file_materialization_operations','resource_type','SELECT'),
      ('public.core_file_materialization_operations','resource_id','SELECT'),
      ('public.core_file_materialization_operations','projection_version','SELECT'),
      ('public.core_file_materialization_operations','retrieval_partition_id','SELECT'),
      ('public.core_file_materialization_operations','partition_metadata_version','SELECT'),
      ('public.core_file_materialization_operations','change_kind','SELECT'),
      ('public.core_file_materialization_operations','desired_state','SELECT'),
      ('public.core_file_materialization_operations','content_checksum','SELECT'),
      ('public.core_file_materialization_operations','visibility_checksum','SELECT'),
      ('public.core_file_materialization_operations','source_event_id','SELECT'),
      ('public.core_file_materialization_operations','source_revision','SELECT'),
      ('public.core_file_materialization_operations','source_payload_digest','SELECT'),
      ('public.core_file_materialization_operations','source_extracted_at','SELECT'),
      ('public.core_file_materialization_operations','keyword_generation_id','SELECT'),
      ('public.core_file_materialization_operations','vector_generation_id','SELECT'),
      ('public.core_file_materialization_operations','generation_key','SELECT'),
      ('public.core_file_materialization_operations','keyword_physical_name','SELECT'),
      ('public.core_file_materialization_operations','vector_physical_name','SELECT'),
      ('public.core_file_materialization_operations','keyword_schema_version','SELECT'),
      ('public.core_file_materialization_operations','vector_schema_version','SELECT'),
      ('public.core_file_materialization_operations','issuer_role_oid','SELECT'),
      ('public.core_file_materialization_operations','issuer_role_name','SELECT'),
      ('public.core_file_materialization_operations','armed_xact_id','SELECT'),
      ('public.core_file_materialization_operations','header_digest','SELECT'),
      ('public.core_file_materialization_operations','state','SELECT'),
      ('public.core_file_materialization_operations','created_at','SELECT'),
      ('public.core_file_materialization_operations','completed_at','SELECT'),
      ('public.search_index_jobs','id','SELECT'),
      ('public.search_index_jobs','resource_type','SELECT'),
      ('public.search_index_jobs','entity_type','SELECT'),
      ('public.search_index_jobs','entity_id','SELECT'),
      ('public.search_index_jobs','projection_version','SELECT'),
      ('public.search_index_jobs','projection_event_sequence','SELECT'),
      ('public.search_index_jobs','retrieval_partition_id','SELECT'),
      ('public.search_index_jobs','desired_state','SELECT'),
      ('public.search_index_jobs','operation','SELECT'),
      ('public.search_index_jobs','status','SELECT'),
      ('public.search_index_jobs','attempts','SELECT'),
      ('public.rag_sync_jobs','id','SELECT'),
      ('public.rag_sync_jobs','resource_type','SELECT'),
      ('public.rag_sync_jobs','resource_id','SELECT'),
      ('public.rag_sync_jobs','projection_version','SELECT'),
      ('public.rag_sync_jobs','projection_event_sequence','SELECT'),
      ('public.rag_sync_jobs','retrieval_partition_id','SELECT'),
      ('public.rag_sync_jobs','desired_state','SELECT'),
      ('public.rag_sync_jobs','operation','SELECT'),
      ('public.rag_sync_jobs','status','SELECT'),
      ('public.rag_sync_jobs','attempts','SELECT'),
      ('public.core_file_materialization_operations','operation_id','INSERT'),
      ('public.core_file_materialization_operations','event_sequence','INSERT'),
      ('public.core_file_materialization_operations','resource_type','INSERT'),
      ('public.core_file_materialization_operations','resource_id','INSERT'),
      ('public.core_file_materialization_operations','projection_version','INSERT'),
      ('public.core_file_materialization_operations','retrieval_partition_id','INSERT'),
      ('public.core_file_materialization_operations','partition_metadata_version','INSERT'),
      ('public.core_file_materialization_operations','change_kind','INSERT'),
      ('public.core_file_materialization_operations','desired_state','INSERT'),
      ('public.core_file_materialization_operations','content_checksum','INSERT'),
      ('public.core_file_materialization_operations','visibility_checksum','INSERT'),
      ('public.core_file_materialization_operations','source_event_id','INSERT'),
      ('public.core_file_materialization_operations','source_revision','INSERT'),
      ('public.core_file_materialization_operations','source_payload_digest','INSERT'),
      ('public.core_file_materialization_operations','source_extracted_at','INSERT'),
      ('public.core_file_materialization_operations','keyword_generation_id','INSERT'),
      ('public.core_file_materialization_operations','vector_generation_id','INSERT'),
      ('public.core_file_materialization_operations','generation_key','INSERT'),
      ('public.core_file_materialization_operations','keyword_physical_name','INSERT'),
      ('public.core_file_materialization_operations','vector_physical_name','INSERT'),
      ('public.core_file_materialization_operations','keyword_schema_version','INSERT'),
      ('public.core_file_materialization_operations','vector_schema_version','INSERT'),
      ('public.core_file_materialization_operations','state','UPDATE'),
      ('public.search_index_jobs','status','UPDATE'),
      ('public.search_index_jobs','attempts','UPDATE'),
      ('public.search_index_jobs','last_error','UPDATE'),
      ('public.search_index_jobs','next_retry_at','UPDATE'),
      ('public.search_index_jobs','updated_at','UPDATE'),
      ('public.rag_sync_jobs','status','UPDATE'),
      ('public.rag_sync_jobs','attempts','UPDATE'),
      ('public.rag_sync_jobs','last_error','UPDATE'),
      ('public.rag_sync_jobs','next_retry_at','UPDATE'),
      ('public.rag_sync_jobs','updated_at','UPDATE')
    ) AS required(relation_name,column_name,privilege)
      WHERE NOT pg_catalog.has_column_privilege(session_user,relation_name,column_name,privilege))
  THEN RAISE EXCEPTION 'file_materialization_effect_authority_invalid' USING ERRCODE='55000'; END IF;

  SELECT o.event_id,o.resource_type,o.resource_id,o.source_revision,o.payload_digest INTO STRICT source
    FROM public.official_projection_outbox o
    WHERE o.resource_type='file_manager_file' AND o.resource_id=event.resource_id
    ORDER BY o.source_revision DESC LIMIT 1;
  SELECT r.event_id,r.resource_type,r.resource_id,r.source_revision,r.payload_digest,
    r.status,r.core_event_sequence INTO STRICT receipt FROM public.official_projection_receipts r
    WHERE r.event_id=source.event_id;
  IF ROW(receipt.event_id,receipt.resource_type,receipt.resource_id,receipt.source_revision,receipt.payload_digest)
    IS DISTINCT FROM ROW(source.event_id,source.resource_type,source.resource_id,source.source_revision,source.payload_digest)
    OR receipt.status<>'accepted' OR receipt.core_event_sequence IS DISTINCT FROM event.event_sequence
  THEN RAISE EXCEPTION 'file_materialization_effect_source_changed' USING ERRCODE='55000'; END IF;
  SELECT f.id,f.corpus_id,f.retrieval_partition_id,f.deleted_at,f.extraction_status,
    f.extraction_content_checksum,f.extracted_at,c.id AS corpus_identity,
    c.access_scope_kind,c.retrieval_partition_id AS corpus_partition,
    m.file_id AS metadata_file,m.corpus_id AS metadata_corpus,m.content_checksum AS metadata_checksum
    INTO file FROM public.file_manager_files f
    LEFT JOIN public.file_manager_corpora c ON c.id=f.corpus_id
    LEFT JOIN public.file_manager_file_source_metadata m ON m.file_id=f.id
    WHERE f.id=event.resource_id;
  IF FOUND AND (file.retrieval_partition_id IS DISTINCT FROM event.retrieval_partition_id
    OR (file.corpus_id IS NOT NULL AND ROW(file.corpus_identity,file.access_scope_kind,file.corpus_partition)
      IS DISTINCT FROM ROW(file.corpus_id,'company'::varchar,event.retrieval_partition_id))
    OR (file.metadata_file IS NOT NULL AND (file.metadata_file<>file.id
      OR file.corpus_id IS NULL OR file.metadata_corpus IS DISTINCT FROM file.corpus_id)))
  THEN RAISE EXCEPTION 'file_materialization_effect_source_binding_invalid' USING ERRCODE='55000'; END IF;
  IF event.desired_state='active' THEN
    IF file.id IS NULL OR file.deleted_at IS NOT NULL OR file.extraction_status<>'ready'
      OR event.content_checksum IS NULL OR event.content_checksum !~ '^[a-f0-9]{64}$'
      OR file.extraction_content_checksum IS DISTINCT FROM event.content_checksum
      OR file.extracted_at IS NULL
      OR (file.metadata_file IS NOT NULL AND file.metadata_checksum IS DISTINCT FROM event.content_checksum)
    THEN RAISE EXCEPTION 'file_materialization_effect_source_not_ready' USING ERRCODE='55000'; END IF;
  ELSIF event.desired_state='deleted' THEN
    IF file.id IS NOT NULL AND file.deleted_at IS NULL AND file.extraction_status<>'unsupported'
    THEN RAISE EXCEPTION 'file_materialization_effect_source_not_deleted' USING ERRCODE='55000'; END IF;
  ELSE RAISE EXCEPTION 'file_materialization_effect_unavailable' USING ERRCODE='55000'; END IF;
  RETURN descriptor;
EXCEPTION WHEN no_data_found OR too_many_rows THEN
  RAISE EXCEPTION 'file_materialization_effect_unavailable' USING ERRCODE='55000';
END
"""

_BODY_1 = """
DECLARE actor record;
BEGIN

  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'file_materialization_effect_requires_read_committed' USING ERRCODE='55000';
  END IF;
  SELECT r.* INTO STRICT actor FROM pg_catalog.pg_roles r WHERE r.rolname=session_user;
  IF NOT actor.rolcanlogin OR actor.rolsuper OR actor.rolinherit OR actor.rolcreatedb
    OR actor.rolcreaterole OR actor.rolreplication OR actor.rolbypassrls
    OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=actor.oid OR m.roleid=actor.oid)
    OR EXISTS(SELECT 1 FROM public.official_writer_principals p
      WHERE p.role_oid=actor.oid::bigint OR p.role_name=session_user)
  THEN RAISE EXCEPTION 'file_materialization_effect_authority_invalid' USING ERRCODE='55000'; END IF;
  IF NOT pg_catalog.has_function_privilege(session_user,
      'public.miy_lock_file_materialization(bigint,uuid,uuid,integer)','EXECUTE')
    OR EXISTS(SELECT 1 FROM (VALUES
      ('public.file_manager_files','id','SELECT'),
      ('public.file_manager_files','owner_id','SELECT'),
      ('public.file_manager_files','filename','SELECT'),
      ('public.file_manager_files','folder_id','SELECT'),
      ('public.file_manager_files','corpus_id','SELECT'),
      ('public.file_manager_files','content_type','SELECT'),
      ('public.file_manager_files','size_bytes','SELECT'),
      ('public.file_manager_files','visibility','SELECT'),
      ('public.file_manager_files','updated_at','SELECT'),
      ('public.file_manager_files','retrieval_partition_id','SELECT'),
      ('public.file_manager_files','deleted_at','SELECT'),
      ('public.file_manager_files','extraction_status','SELECT'),
      ('public.file_manager_files','extraction_content_checksum','SELECT'),
      ('public.file_manager_files','extraction_text','SELECT'),
      ('public.file_manager_files','extraction_blocks','SELECT'),
      ('public.file_manager_files','extraction_metadata','SELECT'),
      ('public.file_manager_files','extracted_at','SELECT'),
      ('public.users','id','SELECT'),
      ('public.users','display_name','SELECT'),
      ('public.users','full_name','SELECT'),
      ('public.file_manager_corpora','id','SELECT'),
      ('public.file_manager_corpora','access_scope_kind','SELECT'),
      ('public.file_manager_corpora','retrieval_partition_id','SELECT'),
      ('public.file_manager_file_source_metadata','file_id','SELECT'),
      ('public.file_manager_file_source_metadata','corpus_id','SELECT'),
      ('public.file_manager_file_source_metadata','source_kind','SELECT'),
      ('public.file_manager_file_source_metadata','title','SELECT'),
      ('public.file_manager_file_source_metadata','author','SELECT'),
      ('public.file_manager_file_source_metadata','authored_at','SELECT'),
      ('public.file_manager_file_source_metadata','department','SELECT'),
      ('public.file_manager_file_source_metadata','document_type','SELECT'),
      ('public.file_manager_file_source_metadata','source_updated_at','SELECT'),
      ('public.file_manager_file_source_metadata','content_checksum','SELECT'),
      ('public.official_projection_outbox','event_id','SELECT'),
      ('public.official_projection_outbox','resource_type','SELECT'),
      ('public.official_projection_outbox','resource_id','SELECT'),
      ('public.official_projection_outbox','source_revision','SELECT'),
      ('public.official_projection_outbox','payload_digest','SELECT'),
      ('public.official_projection_receipts','event_id','SELECT'),
      ('public.official_projection_receipts','resource_type','SELECT'),
      ('public.official_projection_receipts','resource_id','SELECT'),
      ('public.official_projection_receipts','source_revision','SELECT'),
      ('public.official_projection_receipts','payload_digest','SELECT'),
      ('public.official_projection_receipts','status','SELECT'),
      ('public.official_projection_receipts','core_event_sequence','SELECT'),
      ('public.retrieval_projection_events','event_sequence','SELECT'),
      ('public.retrieval_projection_events','resource_type','SELECT'),
      ('public.retrieval_projection_events','resource_id','SELECT'),
      ('public.retrieval_projection_events','projection_version','SELECT'),
      ('public.retrieval_projection_events','retrieval_partition_id','SELECT'),
      ('public.retrieval_projection_events','change_kind','SELECT'),
      ('public.retrieval_projection_events','desired_state','SELECT'),
      ('public.retrieval_projection_events','content_checksum','SELECT'),
      ('public.retrieval_projection_events','visibility_checksum','SELECT'),
      ('public.retrieval_projection_heads','resource_type','SELECT'),
      ('public.retrieval_projection_heads','resource_id','SELECT'),
      ('public.retrieval_projection_heads','projection_version','SELECT'),
      ('public.retrieval_projection_heads','retrieval_partition_id','SELECT'),
      ('public.retrieval_projection_heads','desired_state','SELECT'),
      ('public.retrieval_projection_heads','content_checksum','SELECT'),
      ('public.retrieval_projection_heads','visibility_checksum','SELECT'),
      ('public.official_writer_principals','role_oid','SELECT'),
      ('public.official_writer_principals','role_name','SELECT'),
      ('public.retrieval_projection_generations','id','SELECT'),
      ('public.retrieval_projection_generations','backend','SELECT'),
      ('public.retrieval_projection_generations','generation_key','SELECT'),
      ('public.retrieval_projection_generations','physical_name','SELECT'),
      ('public.retrieval_projection_generations','schema_version','SELECT'),
      ('public.retrieval_projection_generations','state','SELECT'),
      ('public.retrieval_partitions','id','SELECT'),
      ('public.retrieval_partitions','source_namespace','SELECT'),
      ('public.retrieval_partitions','candidate_scope_kind','SELECT'),
      ('public.retrieval_partitions','candidate_user_id','SELECT'),
      ('public.retrieval_partitions','state','SELECT'),
      ('public.retrieval_partitions','metadata_version','SELECT'),
      ('public.core_file_materialization_operations','operation_id','SELECT'),
      ('public.core_file_materialization_operations','event_sequence','SELECT'),
      ('public.core_file_materialization_operations','resource_type','SELECT'),
      ('public.core_file_materialization_operations','resource_id','SELECT'),
      ('public.core_file_materialization_operations','projection_version','SELECT'),
      ('public.core_file_materialization_operations','retrieval_partition_id','SELECT'),
      ('public.core_file_materialization_operations','partition_metadata_version','SELECT'),
      ('public.core_file_materialization_operations','change_kind','SELECT'),
      ('public.core_file_materialization_operations','desired_state','SELECT'),
      ('public.core_file_materialization_operations','content_checksum','SELECT'),
      ('public.core_file_materialization_operations','visibility_checksum','SELECT'),
      ('public.core_file_materialization_operations','source_event_id','SELECT'),
      ('public.core_file_materialization_operations','source_revision','SELECT'),
      ('public.core_file_materialization_operations','source_payload_digest','SELECT'),
      ('public.core_file_materialization_operations','source_extracted_at','SELECT'),
      ('public.core_file_materialization_operations','keyword_generation_id','SELECT'),
      ('public.core_file_materialization_operations','vector_generation_id','SELECT'),
      ('public.core_file_materialization_operations','generation_key','SELECT'),
      ('public.core_file_materialization_operations','keyword_physical_name','SELECT'),
      ('public.core_file_materialization_operations','vector_physical_name','SELECT'),
      ('public.core_file_materialization_operations','keyword_schema_version','SELECT'),
      ('public.core_file_materialization_operations','vector_schema_version','SELECT'),
      ('public.core_file_materialization_operations','issuer_role_oid','SELECT'),
      ('public.core_file_materialization_operations','issuer_role_name','SELECT'),
      ('public.core_file_materialization_operations','armed_xact_id','SELECT'),
      ('public.core_file_materialization_operations','header_digest','SELECT'),
      ('public.core_file_materialization_operations','state','SELECT'),
      ('public.core_file_materialization_operations','created_at','SELECT'),
      ('public.core_file_materialization_operations','completed_at','SELECT'),
      ('public.search_index_jobs','id','SELECT'),
      ('public.search_index_jobs','resource_type','SELECT'),
      ('public.search_index_jobs','entity_type','SELECT'),
      ('public.search_index_jobs','entity_id','SELECT'),
      ('public.search_index_jobs','projection_version','SELECT'),
      ('public.search_index_jobs','projection_event_sequence','SELECT'),
      ('public.search_index_jobs','retrieval_partition_id','SELECT'),
      ('public.search_index_jobs','desired_state','SELECT'),
      ('public.search_index_jobs','operation','SELECT'),
      ('public.search_index_jobs','status','SELECT'),
      ('public.search_index_jobs','attempts','SELECT'),
      ('public.rag_sync_jobs','id','SELECT'),
      ('public.rag_sync_jobs','resource_type','SELECT'),
      ('public.rag_sync_jobs','resource_id','SELECT'),
      ('public.rag_sync_jobs','projection_version','SELECT'),
      ('public.rag_sync_jobs','projection_event_sequence','SELECT'),
      ('public.rag_sync_jobs','retrieval_partition_id','SELECT'),
      ('public.rag_sync_jobs','desired_state','SELECT'),
      ('public.rag_sync_jobs','operation','SELECT'),
      ('public.rag_sync_jobs','status','SELECT'),
      ('public.rag_sync_jobs','attempts','SELECT'),
      ('public.core_file_materialization_operations','operation_id','INSERT'),
      ('public.core_file_materialization_operations','event_sequence','INSERT'),
      ('public.core_file_materialization_operations','resource_type','INSERT'),
      ('public.core_file_materialization_operations','resource_id','INSERT'),
      ('public.core_file_materialization_operations','projection_version','INSERT'),
      ('public.core_file_materialization_operations','retrieval_partition_id','INSERT'),
      ('public.core_file_materialization_operations','partition_metadata_version','INSERT'),
      ('public.core_file_materialization_operations','change_kind','INSERT'),
      ('public.core_file_materialization_operations','desired_state','INSERT'),
      ('public.core_file_materialization_operations','content_checksum','INSERT'),
      ('public.core_file_materialization_operations','visibility_checksum','INSERT'),
      ('public.core_file_materialization_operations','source_event_id','INSERT'),
      ('public.core_file_materialization_operations','source_revision','INSERT'),
      ('public.core_file_materialization_operations','source_payload_digest','INSERT'),
      ('public.core_file_materialization_operations','source_extracted_at','INSERT'),
      ('public.core_file_materialization_operations','keyword_generation_id','INSERT'),
      ('public.core_file_materialization_operations','vector_generation_id','INSERT'),
      ('public.core_file_materialization_operations','generation_key','INSERT'),
      ('public.core_file_materialization_operations','keyword_physical_name','INSERT'),
      ('public.core_file_materialization_operations','vector_physical_name','INSERT'),
      ('public.core_file_materialization_operations','keyword_schema_version','INSERT'),
      ('public.core_file_materialization_operations','vector_schema_version','INSERT'),
      ('public.core_file_materialization_operations','state','UPDATE'),
      ('public.search_index_jobs','status','UPDATE'),
      ('public.search_index_jobs','attempts','UPDATE'),
      ('public.search_index_jobs','last_error','UPDATE'),
      ('public.search_index_jobs','next_retry_at','UPDATE'),
      ('public.search_index_jobs','updated_at','UPDATE'),
      ('public.rag_sync_jobs','status','UPDATE'),
      ('public.rag_sync_jobs','attempts','UPDATE'),
      ('public.rag_sync_jobs','last_error','UPDATE'),
      ('public.rag_sync_jobs','next_retry_at','UPDATE'),
      ('public.rag_sync_jobs','updated_at','UPDATE')
    ) AS required(relation_name,column_name,privilege)
      WHERE NOT pg_catalog.has_column_privilege(session_user,relation_name,column_name,privilege))
  THEN RAISE EXCEPTION 'file_materialization_effect_authority_invalid' USING ERRCODE='55000'; END IF;

  IF TG_OP IN ('DELETE','TRUNCATE') THEN
    RAISE EXCEPTION 'file_materialization_effect_history_immutable' USING ERRCODE='55000';
  END IF;
  RETURN NULL;
END
"""

_BODY_2 = """
DECLARE actor record; event record; source record; keyword record; vector record; stamp timestamp;
BEGIN

  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'file_materialization_effect_requires_read_committed' USING ERRCODE='55000';
  END IF;
  SELECT r.* INTO STRICT actor FROM pg_catalog.pg_roles r WHERE r.rolname=session_user;
  IF NOT actor.rolcanlogin OR actor.rolsuper OR actor.rolinherit OR actor.rolcreatedb
    OR actor.rolcreaterole OR actor.rolreplication OR actor.rolbypassrls
    OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=actor.oid OR m.roleid=actor.oid)
    OR EXISTS(SELECT 1 FROM public.official_writer_principals p
      WHERE p.role_oid=actor.oid::bigint OR p.role_name=session_user)
  THEN RAISE EXCEPTION 'file_materialization_effect_authority_invalid' USING ERRCODE='55000'; END IF;
  IF NOT pg_catalog.has_function_privilege(session_user,
      'public.miy_lock_file_materialization(bigint,uuid,uuid,integer)','EXECUTE')
    OR EXISTS(SELECT 1 FROM (VALUES
      ('public.file_manager_files','id','SELECT'),
      ('public.file_manager_files','owner_id','SELECT'),
      ('public.file_manager_files','filename','SELECT'),
      ('public.file_manager_files','folder_id','SELECT'),
      ('public.file_manager_files','corpus_id','SELECT'),
      ('public.file_manager_files','content_type','SELECT'),
      ('public.file_manager_files','size_bytes','SELECT'),
      ('public.file_manager_files','visibility','SELECT'),
      ('public.file_manager_files','updated_at','SELECT'),
      ('public.file_manager_files','retrieval_partition_id','SELECT'),
      ('public.file_manager_files','deleted_at','SELECT'),
      ('public.file_manager_files','extraction_status','SELECT'),
      ('public.file_manager_files','extraction_content_checksum','SELECT'),
      ('public.file_manager_files','extraction_text','SELECT'),
      ('public.file_manager_files','extraction_blocks','SELECT'),
      ('public.file_manager_files','extraction_metadata','SELECT'),
      ('public.file_manager_files','extracted_at','SELECT'),
      ('public.users','id','SELECT'),
      ('public.users','display_name','SELECT'),
      ('public.users','full_name','SELECT'),
      ('public.file_manager_corpora','id','SELECT'),
      ('public.file_manager_corpora','access_scope_kind','SELECT'),
      ('public.file_manager_corpora','retrieval_partition_id','SELECT'),
      ('public.file_manager_file_source_metadata','file_id','SELECT'),
      ('public.file_manager_file_source_metadata','corpus_id','SELECT'),
      ('public.file_manager_file_source_metadata','source_kind','SELECT'),
      ('public.file_manager_file_source_metadata','title','SELECT'),
      ('public.file_manager_file_source_metadata','author','SELECT'),
      ('public.file_manager_file_source_metadata','authored_at','SELECT'),
      ('public.file_manager_file_source_metadata','department','SELECT'),
      ('public.file_manager_file_source_metadata','document_type','SELECT'),
      ('public.file_manager_file_source_metadata','source_updated_at','SELECT'),
      ('public.file_manager_file_source_metadata','content_checksum','SELECT'),
      ('public.official_projection_outbox','event_id','SELECT'),
      ('public.official_projection_outbox','resource_type','SELECT'),
      ('public.official_projection_outbox','resource_id','SELECT'),
      ('public.official_projection_outbox','source_revision','SELECT'),
      ('public.official_projection_outbox','payload_digest','SELECT'),
      ('public.official_projection_receipts','event_id','SELECT'),
      ('public.official_projection_receipts','resource_type','SELECT'),
      ('public.official_projection_receipts','resource_id','SELECT'),
      ('public.official_projection_receipts','source_revision','SELECT'),
      ('public.official_projection_receipts','payload_digest','SELECT'),
      ('public.official_projection_receipts','status','SELECT'),
      ('public.official_projection_receipts','core_event_sequence','SELECT'),
      ('public.retrieval_projection_events','event_sequence','SELECT'),
      ('public.retrieval_projection_events','resource_type','SELECT'),
      ('public.retrieval_projection_events','resource_id','SELECT'),
      ('public.retrieval_projection_events','projection_version','SELECT'),
      ('public.retrieval_projection_events','retrieval_partition_id','SELECT'),
      ('public.retrieval_projection_events','change_kind','SELECT'),
      ('public.retrieval_projection_events','desired_state','SELECT'),
      ('public.retrieval_projection_events','content_checksum','SELECT'),
      ('public.retrieval_projection_events','visibility_checksum','SELECT'),
      ('public.retrieval_projection_heads','resource_type','SELECT'),
      ('public.retrieval_projection_heads','resource_id','SELECT'),
      ('public.retrieval_projection_heads','projection_version','SELECT'),
      ('public.retrieval_projection_heads','retrieval_partition_id','SELECT'),
      ('public.retrieval_projection_heads','desired_state','SELECT'),
      ('public.retrieval_projection_heads','content_checksum','SELECT'),
      ('public.retrieval_projection_heads','visibility_checksum','SELECT'),
      ('public.official_writer_principals','role_oid','SELECT'),
      ('public.official_writer_principals','role_name','SELECT'),
      ('public.retrieval_projection_generations','id','SELECT'),
      ('public.retrieval_projection_generations','backend','SELECT'),
      ('public.retrieval_projection_generations','generation_key','SELECT'),
      ('public.retrieval_projection_generations','physical_name','SELECT'),
      ('public.retrieval_projection_generations','schema_version','SELECT'),
      ('public.retrieval_projection_generations','state','SELECT'),
      ('public.retrieval_partitions','id','SELECT'),
      ('public.retrieval_partitions','source_namespace','SELECT'),
      ('public.retrieval_partitions','candidate_scope_kind','SELECT'),
      ('public.retrieval_partitions','candidate_user_id','SELECT'),
      ('public.retrieval_partitions','state','SELECT'),
      ('public.retrieval_partitions','metadata_version','SELECT'),
      ('public.core_file_materialization_operations','operation_id','SELECT'),
      ('public.core_file_materialization_operations','event_sequence','SELECT'),
      ('public.core_file_materialization_operations','resource_type','SELECT'),
      ('public.core_file_materialization_operations','resource_id','SELECT'),
      ('public.core_file_materialization_operations','projection_version','SELECT'),
      ('public.core_file_materialization_operations','retrieval_partition_id','SELECT'),
      ('public.core_file_materialization_operations','partition_metadata_version','SELECT'),
      ('public.core_file_materialization_operations','change_kind','SELECT'),
      ('public.core_file_materialization_operations','desired_state','SELECT'),
      ('public.core_file_materialization_operations','content_checksum','SELECT'),
      ('public.core_file_materialization_operations','visibility_checksum','SELECT'),
      ('public.core_file_materialization_operations','source_event_id','SELECT'),
      ('public.core_file_materialization_operations','source_revision','SELECT'),
      ('public.core_file_materialization_operations','source_payload_digest','SELECT'),
      ('public.core_file_materialization_operations','source_extracted_at','SELECT'),
      ('public.core_file_materialization_operations','keyword_generation_id','SELECT'),
      ('public.core_file_materialization_operations','vector_generation_id','SELECT'),
      ('public.core_file_materialization_operations','generation_key','SELECT'),
      ('public.core_file_materialization_operations','keyword_physical_name','SELECT'),
      ('public.core_file_materialization_operations','vector_physical_name','SELECT'),
      ('public.core_file_materialization_operations','keyword_schema_version','SELECT'),
      ('public.core_file_materialization_operations','vector_schema_version','SELECT'),
      ('public.core_file_materialization_operations','issuer_role_oid','SELECT'),
      ('public.core_file_materialization_operations','issuer_role_name','SELECT'),
      ('public.core_file_materialization_operations','armed_xact_id','SELECT'),
      ('public.core_file_materialization_operations','header_digest','SELECT'),
      ('public.core_file_materialization_operations','state','SELECT'),
      ('public.core_file_materialization_operations','created_at','SELECT'),
      ('public.core_file_materialization_operations','completed_at','SELECT'),
      ('public.search_index_jobs','id','SELECT'),
      ('public.search_index_jobs','resource_type','SELECT'),
      ('public.search_index_jobs','entity_type','SELECT'),
      ('public.search_index_jobs','entity_id','SELECT'),
      ('public.search_index_jobs','projection_version','SELECT'),
      ('public.search_index_jobs','projection_event_sequence','SELECT'),
      ('public.search_index_jobs','retrieval_partition_id','SELECT'),
      ('public.search_index_jobs','desired_state','SELECT'),
      ('public.search_index_jobs','operation','SELECT'),
      ('public.search_index_jobs','status','SELECT'),
      ('public.search_index_jobs','attempts','SELECT'),
      ('public.rag_sync_jobs','id','SELECT'),
      ('public.rag_sync_jobs','resource_type','SELECT'),
      ('public.rag_sync_jobs','resource_id','SELECT'),
      ('public.rag_sync_jobs','projection_version','SELECT'),
      ('public.rag_sync_jobs','projection_event_sequence','SELECT'),
      ('public.rag_sync_jobs','retrieval_partition_id','SELECT'),
      ('public.rag_sync_jobs','desired_state','SELECT'),
      ('public.rag_sync_jobs','operation','SELECT'),
      ('public.rag_sync_jobs','status','SELECT'),
      ('public.rag_sync_jobs','attempts','SELECT'),
      ('public.core_file_materialization_operations','operation_id','INSERT'),
      ('public.core_file_materialization_operations','event_sequence','INSERT'),
      ('public.core_file_materialization_operations','resource_type','INSERT'),
      ('public.core_file_materialization_operations','resource_id','INSERT'),
      ('public.core_file_materialization_operations','projection_version','INSERT'),
      ('public.core_file_materialization_operations','retrieval_partition_id','INSERT'),
      ('public.core_file_materialization_operations','partition_metadata_version','INSERT'),
      ('public.core_file_materialization_operations','change_kind','INSERT'),
      ('public.core_file_materialization_operations','desired_state','INSERT'),
      ('public.core_file_materialization_operations','content_checksum','INSERT'),
      ('public.core_file_materialization_operations','visibility_checksum','INSERT'),
      ('public.core_file_materialization_operations','source_event_id','INSERT'),
      ('public.core_file_materialization_operations','source_revision','INSERT'),
      ('public.core_file_materialization_operations','source_payload_digest','INSERT'),
      ('public.core_file_materialization_operations','source_extracted_at','INSERT'),
      ('public.core_file_materialization_operations','keyword_generation_id','INSERT'),
      ('public.core_file_materialization_operations','vector_generation_id','INSERT'),
      ('public.core_file_materialization_operations','generation_key','INSERT'),
      ('public.core_file_materialization_operations','keyword_physical_name','INSERT'),
      ('public.core_file_materialization_operations','vector_physical_name','INSERT'),
      ('public.core_file_materialization_operations','keyword_schema_version','INSERT'),
      ('public.core_file_materialization_operations','vector_schema_version','INSERT'),
      ('public.core_file_materialization_operations','state','UPDATE'),
      ('public.search_index_jobs','status','UPDATE'),
      ('public.search_index_jobs','attempts','UPDATE'),
      ('public.search_index_jobs','last_error','UPDATE'),
      ('public.search_index_jobs','next_retry_at','UPDATE'),
      ('public.search_index_jobs','updated_at','UPDATE'),
      ('public.rag_sync_jobs','status','UPDATE'),
      ('public.rag_sync_jobs','attempts','UPDATE'),
      ('public.rag_sync_jobs','last_error','UPDATE'),
      ('public.rag_sync_jobs','next_retry_at','UPDATE'),
      ('public.rag_sync_jobs','updated_at','UPDATE')
    ) AS required(relation_name,column_name,privilege)
      WHERE NOT pg_catalog.has_column_privilege(session_user,relation_name,column_name,privilege))
  THEN RAISE EXCEPTION 'file_materialization_effect_authority_invalid' USING ERRCODE='55000'; END IF;

  IF TG_OP='UPDATE' THEN
    IF OLD.state<>'armed' OR NEW.state<>'complete'
      OR (to_jsonb(NEW)-ARRAY['state','completed_at']) IS DISTINCT FROM
         (to_jsonb(OLD)-ARRAY['state','completed_at'])
      OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
      OR OLD.armed_xact_id=pg_catalog.pg_current_xact_id()::text
      OR OLD.issuer_role_oid<>actor.oid::bigint OR OLD.issuer_role_name<>session_user
    THEN RAISE EXCEPTION 'file_materialization_effect_history_immutable' USING ERRCODE='55000'; END IF;
  ELSIF TG_OP='INSERT' THEN
    IF NEW.state<>'armed' OR NEW.completed_at IS NOT NULL THEN
      RAISE EXCEPTION 'file_materialization_effect_transition_invalid' USING ERRCODE='55000';
    END IF;
  ELSE RAISE EXCEPTION 'file_materialization_effect_transition_invalid' USING ERRCODE='55000'; END IF;
  PERFORM public.miy_lock_file_materialization(NEW.event_sequence,NEW.keyword_generation_id,
    NEW.vector_generation_id,NEW.partition_metadata_version);
  SELECT e.event_sequence,e.resource_type,e.resource_id,e.projection_version,e.retrieval_partition_id,
    e.change_kind,e.desired_state,e.content_checksum,e.visibility_checksum INTO STRICT event
    FROM public.retrieval_projection_events e WHERE e.event_sequence=NEW.event_sequence;
  IF ROW(NEW.event_sequence,NEW.resource_type,NEW.resource_id,NEW.projection_version,NEW.retrieval_partition_id,
      NEW.change_kind,NEW.desired_state,NEW.content_checksum,NEW.visibility_checksum) IS DISTINCT FROM
    ROW(event.event_sequence,event.resource_type,event.resource_id,event.projection_version,event.retrieval_partition_id,
      event.change_kind,event.desired_state,event.content_checksum,event.visibility_checksum)
  THEN RAISE EXCEPTION 'file_materialization_effect_header_invalid' USING ERRCODE='55000'; END IF;
  SELECT o.event_id,o.source_revision,o.payload_digest INTO STRICT source
    FROM public.official_projection_outbox o
    WHERE o.resource_type='file_manager_file' AND o.resource_id=NEW.resource_id
    ORDER BY o.source_revision DESC LIMIT 1;
  IF ROW(NEW.source_event_id,NEW.source_revision,NEW.source_payload_digest)
    IS DISTINCT FROM ROW(source.event_id,source.source_revision,source.payload_digest)
  THEN RAISE EXCEPTION 'file_materialization_effect_header_invalid' USING ERRCODE='55000'; END IF;
  SELECT g.id,g.generation_key,g.physical_name,g.schema_version INTO STRICT keyword
    FROM public.retrieval_projection_generations g WHERE g.id=NEW.keyword_generation_id;
  SELECT g.id,g.generation_key,g.physical_name,g.schema_version INTO STRICT vector
    FROM public.retrieval_projection_generations g WHERE g.id=NEW.vector_generation_id;
  IF ROW(NEW.generation_key,NEW.keyword_physical_name,NEW.keyword_schema_version,NEW.vector_physical_name,NEW.vector_schema_version)
    IS DISTINCT FROM ROW(keyword.generation_key,keyword.physical_name,keyword.schema_version,vector.physical_name,vector.schema_version)
    OR vector.generation_key<>keyword.generation_key
  THEN RAISE EXCEPTION 'file_materialization_effect_header_invalid' USING ERRCODE='55000'; END IF;
  IF NEW.desired_state='active' THEN
    SELECT f.extracted_at INTO STRICT stamp FROM public.file_manager_files f WHERE f.id=NEW.resource_id;
    IF NEW.source_extracted_at IS DISTINCT FROM stamp THEN
      RAISE EXCEPTION 'file_materialization_effect_header_invalid' USING ERRCODE='55000';
    END IF;
  ELSIF NEW.source_extracted_at IS NOT NULL THEN
    RAISE EXCEPTION 'file_materialization_effect_header_invalid' USING ERRCODE='55000';
  END IF;
  IF TG_OP='INSERT' THEN
    NEW.issuer_role_oid=actor.oid::bigint;
    NEW.issuer_role_name=session_user;
    NEW.armed_xact_id=pg_catalog.pg_current_xact_id()::text;
    NEW.created_at=pg_catalog.clock_timestamp() AT TIME ZONE 'UTC';
    NEW.header_digest=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
      (to_jsonb(NEW)-ARRAY['state','completed_at','header_digest'])::text,'UTF8')),'hex');
  ELSE NEW.completed_at=greatest(pg_catalog.clock_timestamp() AT TIME ZONE 'UTC',OLD.created_at); END IF;
  RETURN NEW;
EXCEPTION WHEN no_data_found OR too_many_rows THEN
  RAISE EXCEPTION 'file_materialization_effect_header_invalid' USING ERRCODE='55000';
END
"""

_BODY_3 = """
BEGIN
  IF ROW(NEW.id,NEW.backend,NEW.generation_key,NEW.physical_name,NEW.schema_version,NEW.state)
    IS NOT DISTINCT FROM ROW(OLD.id,OLD.backend,OLD.generation_key,OLD.physical_name,OLD.schema_version,OLD.state)
    AND NEW.baseline_event_sequence=OLD.baseline_event_sequence
    AND NEW.replay_event_sequence=OLD.replay_event_sequence THEN RETURN NEW; END IF;
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'file_materialization_effect_requires_read_committed' USING ERRCODE='55000';
  END IF;
  IF EXISTS(SELECT 1 FROM public.core_file_materialization_operations o
    WHERE o.state='armed' AND (o.keyword_generation_id=OLD.id OR o.vector_generation_id=OLD.id))
  THEN RAISE EXCEPTION 'file_materialization_effect_generation_armed' USING ERRCODE='55000'; END IF;
  RETURN NEW;
END
"""


def _guard():
    connection = op.get_bind()
    if connection.connection.driver_connection.autocommit is True:
        raise RuntimeError("file_materialization_effect_requires_transaction")
    if connection.get_isolation_level() != "READ COMMITTED":
        raise RuntimeError("file_materialization_effect_requires_read_committed")
    ownership = connection.execute(
        sa.text(
            "SELECT active_owner,state FROM public.official_runtime_ownership "
            "WHERE scope='official.suite' FOR UPDATE"
        )
    ).one_or_none()
    if ownership is None or ownership[0] != "legacy":
        raise RuntimeError("file_materialization_effect_ownership_invalid")
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
        raise RuntimeError("file_materialization_effect_guard_inventory_invalid")
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
            raise RuntimeError("file_materialization_effect_role_guard_invalid")
    return guard, ownership[1]


def upgrade() -> None:
    _guard()
    op.create_table(
        "core_file_materialization_operations",
        sa.Column("operation_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "event_sequence",
            sa.BigInteger(),
            sa.ForeignKey("retrieval_projection_events.event_sequence", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("projection_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "retrieval_partition_id",
            sa.Uuid(),
            sa.ForeignKey("retrieval_partitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("partition_metadata_version", sa.Integer(), nullable=False),
        sa.Column("change_kind", sa.String(16), nullable=False),
        sa.Column("desired_state", sa.String(16), nullable=False),
        sa.Column("content_checksum", sa.String(128), nullable=True),
        sa.Column("visibility_checksum", sa.String(128), nullable=True),
        sa.Column(
            "source_event_id",
            sa.Uuid(),
            sa.ForeignKey("official_projection_outbox.event_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("source_payload_digest", sa.String(64), nullable=False),
        sa.Column("source_extracted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "keyword_generation_id",
            sa.Uuid(),
            sa.ForeignKey("retrieval_projection_generations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "vector_generation_id",
            sa.Uuid(),
            sa.ForeignKey("retrieval_projection_generations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("generation_key", sa.String(64), nullable=False),
        sa.Column("keyword_physical_name", sa.String(255), nullable=False),
        sa.Column("vector_physical_name", sa.String(255), nullable=False),
        sa.Column("keyword_schema_version", sa.Integer(), nullable=False),
        sa.Column("vector_schema_version", sa.Integer(), nullable=False),
        sa.Column("issuer_role_oid", sa.BigInteger(), nullable=False),
        sa.Column("issuer_role_name", sa.String(63), nullable=False),
        sa.Column("armed_xact_id", sa.String(20), nullable=False),
        sa.Column("header_digest", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default=sa.text("'armed'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "resource_type='file_manager_file' AND length(trim(resource_id))>0",
            name="ck_core_file_materialization_resource",
        ),
        sa.CheckConstraint(
            "event_sequence>0 AND projection_version>0 AND source_revision>0 AND partition_metadata_version>0",
            name="ck_core_file_materialization_versions",
        ),
        sa.CheckConstraint(
            "change_kind IN ('content','visibility','delete','repair') AND desired_state IN ('active','deleted')",
            name="ck_core_file_materialization_event",
        ),
        sa.CheckConstraint(
            "keyword_generation_id<>vector_generation_id AND keyword_schema_version=3 AND vector_schema_version=1",
            name="ck_core_file_materialization_pair",
        ),
        sa.CheckConstraint(
            "source_payload_digest ~ '^[a-f0-9]{64}$' AND header_digest ~ '^[a-f0-9]{64}$' AND armed_xact_id ~ '^[0-9]{1,20}$'",
            name="ck_core_file_materialization_digests",
        ),
        sa.CheckConstraint(
            "(desired_state='active' AND source_extracted_at IS NOT NULL AND content_checksum ~ '^[a-f0-9]{64}$') OR (desired_state='deleted' AND source_extracted_at IS NULL)",
            name="ck_core_file_materialization_result",
        ),
        sa.CheckConstraint(
            "issuer_role_oid>0 AND length(issuer_role_name)>0",
            name="ck_core_file_materialization_issuer",
        ),
        sa.CheckConstraint(
            "(state='armed' AND completed_at IS NULL) OR (state='complete' AND completed_at IS NOT NULL)",
            name="ck_core_file_materialization_state",
        ),
        sa.UniqueConstraint(
            "event_sequence",
            "keyword_generation_id",
            "vector_generation_id",
            name="uq_core_file_materialization_event_pair",
        ),
    )
    for backend in ("keyword", "vector"):
        op.create_index(
            "uq_core_file_materialization_armed_" + backend,
            "core_file_materialization_operations",
            ["resource_id", backend + "_generation_id"],
            unique=True,
            postgresql_where=sa.text("state='armed'"),
        )
        op.create_index(
            "ix_core_file_materialization_" + backend + "_state",
            "core_file_materialization_operations",
            [backend + "_generation_id", "state"],
        )
    op.execute(
        "CREATE FUNCTION public.miy_lock_file_materialization(event_sequence bigint, keyword_generation_id uuid, vector_generation_id uuid, expected_partition_metadata_version integer) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$"
        + _BODY_0
        + "$body$; REVOKE ALL ON FUNCTION public.miy_lock_file_materialization(bigint,uuid,uuid,integer) FROM PUBLIC;"
    )
    op.execute(
        "CREATE FUNCTION public.miy_guard_file_materialization_effect_writer() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$"
        + _BODY_1
        + "$body$; REVOKE ALL ON FUNCTION public.miy_guard_file_materialization_effect_writer() FROM PUBLIC;"
    )
    op.execute(
        "CREATE FUNCTION public.miy_guard_file_materialization_effect_row() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$"
        + _BODY_2
        + "$body$; REVOKE ALL ON FUNCTION public.miy_guard_file_materialization_effect_row() FROM PUBLIC;"
    )
    op.execute(
        "CREATE FUNCTION public.miy_guard_file_materialization_generation() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$"
        + _BODY_3
        + "$body$; REVOKE ALL ON FUNCTION public.miy_guard_file_materialization_generation() FROM PUBLIC;"
    )
    op.execute("""
CREATE TRIGGER miy_file_materialization_effect_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
  ON public.core_file_materialization_operations FOR EACH STATEMENT
  EXECUTE FUNCTION public.miy_guard_file_materialization_effect_writer();
CREATE TRIGGER miy_file_materialization_effect_row BEFORE INSERT OR UPDATE
  ON public.core_file_materialization_operations FOR EACH ROW
  EXECUTE FUNCTION public.miy_guard_file_materialization_effect_row();
CREATE TRIGGER miy_file_materialization_generation BEFORE UPDATE OF id,backend,generation_key,
  physical_name,schema_version,state,baseline_event_sequence,replay_event_sequence
  ON public.retrieval_projection_generations FOR EACH ROW
  EXECUTE FUNCTION public.miy_guard_file_materialization_generation();
    """)


def downgrade() -> None:
    guard, state = _guard()
    if guard == "miy_guard_official_source_writer_by_role" and state != "draining":
        raise RuntimeError("file_materialization_effect_requires_draining")
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM public.core_file_materialization_operations)")
    ):
        raise RuntimeError("file_materialization_effect_history_retirement_required")
    if op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p,
          LATERAL pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
          WHERE p.oid='public.miy_lock_file_materialization(bigint,uuid,uuid,integer)'::regprocedure
            AND a.grantee<>p.proowner AND a.privilege_type='EXECUTE')
    """)
    ):
        raise RuntimeError("file_materialization_effect_requires_explicit_retirement")
    op.execute(
        "DROP TRIGGER miy_file_materialization_generation ON public.retrieval_projection_generations"
    )
    op.drop_table("core_file_materialization_operations")
    for signature in (
        "public.miy_lock_file_materialization(bigint,uuid,uuid,integer)",
        "public.miy_guard_file_materialization_effect_writer()",
        "public.miy_guard_file_materialization_effect_row()",
        "public.miy_guard_file_materialization_generation()",
    ):
        op.execute("DROP FUNCTION " + signature)
