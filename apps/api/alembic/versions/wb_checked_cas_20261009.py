"""Inactive Core-sealed, same-transaction original-cohort checked Whiteboard CAS."""

from alembic import op
import hashlib
import sqlalchemy as sa

revision = "wb_checked_cas_20261009"
down_revision = "wb_actor_acl_20261009"
branch_labels = None
depends_on = None

ACL_CAPABILITY = "public.miy_whiteboard_lock_edit_actor(integer,text,text,text,text,text,integer,text,text,text,text,text,text,text)"
ACL_BODY_SHA256 = "444fab74ce53c826b764775ba79d65595c301691e8e726a8f9653c9c20a8b070"
OWNER_CAPABILITY = "public.miy_whiteboard_lock_owner_actor(integer,text,text,text,text,text,integer,text,text,text,text,text,text,text)"
OWNER_BODY_SHA256 = "c9cb12f043dd4fb8bd62d60f1112626cf263b2e570c3af931a1ff808c5c52da0"
SERVICE_CAPABILITY = "public.miy_whiteboard_lock_source_writer(integer,text)"
SERVICE_BODY_SHA256 = "ec03287cc2dc8fbe39858a39c7cc6231a8aa77f772b5137eafd18073c6d3e851"
PRODUCER_ADMISSION = "public.miy_recording_lock_producer(bigint,text,integer,text)"
PRODUCER_BODY_SHA256 = "14f6b158322d8020ec6ebe2a1bfc728ff1f1091351b33ec5f1dd7874cc0d1617"
SEAL_CAPABILITY = "public.miy_whiteboard_seal_checked(uuid,bigint,text,integer,text,text,text,text,uuid,bigint,bytea,jsonb,bigint,jsonb)"
SAVE_CAPABILITY = "public.miy_whiteboard_save_checked(uuid,text)"
RESOLVE_CAPABILITY = "public.miy_whiteboard_resolve_checked(uuid,text)"
REVISION_TRIGGER = "public.miy_whiteboard_content_revision()"
IMMUTABLE_TRIGGER = "public.miy_whiteboard_checked_immutable()"
COMPOSITION_EPOCH = "whiteboard_checked_cas_v1"


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


def _accepted_source_inventory(*, downgrading=False):
    db = op.get_bind()
    if (
        db.connection.driver_connection.autocommit is True
        or db.scalar(sa.text("SHOW transaction_isolation")) != "read committed"
    ):
        raise RuntimeError("whiteboard_checked_requires_read_committed")
    ownership = db.execute(
        sa.text(
            "SELECT active_owner,state FROM public.official_runtime_ownership "
            "WHERE scope='official.suite' FOR UPDATE"
        )
    ).one_or_none()
    if ownership is None or ownership[0] != "legacy":
        raise RuntimeError("whiteboard_checked_ownership_invalid")
    rows = db.execute(
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
        len(rows) != len(_SOURCES)
        or {row[0] for row in rows} != set(_SOURCES)
        or len(guards) != 1
        or not guards
        <= {"miy_guard_official_source_writer", "miy_guard_official_source_writer_by_role"}
        or any(tuple(row[2:]) != ("public", "O", 62, 1, True) for row in rows)
    ):
        raise RuntimeError("whiteboard_checked_guard_inventory_invalid")
    if guards == {"miy_guard_official_source_writer_by_role"}:
        row = db.execute(
            sa.text("""
          SELECT p.prosecdef,p.proconfig,EXISTS(SELECT 1 FROM pg_catalog.aclexplode(
            COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
            WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
          FROM pg_catalog.pg_proc p
          WHERE p.oid=pg_catalog.to_regprocedure('public.miy_guard_official_source_writer_by_role()')
        """)
        ).one_or_none()
        if row is None or tuple(row) != (True, ["search_path=pg_catalog, pg_temp"], False):
            raise RuntimeError("whiteboard_checked_role_guard_invalid")
        if downgrading and ownership[1] != "draining":
            raise RuntimeError("whiteboard_checked_requires_draining")
    producer = db.execute(
        sa.text("""
        SELECT p.prosecdef,p.proconfig,
          pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex'),
          pg_catalog.pg_get_function_result(p.oid),p.pronargdefaults,l.lanname,
          p.provolatile,p.proisstrict,p.proleakproof,p.proparallel,
          EXISTS(SELECT 1 FROM pg_catalog.aclexplode(
            COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
            WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),
          (SELECT count(*) FROM pg_catalog.pg_proc q JOIN pg_catalog.pg_namespace n
            ON n.oid=q.pronamespace WHERE n.nspname='public'
              AND q.proname='miy_recording_lock_producer'),
          p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=CURRENT_USER)
        FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang
        WHERE p.oid=pg_catalog.to_regprocedure(:signature)
    """),
        {"signature": PRODUCER_ADMISSION},
    ).one_or_none()
    if producer is None or tuple(producer) != (
        True,
        ["search_path=pg_catalog, pg_temp"],
        PRODUCER_BODY_SHA256,
        "void",
        0,
        "plpgsql",
        "v",
        False,
        False,
        "u",
        False,
        1,
        True,
    ):
        raise RuntimeError("whiteboard_checked_producer_contract_invalid")


def _prior_guard(*, downgrading=False):
    _accepted_source_inventory(downgrading=downgrading)
    db = op.get_bind()
    source = db.execute(
        sa.text("""
      SELECT p.prosecdef,p.proconfig,
        pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex'),
        pg_catalog.pg_get_function_result(p.oid),p.pronargdefaults,l.lanname,
        p.provolatile,p.proisstrict,p.proleakproof,p.proparallel,p.prokind,
        EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
          WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),
        (SELECT count(*) FROM pg_catalog.pg_proc q WHERE q.pronamespace=p.pronamespace AND q.proname=p.proname)
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang
      WHERE p.oid=pg_catalog.to_regprocedure(:cap)
    """),
        {"cap": SERVICE_CAPABILITY},
    ).one_or_none()
    if source is None or tuple(source) != (
        True,
        ["search_path=pg_catalog, pg_temp"],
        SERVICE_BODY_SHA256,
        "void",
        0,
        "plpgsql",
        "v",
        False,
        False,
        "u",
        "f",
        False,
        1,
    ):
        raise RuntimeError("whiteboard_checked_service_contract_invalid")
    owner = db.execute(
        sa.text("""
      SELECT p.prosecdef,p.proconfig,
        pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex'),
        pg_catalog.pg_get_function_result(p.oid),p.pronargdefaults,l.lanname,
        p.provolatile,p.proisstrict,p.proleakproof,p.proparallel,p.prokind,
        EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
          WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),
        (SELECT count(*) FROM pg_catalog.pg_proc q WHERE q.pronamespace=p.pronamespace AND q.proname=p.proname)
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang
      WHERE p.oid=pg_catalog.to_regprocedure(:cap)
    """),
        {"cap": OWNER_CAPABILITY},
    ).one_or_none()
    if owner is None or tuple(owner) != (
        True,
        ["search_path=pg_catalog, pg_temp"],
        OWNER_BODY_SHA256,
        "void",
        0,
        "plpgsql",
        "v",
        False,
        False,
        "u",
        "f",
        False,
        1,
    ):
        raise RuntimeError("whiteboard_checked_owner_contract_invalid")


# Trigger authority is invoker-only. No private role receives column authority to
# choose an incarnation or revision; all existing PostgreSQL writers use it too.
REVISION_BODY = r"""
BEGIN
  IF TG_OP='INSERT' THEN
    IF NEW.content_incarnation_id IS DISTINCT FROM '00000000-0000-0000-0000-000000000000'::uuid
      OR NEW.content_revision IS DISTINCT FROM 0::bigint
    THEN RAISE EXCEPTION 'whiteboard_checked_revision_refused' USING ERRCODE='55000'; END IF;
    NEW.content_incarnation_id := gen_random_uuid();
    NEW.content_revision := 0;
  ELSE
    IF NEW.content_incarnation_id IS DISTINCT FROM OLD.content_incarnation_id
      OR NEW.content_revision IS DISTINCT FROM OLD.content_revision
    THEN RAISE EXCEPTION 'whiteboard_checked_revision_refused' USING ERRCODE='55000'; END IF;
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.whiteboard_id IS DISTINCT FROM OLD.whiteboard_id
      OR NEW.room_key IS DISTINCT FROM OLD.room_key OR NEW.yjs_state IS DISTINCT FROM OLD.yjs_state
      OR NEW.snapshot_scene::jsonb IS DISTINCT FROM OLD.snapshot_scene::jsonb THEN
      IF OLD.content_revision=9223372036854775807 THEN
        RAISE EXCEPTION 'whiteboard_checked_revision_overflow' USING ERRCODE='22003'; END IF;
      NEW.content_revision := OLD.content_revision+1;
      -- Existing writers retain their timestamp contract; checked CAS supplies
      -- its final DB decision time. Revision, not caller time, fences content.
    ELSE
      NEW.updated_at := OLD.updated_at;
    END IF;
  END IF;
  RETURN NEW;
END
"""

IMMUTABLE_BODY = r"""
DECLARE owner_oid oid;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'whiteboard_checked_immutable_refused' USING ERRCODE='55000'; END IF;
  SELECT oid INTO owner_oid FROM pg_roles WHERE rolname=CURRENT_USER;
  IF TG_OP='INSERT' THEN
    IF owner_oid IS DISTINCT FROM (SELECT proowner FROM pg_proc
      WHERE oid=to_regprocedure('public.miy_whiteboard_seal_checked(uuid,bigint,text,integer,text,text,text,text,uuid,bigint,bytea,jsonb,bigint,jsonb)'))
    THEN RAISE EXCEPTION 'whiteboard_checked_immutable_refused' USING ERRCODE='55000'; END IF;
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME<>'whiteboard_checked_attempts'
    OR (to_jsonb(NEW)-ARRAY['state','result_incarnation_id','result_revision','completed_at'])
      IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','result_incarnation_id','result_revision','completed_at'])
    OR OLD.state<>'sealed' OR NEW.completed_at IS NULL THEN
    RAISE EXCEPTION 'whiteboard_checked_immutable_refused' USING ERRCODE='55000'; END IF;
  IF NEW.state='committed' THEN
    IF owner_oid IS DISTINCT FROM (SELECT proowner FROM pg_proc WHERE oid=to_regprocedure('public.miy_whiteboard_save_checked(uuid,text)'))
      OR NEW.result_incarnation_id IS DISTINCT FROM OLD.content_incarnation_id
      OR NEW.result_revision IS NULL OR NEW.result_revision<OLD.base_revision
      OR NEW.result_revision-OLD.base_revision>1 THEN
      RAISE EXCEPTION 'whiteboard_checked_immutable_refused' USING ERRCODE='55000'; END IF;
  ELSIF NEW.state='cancelled_not_committed' THEN
    IF owner_oid IS DISTINCT FROM (SELECT proowner FROM pg_proc WHERE oid=to_regprocedure('public.miy_whiteboard_resolve_checked(uuid,text)'))
      OR NEW.result_incarnation_id IS NOT NULL OR NEW.result_revision IS NOT NULL THEN
      RAISE EXCEPTION 'whiteboard_checked_immutable_refused' USING ERRCODE='55000'; END IF;
  ELSE RAISE EXCEPTION 'whiteboard_checked_immutable_refused' USING ERRCODE='55000'; END IF;
  RETURN NEW;
END
"""

# Repeated explicit caller fence makes each public private-SQL entrypoint safe
# without a separately executable helper or a Python-only principal assumption.
CALLER_FENCE = r"""
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  SELECT oid::bigint,rolname INTO caller FROM pg_roles WHERE rolname=SESSION_USER
    AND rolcanlogin AND NOT rolsuper AND NOT rolinherit AND NOT rolcreaterole
    AND NOT rolcreatedb AND NOT rolreplication AND NOT rolbypassrls;
  IF caller.oid IS NULL OR EXISTS(SELECT 1 FROM pg_auth_members
      WHERE member=caller.oid OR roleid=caller.oid) THEN
    RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
"""

SEAL_BODY = (
    r"""
DECLARE caller record; source record; prior record; c jsonb; item record;
  request_hash text; payload_hash text; decision_time timestamp;
  contribution_keys CONSTANT text[] := ARRAY['delegated_token_digest','actor_user_id','source_session_id','installation_id','installation_generation','binding_id','release_id','verification_id','execution_artifact','origin','environment','database_name','database_oid','server_address','server_port'];
BEGIN
"""
    + CALLER_FENCE
    + r"""
  IF requested_attempt IS NULL OR requested_attempt='00000000-0000-0000-0000-000000000000'::uuid
    OR expected_incarnation IS NULL OR expected_incarnation='00000000-0000-0000-0000-000000000000'::uuid
    OR expected_revision IS NULL OR expected_revision<0 OR requested_cutoff IS NULL OR requested_cutoff<1
    OR requested_board IS NULL OR length(requested_board) NOT BETWEEN 1 AND 36
    OR requested_collab IS NULL OR length(requested_collab) NOT BETWEEN 1 AND 36
    OR requested_room IS NULL OR length(requested_room) NOT BETWEEN 1 AND 128
    OR requested_board ~ '[[:cntrl:]]' OR requested_collab ~ '[[:cntrl:]]' OR requested_room ~ '[[:cntrl:]]'
    OR (requested_snapshot IS NOT NULL AND jsonb_typeof(requested_snapshot)<>'object')
    OR coalesce(octet_length(requested_yjs),0)+coalesce(octet_length(convert_to(requested_snapshot::text,'UTF8')),0)>8388608
    OR jsonb_typeof(requested_contributors) IS DISTINCT FROM 'array'
    OR jsonb_array_length(requested_contributors) NOT BETWEEN 1 AND 128 THEN
    RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  PERFORM public.miy_recording_lock_producer(caller.oid,caller.rolname,service_generation,service_artifact);
  SELECT oid::bigint,rolname INTO source FROM pg_roles
    WHERE oid=expected_source_oid AND rolname=expected_source_name
      AND rolcanlogin AND NOT rolsuper AND NOT rolinherit AND NOT rolcreaterole
      AND NOT rolcreatedb AND NOT rolreplication AND NOT rolbypassrls;
  IF source.oid IS NULL OR source.oid=caller.oid OR EXISTS(SELECT 1 FROM pg_auth_members
    WHERE member=source.oid OR roleid=source.oid) THEN
    RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  PERFORM public.miy_recording_lock_producer(source.oid,source.rolname,service_generation,service_artifact);
  FOR c IN SELECT value FROM jsonb_array_elements(requested_contributors) LOOP
    IF jsonb_typeof(c)<>'object' OR NOT(c ?& contribution_keys)
      OR (c-contribution_keys)<>'{}'::jsonb THEN
      RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
    IF EXISTS(SELECT 1 FROM jsonb_each(c) e WHERE e.key NOT IN ('installation_generation','database_oid','server_port','server_address')
      AND (jsonb_typeof(e.value)<>'string' OR (e.value#>>'{}') ~ '[[:cntrl:]]')) THEN
      RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
    IF (c->>'delegated_token_digest') !~ '^[a-f0-9]{64}$'
      OR EXISTS(SELECT 1 FROM jsonb_each_text(c) e WHERE e.key IN ('actor_user_id','source_session_id','installation_id','binding_id','release_id') AND length(e.value) NOT BETWEEN 1 AND 36)
      OR length(c->>'verification_id') NOT BETWEEN 1 AND 100
      OR length(c->>'execution_artifact') NOT BETWEEN 1 AND 500
      OR length(c->>'origin') NOT BETWEEN 1 AND 300 OR length(c->>'environment') NOT BETWEEN 1 AND 16
      OR length(c->>'database_name') NOT BETWEEN 1 AND 63
      OR (c->'installation_generation')::text !~ '^[1-9][0-9]*$'
      OR (c->'database_oid')::text !~ '^[1-9][0-9]*$'
      OR (c->>'installation_generation')::numeric>2147483647
      OR (c->>'database_oid')::numeric>4294967295
      OR NOT(jsonb_typeof(c->'server_address')='null' OR (jsonb_typeof(c->'server_address')='string' AND length(c->>'server_address') BETWEEN 1 AND 100 AND (c->>'server_address') !~ '[[:cntrl:]]'))
      OR NOT(jsonb_typeof(c->'server_port')='null' OR ((c->'server_port')::text ~ '^[1-9][0-9]*$' AND (c->>'server_port')::numeric<=65535))
      OR c->>'database_name' IS DISTINCT FROM current_database()
      OR (c->>'database_oid')::bigint IS DISTINCT FROM (SELECT oid::bigint FROM pg_database WHERE datname=current_database())
      OR c->>'server_address' IS DISTINCT FROM inet_server_addr()::text
      OR (c->>'server_port')::integer IS DISTINCT FROM inet_server_port() THEN
      RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  END LOOP;
  payload_hash := encode(sha256(convert_to(jsonb_build_object('yjs',encode(requested_yjs,'hex'),'snapshot',requested_snapshot)::text,'UTF8')),'hex');
  request_hash := encode(sha256(convert_to(jsonb_build_object('attempt',requested_attempt,'core_oid',caller.oid,'core_name',caller.rolname,'source_oid',source.oid,'source_name',source.rolname,'generation',service_generation,'artifact',service_artifact,'epoch','whiteboard_checked_cas_v1','board',requested_board,'collab',requested_collab,'room',requested_room,'incarnation',expected_incarnation,'revision',expected_revision,'payload_digest',payload_hash,'cutoff',requested_cutoff,'contributors',requested_contributors)::text,'UTF8')),'hex');
  -- Serialize concurrent first seals as well as exact replay without creating
  -- a writable receipt for an unobserved attempt or leaking content in errors.
  PERFORM pg_advisory_xact_lock(hashtextextended(requested_attempt::text,0));
  SELECT * INTO prior FROM public.whiteboard_checked_attempts WHERE attempt_id=requested_attempt FOR UPDATE;
  IF prior.attempt_id IS NOT NULL THEN
    IF prior.request_digest IS DISTINCT FROM request_hash OR prior.seal_role_oid<>caller.oid OR prior.seal_role_name<>caller.rolname THEN
      RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
    RETURN jsonb_build_object('attempt_id',prior.attempt_id,'request_digest',prior.request_digest,'state',prior.state,'content_incarnation_id',prior.result_incarnation_id,'content_revision',prior.result_revision);
  END IF;
  decision_time := clock_timestamp() AT TIME ZONE 'UTC';
  INSERT INTO public.whiteboard_checked_attempts(attempt_id,request_digest,seal_role_oid,seal_role_name,source_role_oid,source_role_name,service_generation,service_artifact,composition_epoch,whiteboard_id,collab_id,room_key,content_incarnation_id,base_revision,yjs_state,snapshot_scene,payload_digest,cohort_cutoff,contributor_count,state,sealed_at)
    VALUES(requested_attempt,request_hash,caller.oid,caller.rolname,source.oid,source.rolname,service_generation,service_artifact,'whiteboard_checked_cas_v1',requested_board,requested_collab,requested_room,expected_incarnation,expected_revision,requested_yjs,requested_snapshot,payload_hash,requested_cutoff,jsonb_array_length(requested_contributors),'sealed',decision_time);
  FOR item IN SELECT value,ordinality FROM jsonb_array_elements(requested_contributors) WITH ORDINALITY LOOP
    c := item.value;
    INSERT INTO public.whiteboard_checked_contributors(attempt_id,ordinal,delegated_token_digest,actor_user_id,source_session_id,installation_id,installation_generation,binding_id,release_id,verification_id,execution_artifact,origin,environment,database_name,database_oid,server_address,server_port)
      VALUES(requested_attempt,item.ordinality,c->>'delegated_token_digest',c->>'actor_user_id',c->>'source_session_id',c->>'installation_id',(c->>'installation_generation')::integer,c->>'binding_id',c->>'release_id',c->>'verification_id',c->>'execution_artifact',c->>'origin',c->>'environment',c->>'database_name',(c->>'database_oid')::bigint,c->>'server_address',(c->>'server_port')::integer);
  END LOOP;
  RETURN jsonb_build_object('attempt_id',requested_attempt,'request_digest',request_hash,'state','sealed','content_incarnation_id',NULL,'content_revision',NULL);
END
"""
)

SAVE_BODY = (
    r"""
DECLARE caller record; attempt record; contribution record; live record;
  decision_time timestamp; source_expiry timestamp; delegated_expiry timestamp; seen integer:=0;
BEGIN
"""
    + CALLER_FENCE
    + r"""
  IF requested_attempt IS NULL OR expected_digest IS NULL OR expected_digest !~ '^[a-f0-9]{64}$' THEN
    RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  SELECT * INTO attempt FROM public.whiteboard_checked_attempts WHERE attempt_id=requested_attempt FOR UPDATE;
  IF attempt.attempt_id IS NULL OR attempt.request_digest IS DISTINCT FROM expected_digest
    OR attempt.source_role_oid<>caller.oid OR attempt.source_role_name<>caller.rolname
    OR attempt.state<>'sealed' OR attempt.composition_epoch<>'whiteboard_checked_cas_v1' THEN
    RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  FOR contribution IN SELECT * FROM public.whiteboard_checked_contributors WHERE attempt_id=requested_attempt ORDER BY ordinal LOOP
    seen := seen+1;
    IF contribution.ordinal<>seen OR contribution.database_name IS DISTINCT FROM current_database()
      OR contribution.database_oid IS DISTINCT FROM (SELECT oid::bigint FROM pg_database WHERE datname=current_database())
      OR contribution.server_address IS DISTINCT FROM inet_server_addr()::text
      OR contribution.server_port IS DISTINCT FROM inet_server_port() THEN
      RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
    PERFORM public.miy_whiteboard_lock_edit_actor(attempt.service_generation,attempt.service_artifact,contribution.delegated_token_digest,contribution.actor_user_id,contribution.source_session_id,contribution.installation_id,contribution.installation_generation,contribution.binding_id,contribution.release_id,contribution.verification_id,contribution.execution_artifact,contribution.origin,contribution.environment,attempt.whiteboard_id);
  END LOOP;
  IF seen<>attempt.contributor_count OR seen NOT BETWEEN 1 AND 128 THEN
    RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  SELECT id,whiteboard_id,room_key,content_incarnation_id,content_revision,yjs_state,snapshot_scene,updated_at,writer_scope INTO live
    FROM public.whiteboard_collab_documents WHERE id=attempt.collab_id FOR UPDATE;
  IF live.id IS NULL OR live.whiteboard_id IS DISTINCT FROM attempt.whiteboard_id
    OR live.room_key IS DISTINCT FROM attempt.room_key OR live.content_incarnation_id IS DISTINCT FROM attempt.content_incarnation_id
    OR live.content_revision IS DISTINCT FROM attempt.base_revision THEN
    RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  -- All selected ACL rows and every original auth/delegated row are still locked.
  -- One final clock comes after every contributor and the actual CAS row wait.
  decision_time := clock_timestamp() AT TIME ZONE 'UTC';
  FOR contribution IN SELECT * FROM public.whiteboard_checked_contributors WHERE attempt_id=requested_attempt ORDER BY ordinal LOOP
    SELECT expires_at INTO source_expiry FROM public.auth_sessions WHERE id=contribution.source_session_id;
    SELECT expires_at INTO delegated_expiry FROM public.independent_app_sessions WHERE token_hash=contribution.delegated_token_digest;
    IF source_expiry IS NULL OR delegated_expiry IS NULL OR source_expiry<=decision_time OR delegated_expiry<=decision_time THEN
      RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  END LOOP;
  UPDATE public.whiteboard_collab_documents SET yjs_state=attempt.yjs_state,snapshot_scene=attempt.snapshot_scene,updated_at=decision_time,writer_scope='official.suite'
    WHERE id=attempt.collab_id RETURNING content_incarnation_id,content_revision INTO live;
  UPDATE public.whiteboard_checked_attempts SET state='committed',result_incarnation_id=live.content_incarnation_id,result_revision=live.content_revision,completed_at=decision_time WHERE attempt_id=requested_attempt;
  RETURN jsonb_build_object('attempt_id',requested_attempt,'request_digest',expected_digest,'state','committed','content_incarnation_id',live.content_incarnation_id,'content_revision',live.content_revision);
END
"""
)

RESOLVE_BODY = (
    r"""
DECLARE caller record; attempt record;
BEGIN
"""
    + CALLER_FENCE
    + r"""
  IF requested_attempt IS NULL OR expected_digest IS NULL OR expected_digest !~ '^[a-f0-9]{64}$' THEN
    RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  SELECT * INTO attempt FROM public.whiteboard_checked_attempts WHERE attempt_id=requested_attempt FOR UPDATE;
  IF attempt.attempt_id IS NULL OR attempt.request_digest IS DISTINCT FROM expected_digest
    OR attempt.seal_role_oid<>caller.oid OR attempt.seal_role_name<>caller.rolname THEN
    RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  PERFORM public.miy_recording_lock_producer(caller.oid,caller.rolname,attempt.service_generation,attempt.service_artifact);
  IF attempt.state='sealed' THEN
    UPDATE public.whiteboard_checked_attempts SET state='cancelled_not_committed',completed_at=clock_timestamp() AT TIME ZONE 'UTC' WHERE attempt_id=requested_attempt;
    attempt.state := 'cancelled_not_committed';
  ELSIF attempt.state NOT IN ('committed','cancelled_not_committed') THEN
    RAISE EXCEPTION 'whiteboard_checked_writer_refused' USING ERRCODE='55000'; END IF;
  RETURN jsonb_build_object('attempt_id',requested_attempt,'request_digest',expected_digest,'state',attempt.state,'content_incarnation_id',attempt.result_incarnation_id,'content_revision',attempt.result_revision);
END
"""
)

FUNCTIONS = {
    SEAL_CAPABILITY: (SEAL_BODY, "jsonb", True),
    SAVE_CAPABILITY: (SAVE_BODY, "jsonb", True),
    RESOLVE_CAPABILITY: (RESOLVE_BODY, "jsonb", True),
    REVISION_TRIGGER: (REVISION_BODY, "trigger", False),
    IMMUTABLE_TRIGGER: (IMMUTABLE_BODY, "trigger", False),
}


FUNCTION_ARGUMENTS = {
    SEAL_CAPABILITY: [
        "requested_attempt",
        "expected_source_oid",
        "expected_source_name",
        "service_generation",
        "service_artifact",
        "requested_board",
        "requested_collab",
        "requested_room",
        "expected_incarnation",
        "expected_revision",
        "requested_yjs",
        "requested_snapshot",
        "requested_cutoff",
        "requested_contributors",
    ],
    SAVE_CAPABILITY: ["requested_attempt", "expected_digest"],
    RESOLVE_CAPABILITY: ["requested_attempt", "expected_digest"],
    REVISION_TRIGGER: None,
    IMMUTABLE_TRIGGER: None,
}


def _attest_function(signature, body, result, definer):
    row = (
        op.get_bind()
        .execute(
            sa.text("""
      SELECT p.prosecdef,p.proconfig,
        pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex'),
        pg_catalog.pg_get_function_result(p.oid),p.pronargdefaults,l.lanname,
        p.provolatile,p.proisstrict,p.proleakproof,p.proparallel,p.prokind,
        EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
          WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),
        (SELECT count(*) FROM pg_catalog.pg_proc q WHERE q.pronamespace=p.pronamespace AND q.proname=p.proname),p.proargnames,p.proargmodes
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang
      WHERE p.oid=pg_catalog.to_regprocedure(:cap)
    """),
            {"cap": signature},
        )
        .one_or_none()
    )
    if row is None or tuple(row) != (
        definer,
        ["search_path=pg_catalog, pg_temp"],
        hashlib.sha256(body.encode()).hexdigest(),
        result,
        0,
        "plpgsql",
        "v",
        False,
        False,
        "u",
        "f",
        False,
        1,
        FUNCTION_ARGUMENTS[signature],
        None,
    ):
        raise RuntimeError("whiteboard_checked_capability_contract_invalid")


def _guard(*, downgrading=False):
    _prior_guard(downgrading=downgrading)
    if not downgrading and op.get_bind().scalar(
        sa.text("""
      SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_default_acl d
        CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) a
        WHERE d.defaclrole=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=CURRENT_USER)
          AND d.defaclnamespace IN (0,(SELECT oid FROM pg_catalog.pg_namespace WHERE nspname='public'))
          AND d.defaclobjtype IN ('r','f') AND a.grantee NOT IN (0,d.defaclrole))
    """)
    ):
        raise RuntimeError("whiteboard_checked_default_privilege_forbidden")
    # The previous revision's body is independently fixed; unlike new functions
    # this expected value is already a SHA, never discovered from the database.
    row = (
        op.get_bind()
        .execute(
            sa.text("""
      SELECT p.prosecdef,p.proconfig,
        pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex'),
        pg_catalog.pg_get_function_result(p.oid),p.pronargdefaults,l.lanname,p.provolatile,p.proisstrict,p.proleakproof,p.proparallel,p.prokind,
        EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),
        (SELECT count(*) FROM pg_catalog.pg_proc q WHERE q.pronamespace=p.pronamespace AND q.proname=p.proname)
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang WHERE p.oid=pg_catalog.to_regprocedure(:cap)
    """),
            {"cap": ACL_CAPABILITY},
        )
        .one_or_none()
    )
    if row is None or tuple(row) != (
        True,
        ["search_path=pg_catalog, pg_temp"],
        ACL_BODY_SHA256,
        "void",
        0,
        "plpgsql",
        "v",
        False,
        False,
        "u",
        "f",
        False,
        1,
    ):
        raise RuntimeError("whiteboard_checked_actor_contract_invalid")


def upgrade():
    _guard()
    db = op.get_bind()
    names = [signature.split("(")[0].split(".")[1] for signature in FUNCTIONS]
    if db.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname=ANY(:names))"
        ),
        {"names": names},
    ):
        raise RuntimeError("whiteboard_checked_capability_exists")
    op.add_column(
        "whiteboard_collab_documents", sa.Column("content_incarnation_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "whiteboard_collab_documents", sa.Column("content_revision", sa.BigInteger(), nullable=True)
    )
    op.execute(
        "UPDATE public.whiteboard_collab_documents SET content_incarnation_id=pg_catalog.gen_random_uuid(),content_revision=0"
    )
    op.alter_column(
        "whiteboard_collab_documents",
        "content_incarnation_id",
        nullable=False,
        server_default=sa.text("'00000000-0000-0000-0000-000000000000'::uuid"),
    )
    op.alter_column(
        "whiteboard_collab_documents",
        "content_revision",
        nullable=False,
        server_default=sa.text("0"),
    )
    op.create_table(
        "whiteboard_checked_attempts",
        sa.Column("attempt_id", sa.Uuid(), primary_key=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("seal_role_oid", sa.BigInteger(), nullable=False),
        sa.Column("seal_role_name", sa.String(63), nullable=False),
        sa.Column("source_role_oid", sa.BigInteger(), nullable=False),
        sa.Column("source_role_name", sa.String(63), nullable=False),
        sa.Column("service_generation", sa.Integer(), nullable=False),
        sa.Column("service_artifact", sa.String(71), nullable=False),
        sa.Column("composition_epoch", sa.String(64), nullable=False),
        sa.Column("whiteboard_id", sa.String(36), nullable=False),
        sa.Column("collab_id", sa.String(36), nullable=False),
        sa.Column("room_key", sa.String(128), nullable=False),
        sa.Column("content_incarnation_id", sa.Uuid(), nullable=False),
        sa.Column("base_revision", sa.BigInteger(), nullable=False),
        sa.Column("yjs_state", sa.LargeBinary(), nullable=True),
        sa.Column("snapshot_scene", sa.JSON(), nullable=True),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("cohort_cutoff", sa.BigInteger(), nullable=False),
        sa.Column("contributor_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("result_incarnation_id", sa.Uuid(), nullable=True),
        sa.Column("result_revision", sa.BigInteger(), nullable=True),
        sa.Column("sealed_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("base_revision >= 0", name="ck_wb_checked_base_revision"),
        sa.CheckConstraint("cohort_cutoff >= 1", name="ck_wb_checked_cutoff"),
        sa.CheckConstraint(
            "contributor_count BETWEEN 1 AND 128", name="ck_wb_checked_contributors"
        ),
        sa.CheckConstraint(
            "state IN ('sealed','committed','cancelled_not_committed')", name="ck_wb_checked_state"
        ),
    )
    op.create_table(
        "whiteboard_checked_contributors",
        sa.Column(
            "attempt_id",
            sa.Uuid(),
            sa.ForeignKey("whiteboard_checked_attempts.attempt_id"),
            primary_key=True,
        ),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("delegated_token_digest", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("source_session_id", sa.String(36), nullable=False),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("installation_generation", sa.Integer(), nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("verification_id", sa.String(100), nullable=False),
        sa.Column("execution_artifact", sa.String(500), nullable=False),
        sa.Column("origin", sa.String(300), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("database_name", sa.String(63), nullable=False),
        sa.Column("database_oid", sa.BigInteger(), nullable=False),
        sa.Column("server_address", sa.String(100), nullable=True),
        sa.Column("server_port", sa.Integer(), nullable=True),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 128", name="ck_wb_checked_ordinal"),
    )
    definitions = {
        SEAL_CAPABILITY: "requested_attempt uuid,expected_source_oid bigint,expected_source_name text,service_generation integer,service_artifact text,requested_board text,requested_collab text,requested_room text,expected_incarnation uuid,expected_revision bigint,requested_yjs bytea,requested_snapshot jsonb,requested_cutoff bigint,requested_contributors jsonb",
        SAVE_CAPABILITY: "requested_attempt uuid,expected_digest text",
        RESOLVE_CAPABILITY: "requested_attempt uuid,expected_digest text",
        REVISION_TRIGGER: "",
        IMMUTABLE_TRIGGER: "",
    }
    for signature, (body, result, definer) in FUNCTIONS.items():
        name = signature.split("(")[0]
        op.execute(
            f"CREATE FUNCTION {name}({definitions[signature]}) RETURNS {result} LANGUAGE plpgsql SECURITY {'DEFINER' if definer else 'INVOKER'} SET search_path=pg_catalog,pg_temp AS $body$"
            + body
            + "$body$"
        )
        op.execute("REVOKE ALL ON FUNCTION " + signature + " FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER miy_whiteboard_content_revision BEFORE INSERT OR UPDATE ON public.whiteboard_collab_documents FOR EACH ROW EXECUTE FUNCTION public.miy_whiteboard_content_revision()"
    )
    for table in ("whiteboard_checked_attempts", "whiteboard_checked_contributors"):
        op.execute(
            f"CREATE TRIGGER miy_whiteboard_checked_immutable BEFORE INSERT OR UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.miy_whiteboard_checked_immutable()"
        )
        op.execute("REVOKE ALL ON TABLE public." + table + " FROM PUBLIC")


def downgrade():
    _guard(downgrading=True)
    db = op.get_bind()
    # No table is ever silently dropped while it carries immutable intent,
    # unresolved work or historical receipt. Retirement is a later owner action.
    if db.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM public.whiteboard_checked_attempts) OR EXISTS(SELECT 1 FROM public.whiteboard_checked_contributors)"
        )
    ):
        raise RuntimeError("whiteboard_checked_history_requires_retirement")
    for signature, (body, result, definer) in FUNCTIONS.items():
        _attest_function(signature, body, result, definer)
    rows = db.execute(
        sa.text("""
      SELECT c.relname,p.proname,t.tgenabled,t.tgtype,t.tgnargs,
        t.tgattr=''::int2vector,t.tgqual IS NULL,t.tgargs=decode('','hex'),t.tgconstraint=0
      FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
      JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
      WHERE n.nspname='public' AND t.tgname IN ('miy_whiteboard_content_revision','miy_whiteboard_checked_immutable')
    """)
    ).all()
    if set(map(tuple, rows)) != {
        (
            "whiteboard_collab_documents",
            "miy_whiteboard_content_revision",
            "O",
            23,
            0,
            True,
            True,
            True,
            True,
        ),
        (
            "whiteboard_checked_attempts",
            "miy_whiteboard_checked_immutable",
            "O",
            31,
            0,
            True,
            True,
            True,
            True,
        ),
        (
            "whiteboard_checked_contributors",
            "miy_whiteboard_checked_immutable",
            "O",
            31,
            0,
            True,
            True,
            True,
            True,
        ),
    }:
        raise RuntimeError("whiteboard_checked_trigger_contract_invalid")
    op.execute("DROP TRIGGER miy_whiteboard_content_revision ON public.whiteboard_collab_documents")
    op.drop_table("whiteboard_checked_contributors")
    op.drop_table("whiteboard_checked_attempts")
    for signature in FUNCTIONS:
        op.execute("DROP FUNCTION " + signature)
    op.drop_column("whiteboard_collab_documents", "content_revision")
    op.drop_column("whiteboard_collab_documents", "content_incarnation_id")
