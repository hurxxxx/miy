"""Inactive delegated actor/Whiteboard owner locks; no business DML or cutover."""

from alembic import op
import hashlib
import sqlalchemy as sa

revision = "wb_actor_owner_20261009"
down_revision = "wb_source_writer_20261009"
branch_labels = None
depends_on = None

CAPABILITY = "public.miy_whiteboard_lock_owner_actor(integer,text,text,text,text,text,integer,text,text,text,text,text,text,text)"
SERVICE_CAPABILITY = "public.miy_whiteboard_lock_source_writer(integer,text)"
PRODUCER_ADMISSION = "public.miy_recording_lock_producer(bigint,text,integer,text)"
PRODUCER_BODY_SHA256 = "14f6b158322d8020ec6ebe2a1bfc728ff1f1091351b33ec5f1dd7874cc0d1617"
SERVICE_BODY_SHA256 = "ec03287cc2dc8fbe39858a39c7cc6231a8aa77f772b5137eafd18073c6d3e851"
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
CAPABILITY_BODY = """
DECLARE
  u record; s record; a record; i record; r record; v record; b record;
  g record; policy record; gid text; witness text; board record; gate text;
  decision_time timestamp;
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed'
    OR delegated_digest IS NULL OR delegated_digest !~ '^[a-f0-9]{64}$'
    OR expected_user IS NULL OR expected_source_session IS NULL
    OR expected_installation IS NULL OR expected_binding IS NULL
    OR expected_release IS NULL OR expected_verification IS NULL
    OR expected_execution_artifact IS NULL OR expected_origin IS NULL
    OR expected_environment IS NULL OR requested_board IS NULL
    OR expected_installation_generation IS NULL OR expected_installation_generation < 1
  THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  -- SESSION_USER remains the original LOGIN inside both SECURITY DEFINER calls.
  PERFORM public.miy_whiteboard_lock_source_writer(service_generation,service_artifact);
  -- Candidate order agrees with update; reset/delete have an opposite order.
  -- The caller's SQL budget bounds deadlocks/waits; no decision survives rollback.
  SELECT id,status,login_blocked,must_change_password,primary_organization_unit_id INTO u
    FROM public.users WHERE id=expected_user FOR SHARE;
  IF u.id IS NULL OR u.status<>'active' OR u.login_blocked OR u.must_change_password
  THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  SELECT id,user_id,expires_at,revoked_at,impersonator_user_id INTO s
    FROM public.auth_sessions WHERE id=expected_source_session FOR SHARE;
  IF s.id IS NULL OR s.user_id<>u.id OR s.revoked_at IS NOT NULL
    OR s.impersonator_user_id IS NOT NULL
  THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  SELECT token_hash,installation_id,source_session_id,generation,permissions,expires_at,revoked_at INTO a
    FROM public.independent_app_sessions WHERE token_hash=delegated_digest FOR SHARE;
  IF a.token_hash IS NULL OR a.revoked_at IS NOT NULL
    OR a.source_session_id<>s.id OR a.installation_id<>expected_installation
    OR a.generation<>expected_installation_generation
  THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  SELECT id,app_id,environment,origin,enabled,audience,user_ids,group_ids,
    granted_permissions,release_id,state,generation,runtime_ref INTO i
    FROM public.independent_app_installations WHERE id=expected_installation FOR SHARE;
  IF i.id IS NULL OR NOT i.enabled OR i.state<>'ready' OR i.runtime_ref IS NULL
    OR i.runtime_ref='' OR i.origin<>expected_origin OR i.environment<>expected_environment
    OR i.generation<>expected_installation_generation OR i.release_id IS DISTINCT FROM expected_release
    OR NOT COALESCE(i.granted_permissions::jsonb ? 'identity:read',false)
    OR NOT COALESCE(a.permissions::jsonb ? 'identity:read',false)
  THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  SELECT id,app_id,definition_digest,definition_snapshot,source_revision,artifact,
    verification_id,verified_at INTO r FROM public.independent_app_releases
    WHERE id=expected_release FOR SHARE;
  IF r.id IS NULL OR r.app_id<>i.app_id OR r.verified_at IS NULL
    OR r.verification_id IS DISTINCT FROM expected_verification OR r.artifact<>expected_execution_artifact
    OR r.definition_snapshot->>'ownership' IS DISTINCT FROM 'official'
  THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  SELECT id,app_id,source_revision,definition_digest,artifact_digest,target_environment,checks,revoked_at INTO v
    FROM public.independent_app_build_verifications WHERE id=expected_verification FOR SHARE;
  IF v.id IS NULL OR v.revoked_at IS NOT NULL OR v.target_environment<>i.environment
    OR (v.app_id,v.source_revision,v.definition_digest,v.artifact_digest)
       IS DISTINCT FROM (r.app_id,r.source_revision,r.definition_digest,r.artifact)
    OR json_typeof(v.checks) IS DISTINCT FROM 'object'
  THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  -- Keep JSON lexical numbers: jsonb would normalize 0e0 to integer-looking 0.
  IF NOT EXISTS(SELECT 1 FROM pg_catalog.json_each(v.checks))
    OR EXISTS(SELECT 1 FROM pg_catalog.json_each(v.checks) e
      WHERE json_typeof(e.value)<>'number' OR e.value::text !~ '^[[:space:]]*-?0[[:space:]]*$')
  THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  SELECT id,installation_id,generation,release_id,verification_id,artifact,origin,
    environment,logical_app_ids,revoked_at INTO b
    FROM public.official_app_bindings WHERE id=expected_binding FOR SHARE;
  IF b.id IS NULL OR b.revoked_at IS NOT NULL
    OR (b.installation_id,b.generation,b.release_id,b.verification_id,b.artifact,b.origin,b.environment)
      IS DISTINCT FROM (i.id,i.generation,r.id,v.id,r.artifact,i.origin,i.environment)
    OR NOT COALESCE(b.logical_app_ids::jsonb ? 'whiteboard',false)
  THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  -- Missing company controls deny. Acquire both positive controls in stable order.
  FOR gate IN SELECT DISTINCT x FROM unnest(ARRAY[i.app_id,'whiteboard']) x ORDER BY x LOOP
    PERFORM app_id FROM public.company_app_controls WHERE app_id=gate AND enabled FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  END LOOP;
  IF i.audience<>'all' AND NOT COALESCE(i.user_ids::jsonb ? u.id,false) THEN
    SELECT gr.id INTO gid FROM public.groups gr WHERE gr.active
      AND COALESCE(i.group_ids::jsonb ? gr.id,false)
      AND ((gr.source='hr' AND u.primary_organization_unit_id=gr.id)
        OR (gr.source='local' AND EXISTS(SELECT 1 FROM public.group_members gm
          WHERE gm.group_id=gr.id AND gm.user_id=u.id))) ORDER BY gr.id LIMIT 1;
    SELECT id,source,active INTO g FROM public.groups WHERE id=gid AND active FOR SHARE;
    IF g.id IS NULL THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
    IF g.source='local' THEN
      PERFORM group_id FROM public.group_members WHERE group_id=g.id AND user_id=u.id FOR SHARE;
      IF NOT FOUND THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
    ELSIF g.source<>'hr' OR u.primary_organization_unit_id IS DISTINCT FROM g.id THEN
      RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000';
    END IF;
  END IF;
  SELECT app_id,audience INTO policy FROM public.app_access_policies
    WHERE app_id='whiteboard' AND audience IN ('all','selected') FOR SHARE;
  IF policy.app_id IS NULL THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  IF policy.audience='selected' THEN
    -- Choose one positive witness, never retry another after a lock wait.
    IF EXISTS(SELECT 1 FROM public.user_system_roles WHERE user_id=u.id AND role='platform_admin') THEN
      PERFORM user_id FROM public.user_system_roles WHERE user_id=u.id AND role='platform_admin' FOR SHARE;
      IF NOT FOUND THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
    ELSIF EXISTS(SELECT 1 FROM public.app_user_grants WHERE app_id='whiteboard' AND user_id=u.id) THEN
      PERFORM app_id FROM public.app_user_grants WHERE app_id='whiteboard' AND user_id=u.id FOR SHARE;
      IF NOT FOUND THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
    ELSE
      SELECT gr.id INTO gid FROM public.groups gr WHERE gr.active
        AND EXISTS(SELECT 1 FROM public.app_group_grants ag WHERE ag.app_id='whiteboard' AND ag.group_id=gr.id)
        AND ((gr.source='hr' AND u.primary_organization_unit_id=gr.id)
          OR (gr.source='local' AND EXISTS(SELECT 1 FROM public.group_members gm
            WHERE gm.group_id=gr.id AND gm.user_id=u.id))) ORDER BY gr.id LIMIT 1;
      PERFORM app_id FROM public.app_group_grants WHERE app_id='whiteboard' AND group_id=gid FOR SHARE;
      IF NOT FOUND THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
      SELECT id,source,active INTO g FROM public.groups WHERE id=gid AND active FOR SHARE;
      IF g.id IS NULL THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
      IF g.source='local' THEN
        PERFORM group_id FROM public.group_members WHERE group_id=g.id AND user_id=u.id FOR SHARE;
        IF NOT FOUND THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
      ELSIF g.source<>'hr' OR u.primary_organization_unit_id IS DISTINCT FROM g.id THEN
        RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000';
      END IF;
    END IF;
  END IF;
  SELECT id,owner_id,trashed_at INTO board FROM public.whiteboards
    WHERE id=requested_board FOR SHARE;
  IF board.id IS NULL OR board.owner_id IS DISTINCT FROM u.id OR board.trashed_at IS NOT NULL
  THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
  decision_time := clock_timestamp() AT TIME ZONE 'UTC';
  IF s.expires_at<=decision_time OR a.expires_at<=decision_time
  THEN RAISE EXCEPTION 'whiteboard_actor_writer_refused' USING ERRCODE='55000'; END IF;
END
"""


def _accepted_source_inventory(*, downgrading=False):
    db = op.get_bind()
    if (
        db.connection.driver_connection.autocommit is True
        or db.scalar(sa.text("SHOW transaction_isolation")) != "read committed"
    ):
        raise RuntimeError("whiteboard_actor_requires_read_committed")
    ownership = db.execute(
        sa.text(
            "SELECT active_owner,state FROM public.official_runtime_ownership "
            "WHERE scope='official.suite' FOR UPDATE"
        )
    ).one_or_none()
    if ownership is None or ownership[0] != "legacy":
        raise RuntimeError("whiteboard_actor_ownership_invalid")
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
        raise RuntimeError("whiteboard_actor_guard_inventory_invalid")
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
            raise RuntimeError("whiteboard_actor_role_guard_invalid")
        if downgrading and ownership[1] != "draining":
            raise RuntimeError("whiteboard_actor_requires_draining")
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
        raise RuntimeError("whiteboard_actor_producer_contract_invalid")


def _guard(*, downgrading=False):
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
        raise RuntimeError("whiteboard_actor_service_contract_invalid")


def upgrade() -> None:
    _guard()
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname='miy_whiteboard_lock_owner_actor')"
        )
    ):
        raise RuntimeError("whiteboard_actor_capability_exists")
    op.execute(
        "CREATE FUNCTION public.miy_whiteboard_lock_owner_actor(service_generation integer,service_artifact text,delegated_digest text,expected_user text,expected_source_session text,expected_installation text,expected_installation_generation integer,expected_binding text,expected_release text,expected_verification text,expected_execution_artifact text,expected_origin text,expected_environment text,requested_board text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$"
        + CAPABILITY_BODY
        + "$body$"
    )
    op.execute("REVOKE ALL ON FUNCTION " + CAPABILITY + " FROM PUBLIC")


def downgrade() -> None:
    _guard(downgrading=True)
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
        (SELECT count(*) FROM pg_catalog.pg_proc q WHERE q.pronamespace=p.pronamespace AND q.proname=p.proname)
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang
      WHERE p.oid=pg_catalog.to_regprocedure(:cap)
    """),
            {"cap": CAPABILITY},
        )
        .one_or_none()
    )
    if row is None or tuple(row) != (
        True,
        ["search_path=pg_catalog, pg_temp"],
        hashlib.sha256(CAPABILITY_BODY.encode()).hexdigest(),
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
        raise RuntimeError("whiteboard_actor_capability_contract_invalid")
    op.execute("DROP FUNCTION " + CAPABILITY)
