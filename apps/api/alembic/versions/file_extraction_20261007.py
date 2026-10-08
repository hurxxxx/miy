"""Fixed Source extraction transport; no runtime/role/provider activation."""

from alembic import op
import sqlalchemy as sa

revision = "file_extraction_20261007"
down_revision = "official_partition_20261007"
branch_labels = None
depends_on = None

# Frozen original88+2; new transport is deliberately outside that inventory.
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
        raise RuntimeError("file_extraction_requires_transaction")
    if connection.get_isolation_level() != "READ COMMITTED":
        raise RuntimeError("file_extraction_requires_read_committed")
    ownership = connection.execute(
        sa.text(
            "SELECT active_owner,state FROM public.official_runtime_ownership "
            "WHERE scope='official.suite' FOR UPDATE"
        )
    ).one_or_none()
    if ownership is None or ownership[0] != "legacy":
        raise RuntimeError("file_extraction_ownership_invalid")
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
        raise RuntimeError("file_extraction_guard_inventory_invalid")
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
            raise RuntimeError("file_extraction_role_guard_invalid")
    return guard, ownership[1]


def upgrade() -> None:
    guard, state = _guard()
    if guard == "miy_guard_official_source_writer_by_role" and state != "draining":
        raise RuntimeError("file_extraction_requires_draining")
    op.execute("""
CREATE TABLE public.file_extraction_requests (
 request_id uuid PRIMARY KEY, result_id uuid NOT NULL, event_id uuid NOT NULL,
 source_scope varchar(80) NOT NULL DEFAULT 'official.suite',
 file_id varchar(36) NOT NULL, actor_user_id varchar(36) NOT NULL,
 execution_ref varchar(80) NOT NULL, parser_policy varchar(80) NOT NULL,
 request_payload text NOT NULL, request_digest varchar(64) NOT NULL,
 input_fingerprint varchar(64) NOT NULL,
 producer_role_oid bigint NOT NULL, producer_role_name varchar(63) NOT NULL,
 producer_generation integer NOT NULL, producer_artifact varchar(71),
 state varchar(16) NOT NULL, claim_token uuid, input_sha256 varchar(64),
 input_byte_count integer, hold_reason varchar(32), result_digest varchar(64),
 error_code varchar(120), created_at timestamp NOT NULL, claimed_at timestamp,
 input_bound_at timestamp, completed_at timestamp,
 CONSTRAINT fk_file_extraction_source_scope FOREIGN KEY(source_scope) REFERENCES public.official_runtime_ownership(scope),
 CONSTRAINT uq_file_extraction_result UNIQUE(result_id),
 CONSTRAINT uq_file_extraction_event UNIQUE(event_id),
 CONSTRAINT uq_file_extraction_input UNIQUE(file_id,input_fingerprint,parser_policy),
 CONSTRAINT ck_file_extraction_scope CHECK(source_scope='official.suite'),
 CONSTRAINT ck_file_extraction_state CHECK(state IN ('prepared','claimed','input_bound','ready','unsupported','failed')),
 CONSTRAINT ck_file_extraction_payload CHECK(octet_length(request_payload)<=8192),
 CONSTRAINT ck_file_extraction_digests CHECK(request_digest ~ '^[a-f0-9]{64}$' AND input_fingerprint ~ '^[a-f0-9]{64}$'),
 CONSTRAINT ck_file_extraction_raw_sha CHECK(input_sha256 IS NULL OR input_sha256 ~ '^[a-f0-9]{64}$'),
 CONSTRAINT ck_file_extraction_result_sha CHECK(result_digest IS NULL OR result_digest ~ '^[a-f0-9]{64}$'),
 CONSTRAINT ck_file_extraction_bytes CHECK(input_byte_count IS NULL OR input_byte_count BETWEEN 0 AND 10485760),
 CONSTRAINT ck_file_extraction_hold CHECK(hold_reason IS NULL OR hold_reason='ocr_required'),
 CONSTRAINT ck_file_extraction_producer CHECK(producer_role_oid>0 AND producer_generation>=1)
);
CREATE TRIGGER miy_file_extraction_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
 ON public.file_extraction_requests FOR EACH STATEMENT
 EXECUTE FUNCTION public.miy_guard_official_source_writer_by_role('official.suite');
""")
    _functions()


def _functions():
    op.execute(r"""

CREATE FUNCTION public.miy_file_extraction_result_digest(r_id uuid,outcome text) RETURNS text
LANGUAGE sql SECURITY INVOKER SET search_path=pg_catalog,pg_temp AS $body$
 SELECT pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
  pg_catalog.jsonb_build_object(
   'protocol_version',1,'request_id',r.request_id,'result_id',r.result_id,'event_id',r.event_id,
   'request_digest',r.request_digest,'input_fingerprint',r.input_fingerprint,
   'claim_token',r.claim_token,'input_sha256',r.input_sha256,'input_byte_count',r.input_byte_count,
   'actor_user_id',r.actor_user_id,'execution_ref',r.execution_ref,'outcome',outcome,
   'artifact',pg_catalog.jsonb_build_object('file_id',f.id,'status',f.extraction_status,
    'checksum',f.extraction_content_checksum,'text',f.extraction_text,
    'blocks',f.extraction_blocks,'metadata',f.extraction_metadata,
    'error_code',f.extraction_error_code,'extracted_at',f.extracted_at,'updated_at',f.updated_at),
   'intent',CASE WHEN e.event_id IS NULL THEN NULL ELSE pg_catalog.jsonb_build_object(
    'event_id',e.event_id,'resource_type',e.resource_type,'resource_id',e.resource_id,
    'source_revision',e.source_revision,'payload_digest',e.payload_digest,
    'producer_oid',e.producer_role_oid,'producer_generation',e.producer_generation,
    'producer_artifact',e.producer_artifact) END
  )::text,'UTF8')),'hex')
 FROM public.file_extraction_requests r JOIN public.file_manager_files f ON f.id=r.file_id
 LEFT JOIN public.official_projection_outbox e ON e.event_id=r.event_id WHERE r.request_id=r_id;
$body$;
REVOKE ALL ON FUNCTION public.miy_file_extraction_result_digest(uuid,text) FROM PUBLIC;


CREATE FUNCTION public.miy_file_extraction_admit(r_id uuid DEFAULT NULL) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$
DECLARE actor record; principal record; command record;
BEGIN
 SELECT * INTO actor FROM pg_catalog.pg_roles WHERE rolname=session_user;
 IF actor.oid IS NULL OR NOT actor.rolcanlogin OR actor.rolsuper OR actor.rolinherit
  OR actor.rolcreatedb OR actor.rolcreaterole OR actor.rolreplication OR actor.rolbypassrls
  OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=actor.oid OR roleid=actor.oid)
 THEN RAISE EXCEPTION 'file_extraction_source_authority_invalid' USING ERRCODE='55000'; END IF;
 SELECT * INTO principal FROM public.official_writer_principals WHERE role_oid=actor.oid AND role_name=session_user;
 IF principal.role_oid IS NULL THEN
  RAISE EXCEPTION 'file_extraction_source_authority_invalid' USING ERRCODE='55000'; END IF;
 PERFORM public.miy_recording_lock_producer(principal.role_oid,principal.role_name,principal.generation,principal.artifact);
 IF r_id IS NOT NULL THEN
  SELECT * INTO command FROM public.file_extraction_requests WHERE request_id=r_id;
  IF command.request_id IS NOT NULL AND
   (command.producer_role_oid,command.producer_role_name,command.producer_generation,command.producer_artifact)
    IS DISTINCT FROM (principal.role_oid,principal.role_name,principal.generation,principal.artifact)
  THEN RAISE EXCEPTION 'file_extraction_source_authority_invalid' USING ERRCODE='55000'; END IF;
 END IF;
END $body$;
REVOKE ALL ON FUNCTION public.miy_file_extraction_admit(uuid) FROM PUBLIC;

CREATE FUNCTION public.miy_file_extraction_request_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$
DECLARE actor record; input jsonb; payload jsonb; file_row record; event_row record; corpus record; pending record; tip record;
BEGIN
 IF TG_TABLE_SCHEMA<>'public' OR TG_TABLE_NAME<>'file_extraction_requests' OR TG_NARGS<>0
  OR current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'file_extraction_contract_invalid' USING ERRCODE='55000'; END IF;
 SELECT r.* INTO actor FROM pg_catalog.pg_roles r WHERE r.rolname=session_user;
 IF actor.oid IS NULL OR NOT actor.rolcanlogin OR actor.rolsuper OR actor.rolinherit
  OR actor.rolcreatedb OR actor.rolcreaterole OR actor.rolreplication OR actor.rolbypassrls
  OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=actor.oid OR roleid=actor.oid)
 THEN RAISE EXCEPTION 'file_extraction_source_authority_invalid' USING ERRCODE='55000'; END IF;
 SELECT p.* INTO actor FROM public.official_writer_principals p
  WHERE p.role_oid=actor.oid AND p.role_name=session_user;
 IF actor.role_oid IS NULL THEN
  RAISE EXCEPTION 'file_extraction_source_authority_invalid' USING ERRCODE='55000'; END IF;
 PERFORM public.miy_recording_lock_producer(actor.role_oid,actor.role_name,actor.generation,actor.artifact);
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'prepared' OR NEW.claim_token IS NOT NULL OR NEW.input_sha256 IS NOT NULL
   OR NEW.input_byte_count IS NOT NULL OR NEW.result_digest IS NOT NULL OR NEW.error_code IS NOT NULL
   OR NEW.hold_reason IS NOT NULL OR NEW.claimed_at IS NOT NULL OR NEW.input_bound_at IS NOT NULL
   OR NEW.completed_at IS NOT NULL OR NEW.request_id=NEW.result_id OR NEW.request_id=NEW.event_id OR NEW.result_id=NEW.event_id
  THEN RAISE EXCEPTION 'file_extraction_transition_invalid' USING ERRCODE='23514'; END IF;
  payload:=NEW.request_payload::jsonb; input:=(payload->>'input_canonical')::jsonb;
  IF (SELECT array_agg(k ORDER BY k) FROM pg_catalog.jsonb_object_keys(payload) k)
    IS DISTINCT FROM ARRAY['actor_user_id','event_id','execution_ref','file_id','input_canonical','parser_policy','protocol_version','request_id','result_id']::text[]
   OR payload->>'protocol_version'<>'1' OR payload->>'request_id' IS DISTINCT FROM NEW.request_id::text
   OR payload->>'result_id' IS DISTINCT FROM NEW.result_id::text OR payload->>'event_id' IS DISTINCT FROM NEW.event_id::text
   OR payload->>'file_id' IS DISTINCT FROM NEW.file_id OR payload->>'actor_user_id' IS DISTINCT FROM NEW.actor_user_id
   OR payload->>'execution_ref' IS DISTINCT FROM NEW.execution_ref OR payload->>'parser_policy' IS DISTINCT FROM NEW.parser_policy
   OR NEW.request_digest IS DISTINCT FROM pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(NEW.request_payload,'UTF8')),'hex')
   OR NEW.input_fingerprint IS DISTINCT FROM pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(payload->>'input_canonical','UTF8')),'hex')
   OR length(NEW.actor_user_id)=0 OR length(NEW.execution_ref)=0 OR NEW.parser_policy<>'files-retrieval-v2/local-only-10m-v1'
  THEN RAISE EXCEPTION 'file_extraction_payload_invalid' USING ERRCODE='23514'; END IF;
  NEW.producer_role_oid:=actor.role_oid; NEW.producer_role_name:=actor.role_name;
  NEW.producer_generation:=actor.generation; NEW.producer_artifact:=actor.artifact;
  NEW.created_at:=timezone('UTC',clock_timestamp());
 ELSE
  IF (NEW.producer_role_oid,NEW.producer_role_name,NEW.producer_generation,NEW.producer_artifact)
    IS DISTINCT FROM (actor.role_oid,actor.role_name,actor.generation,actor.artifact) THEN
   RAISE EXCEPTION 'file_extraction_source_authority_invalid' USING ERRCODE='55000'; END IF;
  IF (to_jsonb(NEW)-ARRAY['state','claim_token','input_sha256','input_byte_count','hold_reason','result_digest','error_code','claimed_at','input_bound_at','completed_at'])
    IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','claim_token','input_sha256','input_byte_count','hold_reason','result_digest','error_code','claimed_at','input_bound_at','completed_at'])
  THEN RAISE EXCEPTION 'file_extraction_identity_immutable' USING ERRCODE='23514'; END IF;
  IF OLD.state IN ('ready','unsupported','failed') THEN
   RAISE EXCEPTION 'file_extraction_terminal_immutable' USING ERRCODE='55000'; END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
  IF OLD.state='prepared' AND NEW.state='claimed' AND NEW.claim_token IS NOT NULL
   AND NEW.input_sha256 IS NULL AND NEW.input_byte_count IS NULL AND NEW.hold_reason IS NULL
   AND NEW.result_digest IS NULL AND NEW.error_code IS NULL AND NEW.input_bound_at IS NULL AND NEW.completed_at IS NULL THEN
   NEW.claimed_at:=timezone('UTC',clock_timestamp());
  ELSIF OLD.state='claimed' AND NEW.state='input_bound'
   AND NEW.claim_token IS NOT DISTINCT FROM OLD.claim_token AND NEW.claimed_at IS NOT DISTINCT FROM OLD.claimed_at
   AND NEW.input_sha256 IS NOT NULL AND NEW.input_byte_count IS NOT NULL AND NEW.hold_reason IS NULL
   AND NEW.result_digest IS NULL AND NEW.error_code IS NULL AND NEW.completed_at IS NULL THEN
   NEW.input_bound_at:=timezone('UTC',clock_timestamp());
  ELSIF OLD.state='input_bound' AND NEW.state='input_bound' AND OLD.hold_reason IS NULL AND NEW.hold_reason='ocr_required'
   AND (to_jsonb(NEW)-'hold_reason') IS NOT DISTINCT FROM (to_jsonb(OLD)-'hold_reason') THEN
   RETURN NEW;
  ELSIF OLD.state='input_bound' AND NEW.state IN ('ready','unsupported','failed') AND OLD.hold_reason IS NULL
   AND NEW.claim_token IS NOT DISTINCT FROM OLD.claim_token AND NEW.claimed_at IS NOT DISTINCT FROM OLD.claimed_at
   AND NEW.input_bound_at IS NOT DISTINCT FROM OLD.input_bound_at AND NEW.input_sha256 IS NOT DISTINCT FROM OLD.input_sha256
   AND NEW.input_byte_count IS NOT DISTINCT FROM OLD.input_byte_count AND NEW.hold_reason IS NULL
   AND NEW.result_digest IS NOT NULL THEN
   NEW.completed_at:=timezone('UTC',clock_timestamp());
  ELSE RAISE EXCEPTION 'file_extraction_transition_invalid' USING ERRCODE='23514'; END IF;
  input:=(NEW.request_payload::jsonb->>'input_canonical')::jsonb;
 END IF;
 SELECT sf.*,sf.xmin AS row_xmin,m.source_version,m.content_checksum AS source_checksum INTO file_row
  FROM public.file_manager_files sf LEFT JOIN public.file_manager_file_source_metadata m ON m.file_id=sf.id WHERE sf.id=NEW.file_id;
 IF file_row.id IS NULL OR file_row.deleted_at IS NOT NULL OR file_row.retrieval_partition_id IS NULL OR file_row.size_bytes NOT BETWEEN 0 AND 10485760
  OR (SELECT array_agg(k ORDER BY k) FROM pg_catalog.jsonb_object_keys(input) k) IS DISTINCT FROM
   ARRAY['content_type','corpus_id','filename','folder_id','owner_id','pending_event_digest','pending_event_id','retrieval_partition_id','size_bytes','source_content_checksum','source_version','storage_key','updated_at','visibility']::text[]
  OR (input->>'storage_key',input->>'filename',input->>'content_type',input->>'owner_id',input->>'visibility',input->>'corpus_id',input->>'folder_id',input->>'retrieval_partition_id',input->>'source_version',input->>'source_content_checksum')
   IS DISTINCT FROM (file_row.storage_key,file_row.filename,file_row.content_type,file_row.owner_id,file_row.visibility,file_row.corpus_id,file_row.folder_id,file_row.retrieval_partition_id::text,file_row.source_version,file_row.source_checksum)
  OR (input->>'size_bytes')::bigint IS DISTINCT FROM file_row.size_bytes
 THEN RAISE EXCEPTION 'file_extraction_input_stale' USING ERRCODE='55000'; END IF;
 SELECT * INTO pending FROM public.official_projection_outbox WHERE event_id=(input->>'pending_event_id')::uuid;
 SELECT * INTO tip FROM public.official_projection_outbox WHERE resource_type='file_manager_file' AND resource_id=NEW.file_id ORDER BY source_revision DESC LIMIT 1;
 IF pending.event_id IS NULL OR pending.payload_digest IS DISTINCT FROM input->>'pending_event_digest'
  OR pending.resource_type<>'file_manager_file' OR pending.resource_id IS DISTINCT FROM NEW.file_id
  OR pending.payload::jsonb->>'retrieval_partition_id' IS DISTINCT FROM file_row.retrieval_partition_id::text
  OR pending.payload::jsonb->>'desired_state' IS DISTINCT FROM 'active'
  OR pending.payload::jsonb->>'operation' IS DISTINCT FROM 'upsert'
  OR pending.payload::jsonb->>'content_checksum' IS NOT NULL
  OR (NEW.state NOT IN ('ready','unsupported') AND tip.event_id IS DISTINCT FROM pending.event_id)
  OR (NEW.state IN ('ready','unsupported') AND tip.event_id IS DISTINCT FROM NEW.event_id)
 THEN RAISE EXCEPTION 'file_extraction_pending_intent_stale' USING ERRCODE='55000'; END IF;
 IF file_row.corpus_id IS NOT NULL THEN
  SELECT c.retrieval_partition_id,c.access_scope_kind INTO corpus FROM public.file_manager_corpora c WHERE c.id=file_row.corpus_id;
  IF corpus.retrieval_partition_id IS DISTINCT FROM file_row.retrieval_partition_id OR corpus.access_scope_kind IS DISTINCT FROM 'company'
  THEN RAISE EXCEPTION 'file_extraction_input_stale' USING ERRCODE='55000'; END IF;
 END IF;
 IF NEW.state NOT IN ('ready','unsupported','failed') THEN
  IF (input->>'updated_at')::timestamp IS DISTINCT FROM file_row.updated_at OR file_row.extraction_status<>'pending' OR file_row.extraction_content_checksum IS NOT NULL
   OR (NEW.state='input_bound' AND NEW.input_byte_count IS DISTINCT FROM file_row.size_bytes)
   OR (NEW.state='input_bound' AND file_row.source_checksum IS NOT NULL AND NEW.input_sha256 IS DISTINCT FROM file_row.source_checksum)
  THEN RAISE EXCEPTION 'file_extraction_input_stale' USING ERRCODE='55000'; END IF;
 ELSE
  IF TG_WHEN='AFTER' AND NOT EXISTS(SELECT 1 FROM public.file_extraction_requests r
    WHERE r.request_id=NEW.request_id AND r.xmin=pg_current_xact_id()::xid) THEN
   RAISE EXCEPTION 'file_extraction_terminal_outer_required' USING ERRCODE='55000'; END IF;
  IF file_row.row_xmin IS DISTINCT FROM pg_current_xact_id()::xid OR file_row.extraction_status IS DISTINCT FROM NEW.state
   OR file_row.extracted_at IS NULL OR (NEW.state='ready' AND (NEW.error_code IS NOT NULL OR file_row.extraction_error_code IS NOT NULL
     OR file_row.extraction_content_checksum IS DISTINCT FROM NEW.input_sha256 OR length(btrim(file_row.extraction_text))=0
     OR file_row.extraction_text IS NULL OR length(file_row.extraction_text)>240000 OR jsonb_typeof(file_row.extraction_blocks::jsonb)<>'array'
     OR jsonb_array_length(file_row.extraction_blocks::jsonb) NOT BETWEEN 1 AND 4096
     OR jsonb_typeof(file_row.extraction_metadata::jsonb)<>'object' OR octet_length(file_row.extraction_metadata::text)>65536
     OR octet_length(jsonb_build_object('text',file_row.extraction_text,'blocks',file_row.extraction_blocks,'metadata',file_row.extraction_metadata)::text)>4194304))
   OR (NEW.state IN ('failed','unsupported') AND (NEW.error_code IS NULL OR NEW.error_code !~ '^[a-z][a-z0-9_.-]{0,119}$'
     OR file_row.extraction_error_code IS DISTINCT FROM NEW.error_code OR file_row.extraction_content_checksum IS NOT NULL
     OR file_row.extraction_text IS NOT NULL OR file_row.extraction_blocks::jsonb IS DISTINCT FROM '[]'::jsonb))
  THEN RAISE EXCEPTION 'file_extraction_result_invalid' USING ERRCODE='23514'; END IF;
  SELECT projection.*,projection.xmin AS row_xmin INTO event_row FROM public.official_projection_outbox projection WHERE projection.event_id=NEW.event_id;
  IF NEW.state='failed' THEN
   IF event_row.event_id IS NOT NULL THEN RAISE EXCEPTION 'file_extraction_result_invalid' USING ERRCODE='23514'; END IF;
  ELSE
   IF event_row.event_id IS NULL OR event_row.source_revision IS DISTINCT FROM pending.source_revision+1 OR event_row.row_xmin IS DISTINCT FROM pg_current_xact_id()::xid
    OR (event_row.resource_type,event_row.resource_id,event_row.producer_role_oid,event_row.producer_role_name,event_row.producer_generation,event_row.producer_artifact)
     IS DISTINCT FROM ('file_manager_file',NEW.file_id,NEW.producer_role_oid,NEW.producer_role_name,NEW.producer_generation,NEW.producer_artifact)
    OR event_row.payload::jsonb->>'retrieval_partition_id' IS DISTINCT FROM file_row.retrieval_partition_id::text
    OR event_row.payload::jsonb->>'desired_state' IS DISTINCT FROM (CASE NEW.state WHEN 'ready' THEN 'active' ELSE 'deleted' END)
    OR event_row.payload::jsonb->>'operation' IS DISTINCT FROM (CASE NEW.state WHEN 'ready' THEN 'upsert' ELSE 'delete' END)
    OR event_row.payload::jsonb->>'content_checksum' IS DISTINCT FROM (CASE NEW.state WHEN 'ready' THEN NEW.input_sha256 ELSE NULL END)
   THEN RAISE EXCEPTION 'file_extraction_intent_invalid' USING ERRCODE='23514'; END IF;
  END IF;
  IF NEW.result_digest IS DISTINCT FROM public.miy_file_extraction_result_digest(NEW.request_id,NEW.state) THEN
   RAISE EXCEPTION 'file_extraction_result_digest_invalid' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION public.miy_file_extraction_request_guard() FROM PUBLIC;
CREATE TRIGGER miy_file_extraction_request BEFORE INSERT OR UPDATE ON public.file_extraction_requests
 FOR EACH ROW EXECUTE FUNCTION public.miy_file_extraction_request_guard();
CREATE CONSTRAINT TRIGGER miy_file_extraction_terminal AFTER UPDATE ON public.file_extraction_requests
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.state IN ('ready','unsupported','failed'))
 EXECUTE FUNCTION public.miy_file_extraction_request_guard();
CREATE FUNCTION public.miy_file_extraction_keep_history() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,pg_temp AS $body$
BEGIN RAISE EXCEPTION 'file_extraction_history_immutable' USING ERRCODE='55000'; END $body$;
REVOKE ALL ON FUNCTION public.miy_file_extraction_keep_history() FROM PUBLIC;
CREATE TRIGGER miy_file_extraction_history BEFORE DELETE OR TRUNCATE ON public.file_extraction_requests
 FOR EACH STATEMENT EXECUTE FUNCTION public.miy_file_extraction_keep_history();

CREATE FUNCTION public.miy_file_extraction_seal_terminal() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$
DECLARE target_file text; target_file_next text; target_corpus text;
BEGIN
 IF TG_TABLE_SCHEMA<>'public' OR TG_NARGS<>0 OR TG_WHEN<>'BEFORE' OR TG_LEVEL<>'ROW' THEN
  RAISE EXCEPTION 'file_extraction_seal_invalid' USING ERRCODE='55000'; END IF;
 IF TG_TABLE_NAME='file_manager_files' AND TG_OP IN ('UPDATE','DELETE') THEN
  target_file:=OLD.id;
 ELSIF TG_TABLE_NAME='official_projection_outbox' AND TG_OP='INSERT' THEN
  IF NEW.resource_type<>'file_manager_file' THEN RETURN NEW; END IF;
  target_file:=NEW.resource_id;
 ELSIF TG_TABLE_NAME='file_manager_file_source_metadata' AND TG_OP IN ('INSERT','UPDATE','DELETE') THEN
  target_file:=CASE WHEN TG_OP='INSERT' THEN NEW.file_id ELSE OLD.file_id END;
  IF TG_OP='UPDATE' THEN target_file_next:=NEW.file_id; END IF;
 ELSIF TG_TABLE_NAME='file_manager_corpora' AND TG_OP IN ('UPDATE','DELETE') THEN
  IF TG_OP='UPDATE' AND (NEW.id,NEW.retrieval_partition_id,NEW.access_scope_kind)
    IS NOT DISTINCT FROM (OLD.id,OLD.retrieval_partition_id,OLD.access_scope_kind) THEN RETURN NEW; END IF;
  target_corpus:=OLD.id;
 ELSE RAISE EXCEPTION 'file_extraction_seal_invalid' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT 1 FROM public.file_extraction_requests r JOIN public.file_manager_files f ON f.id=r.file_id
   WHERE r.state IN ('ready','unsupported','failed') AND r.xmin=pg_current_xact_id()::xid
    AND (r.file_id=target_file OR r.file_id=target_file_next OR f.corpus_id=target_corpus)) THEN
  RAISE EXCEPTION 'file_extraction_terminal_transaction_closed' USING ERRCODE='55000'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION public.miy_file_extraction_seal_terminal() FROM PUBLIC;
CREATE TRIGGER miy_file_extraction_seal_file BEFORE UPDATE OR DELETE ON public.file_manager_files
 FOR EACH ROW EXECUTE FUNCTION public.miy_file_extraction_seal_terminal();
CREATE TRIGGER miy_file_extraction_seal_outbox BEFORE INSERT ON public.official_projection_outbox
 FOR EACH ROW EXECUTE FUNCTION public.miy_file_extraction_seal_terminal();
CREATE TRIGGER miy_file_extraction_seal_metadata BEFORE INSERT OR UPDATE OR DELETE ON public.file_manager_file_source_metadata
 FOR EACH ROW EXECUTE FUNCTION public.miy_file_extraction_seal_terminal();
CREATE TRIGGER miy_file_extraction_seal_corpus BEFORE UPDATE OR DELETE ON public.file_manager_corpora
 FOR EACH ROW EXECUTE FUNCTION public.miy_file_extraction_seal_terminal();

""")


def downgrade() -> None:
    guard, state = _guard()
    if guard == "miy_guard_official_source_writer_by_role" and state != "draining":
        raise RuntimeError("file_extraction_requires_draining")
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM public.file_extraction_requests)")):
        raise RuntimeError("file_extraction_requires_record_retention")
    if connection.scalar(
        sa.text("""
      SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c,
       LATERAL pg_catalog.aclexplode(c.relacl) a WHERE c.oid='public.file_extraction_requests'::regclass
       AND a.grantee<>c.relowner AND a.privilege_type IN ('SELECT','INSERT','UPDATE'))
       OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p,
         LATERAL pg_catalog.aclexplode(p.proacl) a
         WHERE p.oid IN ('public.miy_file_extraction_result_digest(uuid,text)'::regprocedure,'public.miy_file_extraction_admit(uuid)'::regprocedure) AND a.grantee<>p.proowner)
    """)
    ):
        raise RuntimeError("file_extraction_requires_explicit_retirement")
    for table, trigger in (
        ("file_manager_files", "miy_file_extraction_seal_file"),
        ("official_projection_outbox", "miy_file_extraction_seal_outbox"),
        ("file_manager_file_source_metadata", "miy_file_extraction_seal_metadata"),
        ("file_manager_corpora", "miy_file_extraction_seal_corpus"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON public.{table}")
    op.drop_table("file_extraction_requests")
    op.execute("DROP FUNCTION public.miy_file_extraction_request_guard()")
    op.execute("DROP FUNCTION public.miy_file_extraction_admit(uuid)")
    op.execute("DROP FUNCTION public.miy_file_extraction_keep_history()")
    op.execute("DROP FUNCTION public.miy_file_extraction_result_digest(uuid,text)")
    op.execute("DROP FUNCTION public.miy_file_extraction_seal_terminal()")
