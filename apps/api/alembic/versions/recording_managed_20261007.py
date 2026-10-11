"""Inactive fixed Recording command/publication protocol; no runtime role grants."""

from alembic import op
import sqlalchemy as sa

revision = "recording_managed_20261007"
down_revision = "docs_legacy_repair_20261007"
branch_labels = None
depends_on = None

_COMMAND = "recording_stage_commands"
_PUBLICATION = "core_recording_publications"
_LEGACY = "miy_guard_official_source_writer"
_ROLE = "miy_guard_official_source_writer_by_role"
_PREVIOUS_SOURCES = (
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
)


def _guard(tables, *, upgrading=True):
    db = op.get_bind()
    if db.connection.driver_connection.autocommit or db.get_isolation_level() != "READ COMMITTED":
        raise RuntimeError("recording_managed_requires_read_committed")
    owner = db.execute(
        sa.text(
            "SELECT active_owner,state FROM public.official_runtime_ownership WHERE scope='official.suite' FOR UPDATE"
        )
    ).one_or_none()
    if owner is None or owner[0] != "legacy":
        raise RuntimeError("recording_managed_ownership_invalid")
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
    guards = {r[1] for r in rows}
    if (
        {r[0] for r in rows} != set(tables)
        or len(guards) != 1
        or not guards <= {_LEGACY, _ROLE}
        or any(tuple(r[2:]) != ("public", "O", 62, 1, True) for r in rows)
    ):
        raise RuntimeError("recording_managed_guard_inventory_invalid")
    guard = guards.pop()
    if guard == _ROLE:
        if upgrading and owner[1] != "draining":
            raise RuntimeError("recording_managed_requires_draining")
        contract = db.execute(
            sa.text("""
          SELECT p.prosecdef,p.proconfig,
            EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
          FROM pg_catalog.pg_proc p WHERE p.oid='public.miy_guard_official_source_writer_by_role()'::regprocedure
        """)
        ).one()
        if tuple(contract) != (True, ["search_path=pg_catalog, pg_temp"], False):
            raise RuntimeError("recording_managed_role_guard_invalid")
    return guard


def upgrade():
    guard = _guard(_PREVIOUS_SOURCES)
    op.create_table(
        _COMMAND,
        sa.Column("command_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("recording_id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("retry_ordinal", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column(
            "predecessor_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey(f"{_COMMAND}.command_id", ondelete="RESTRICT"),
        ),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("result_version", sa.Integer()),
        sa.Column("transcript_digest", sa.String(64)),
        sa.Column("summary_digest", sa.String(64)),
        sa.Column("verifier_digest", sa.String(64)),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "writer_scope",
            sa.String(80),
            sa.ForeignKey("official_runtime_ownership.scope"),
            nullable=False,
            server_default="official.suite",
        ),
        sa.Column("producer_generation", sa.Integer(), nullable=False),
        sa.Column("producer_artifact", sa.String(71), nullable=False),
        sa.Column("producer_role_oid", sa.BigInteger(), nullable=False),
        sa.Column("producer_role_name", sa.String(63), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("execution_token", sa.Uuid(as_uuid=False)),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.UniqueConstraint(
            "attempt_id", "stage", "retry_ordinal", name="uq_recording_stage_retry"
        ),
        sa.CheckConstraint("writer_scope='official.suite'", name="ck_recording_stage_scope"),
        sa.CheckConstraint(
            "stage IN ('transcribe','analyze_transcript','verify_transcript_summary','persist_result')",
            name="ck_recording_stage_name",
        ),
        sa.CheckConstraint("retry_ordinal BETWEEN 0 AND 3", name="ck_recording_stage_retry"),
        sa.CheckConstraint(
            "result_version IS NULL OR result_version>=1", name="ck_recording_stage_version"
        ),
        sa.CheckConstraint(
            "state IN ('pending','running','succeeded','retry_scheduled','failed')",
            name="ck_recording_stage_state",
        ),
        sa.CheckConstraint(
            "(state='pending' AND execution_token IS NULL AND started_at IS NULL AND finished_at IS NULL) OR (state='running' AND execution_token IS NOT NULL AND started_at IS NOT NULL AND finished_at IS NULL) OR (state IN ('succeeded','retry_scheduled','failed') AND execution_token IS NOT NULL AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_recording_stage_execution",
        ),
        sa.CheckConstraint("payload_digest ~ '^[a-f0-9]{64}$'", name="ck_recording_stage_digest"),
        sa.CheckConstraint(
            "producer_generation>=1 AND producer_role_oid>0", name="ck_recording_stage_producer"
        ),
        sa.CheckConstraint(
            "producer_artifact ~ '^sha256:[a-f0-9]{64}$'", name="ck_recording_stage_artifact"
        ),
        sa.CheckConstraint(
            "stage<>'persist_result' OR task_id=attempt_id", name="ck_recording_stage_final_id"
        ),
        *(
            sa.CheckConstraint(
                f"{field} IS NULL OR {field} ~ '^[a-f0-9]{{64}}$'",
                name=f"ck_recording_stage_{field}",
            )
            for field in ("transcript_digest", "summary_digest", "verifier_digest")
        ),
    )
    op.create_index("ix_recording_stage_commands_recording_id", _COMMAND, ["recording_id"])
    op.create_index("ix_recording_stage_commands_attempt_id", _COMMAND, ["attempt_id"])
    op.create_index("ix_recording_stage_pending", _COMMAND, ["state", "due_at", "command_id"])
    op.create_table(
        _PUBLICATION,
        sa.Column("publication_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "command_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey(f"{_COMMAND}.command_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("task_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("queue", sa.String(80), nullable=False),
        sa.Column("profile", sa.String(16), nullable=False),
        sa.Column("issuer_role_oid", sa.BigInteger(), nullable=False),
        sa.Column("issuer_role_name", sa.String(63), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("publication_token", sa.Uuid(as_uuid=False)),
        sa.Column("attempted_at", sa.DateTime()),
        sa.Column("observed_at", sa.DateTime()),
        sa.CheckConstraint(
            "queue='miy.official.meeting_transcribe' AND profile='official'",
            name="ck_recording_publication_route",
        ),
        sa.CheckConstraint(
            "state IN ('pending','publishing','acknowledged','unknown','consumed')",
            name="ck_recording_publication_state",
        ),
        sa.CheckConstraint(
            "payload_digest ~ '^[a-f0-9]{64}$'", name="ck_recording_publication_digest"
        ),
        sa.CheckConstraint("issuer_role_oid>0", name="ck_recording_publication_issuer"),
    )
    op.execute(
        f"CREATE TRIGGER miy_official_source_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{_COMMAND} FOR EACH STATEMENT EXECUTE FUNCTION public.{guard}('official.suite')"
    )
    _functions()


def _functions():
    op.execute(r"""
CREATE FUNCTION public.miy_recording_lock_producer(r_oid bigint,r_name text,r_generation integer,r_artifact text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ownership record; principal record;
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'recording_managed_requires_read_committed' USING ERRCODE='55000';
  END IF;
  SELECT active_owner,state,generation,artifact INTO STRICT ownership
    FROM public.official_runtime_ownership WHERE scope='official.suite' FOR SHARE;
  SELECT * INTO principal FROM public.official_writer_principals
    WHERE role_oid=r_oid AND role_name=r_name FOR SHARE;
  IF ownership.active_owner <> 'legacy' OR ownership.state <> 'active'
    OR ownership.generation IS DISTINCT FROM r_generation OR ownership.artifact IS DISTINCT FROM r_artifact
    OR principal.role_oid IS NULL OR principal.revoked_at IS NOT NULL
    OR principal.scope <> 'official.suite' OR principal.owner <> 'legacy'
    OR principal.generation IS DISTINCT FROM r_generation OR principal.artifact IS DISTINCT FROM r_artifact
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=r_oid AND rolname=r_name)
  THEN RAISE EXCEPTION 'recording_managed_source_authority_invalid' USING ERRCODE='55000'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.miy_recording_lock_producer(bigint,text,integer,text) FROM PUBLIC;

CREATE FUNCTION public.miy_recording_check_core() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE actor record;
BEGIN
  SELECT * INTO STRICT actor FROM pg_catalog.pg_roles WHERE rolname=session_user;
  IF current_setting('transaction_isolation') <> 'read committed'
    OR NOT actor.rolcanlogin OR actor.rolsuper OR actor.rolinherit OR actor.rolcreaterole
    OR actor.rolcreatedb OR actor.rolreplication OR actor.rolbypassrls
    OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE member=actor.oid OR roleid=actor.oid)
    OR NOT has_table_privilege(session_user,'public.core_recording_publications','SELECT')
    OR NOT has_table_privilege(session_user,'public.core_recording_publications','INSERT')
    OR NOT has_table_privilege(session_user,'public.core_recording_publications','UPDATE')
    OR NOT has_function_privilege(session_user,'public.miy_recording_publication_admit(uuid,uuid,text)','EXECUTE')
    OR EXISTS(
      SELECT 1 FROM pg_catalog.pg_trigger t WHERE t.tgname='miy_official_source_writer'
      AND (has_table_privilege(session_user,t.tgrelid,'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER')
           OR has_any_column_privilege(session_user,t.tgrelid,'INSERT,UPDATE')))
  THEN RAISE EXCEPTION 'recording_managed_core_authority_invalid' USING ERRCODE='42501'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.miy_recording_check_core() FROM PUBLIC;

CREATE FUNCTION public.miy_recording_command_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE actor record; predecessor public.recording_stage_commands%ROWTYPE; expected_stage text;
BEGIN
  SELECT p.* INTO actor FROM public.official_writer_principals p
    JOIN pg_catalog.pg_roles r ON r.oid=p.role_oid AND r.rolname=p.role_name WHERE r.rolname=session_user;
  IF actor.role_oid IS NULL THEN
    RAISE EXCEPTION 'recording_managed_source_authority_invalid' USING ERRCODE='55000';
  END IF;
  PERFORM public.miy_recording_lock_producer(actor.role_oid,actor.role_name,actor.generation,actor.artifact);
  IF TG_OP='INSERT' THEN
    IF NEW.state<>'pending' OR NEW.execution_token IS NOT NULL OR NEW.started_at IS NOT NULL OR NEW.finished_at IS NOT NULL THEN
      RAISE EXCEPTION 'recording_managed_command_transition_invalid' USING ERRCODE='23514'; END IF;
    NEW.producer_role_oid:=actor.role_oid; NEW.producer_role_name:=actor.role_name;
    NEW.producer_generation:=actor.generation; NEW.producer_artifact:=actor.artifact;
    NEW.created_at:=timezone('UTC',clock_timestamp());
    IF NEW.predecessor_id IS NULL THEN
      IF NEW.stage<>'transcribe' OR NEW.retry_ordinal<>0 THEN
        RAISE EXCEPTION 'recording_managed_predecessor_invalid' USING ERRCODE='23514'; END IF;
    ELSE
      SELECT * INTO STRICT predecessor FROM public.recording_stage_commands WHERE command_id=NEW.predecessor_id;
      IF (predecessor.recording_id,predecessor.attempt_id,predecessor.owner_id,predecessor.storage_key,predecessor.producer_generation,predecessor.producer_artifact)
        IS DISTINCT FROM (NEW.recording_id,NEW.attempt_id,NEW.owner_id,NEW.storage_key,NEW.producer_generation,NEW.producer_artifact) THEN
        RAISE EXCEPTION 'recording_managed_predecessor_invalid' USING ERRCODE='23514'; END IF;
      IF NEW.retry_ordinal>0 THEN
        IF predecessor.stage<>NEW.stage OR predecessor.retry_ordinal+1<>NEW.retry_ordinal
          OR predecessor.state<>'retry_scheduled' OR predecessor.task_id<>NEW.task_id THEN
          RAISE EXCEPTION 'recording_managed_predecessor_invalid' USING ERRCODE='23514'; END IF;
      ELSE
        expected_stage:=CASE NEW.stage WHEN 'analyze_transcript' THEN 'transcribe' WHEN 'verify_transcript_summary' THEN 'analyze_transcript' WHEN 'persist_result' THEN 'verify_transcript_summary' ELSE NULL END;
        IF expected_stage IS NULL OR predecessor.stage<>expected_stage OR predecessor.state<>'succeeded' THEN
          RAISE EXCEPTION 'recording_managed_predecessor_invalid' USING ERRCODE='23514'; END IF;
      END IF;
    END IF;
  ELSE
    PERFORM public.miy_recording_lock_producer(OLD.producer_role_oid,OLD.producer_role_name,OLD.producer_generation,OLD.producer_artifact);
    IF (to_jsonb(NEW)-ARRAY['state','execution_token','started_at','finished_at']) IS DISTINCT FROM
       (to_jsonb(OLD)-ARRAY['state','execution_token','started_at','finished_at']) THEN
      RAISE EXCEPTION 'recording_managed_command_identity_immutable' USING ERRCODE='23514'; END IF;
    IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
    IF OLD.state='pending' AND NEW.state='running' AND NEW.execution_token IS NOT NULL
      AND NEW.due_at<=timezone('UTC',clock_timestamp()) THEN
      NEW.started_at:=timezone('UTC',clock_timestamp()); NEW.finished_at:=NULL;
    ELSIF OLD.state='running' AND NEW.state IN ('succeeded','retry_scheduled','failed')
      AND NEW.execution_token IS NOT DISTINCT FROM OLD.execution_token
      AND NEW.started_at IS NOT DISTINCT FROM OLD.started_at THEN
      NEW.finished_at:=timezone('UTC',clock_timestamp());
    ELSE RAISE EXCEPTION 'recording_managed_command_transition_invalid' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.miy_recording_command_guard() FROM PUBLIC;
CREATE TRIGGER miy_recording_command_guard BEFORE INSERT OR UPDATE ON public.recording_stage_commands
  FOR EACH ROW EXECUTE FUNCTION public.miy_recording_command_guard();

CREATE FUNCTION public.miy_recording_keep_history() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
BEGIN RAISE EXCEPTION 'recording_managed_history_retention_required' USING ERRCODE='55000'; END $$;
REVOKE ALL ON FUNCTION public.miy_recording_keep_history() FROM PUBLIC;
CREATE TRIGGER miy_recording_history BEFORE DELETE OR TRUNCATE ON public.recording_stage_commands FOR EACH STATEMENT EXECUTE FUNCTION public.miy_recording_keep_history();
CREATE TRIGGER miy_recording_history BEFORE DELETE OR TRUNCATE ON public.core_recording_publications FOR EACH STATEMENT EXECUTE FUNCTION public.miy_recording_keep_history();

CREATE FUNCTION public.miy_recording_publication_admit(c_id uuid,p_id uuid,expected_payload_digest text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE command public.recording_stage_commands%ROWTYPE; publication public.core_recording_publications%ROWTYPE;
BEGIN
  PERFORM public.miy_recording_check_core();
  SELECT * INTO STRICT command FROM public.recording_stage_commands WHERE command_id=c_id;
  PERFORM public.miy_recording_lock_producer(command.producer_role_oid,command.producer_role_name,command.producer_generation,command.producer_artifact);
  SELECT * INTO STRICT publication FROM public.core_recording_publications WHERE publication_id=p_id FOR UPDATE;
  PERFORM public.miy_recording_check_core();
  IF publication.command_id<>c_id OR publication.payload_digest<>expected_payload_digest
    OR command.payload_digest<>expected_payload_digest OR publication.task_id<>command.task_id
    OR publication.issuer_role_name<>session_user
    OR NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=publication.issuer_role_oid AND rolname=session_user)
  THEN RAISE EXCEPTION 'recording_managed_publication_binding_invalid' USING ERRCODE='23514'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.miy_recording_publication_admit(uuid,uuid,text) FROM PUBLIC;

CREATE FUNCTION public.miy_recording_publication_scope() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
  PERFORM public.miy_recording_check_core();
  PERFORM 1 FROM public.official_runtime_ownership WHERE scope='official.suite' FOR SHARE;
  RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION public.miy_recording_publication_scope() FROM PUBLIC;
CREATE TRIGGER miy_recording_publication_scope BEFORE INSERT OR UPDATE ON public.core_recording_publications
  FOR EACH STATEMENT EXECUTE FUNCTION public.miy_recording_publication_scope();

CREATE FUNCTION public.miy_recording_publication_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE command public.recording_stage_commands%ROWTYPE; actor_oid bigint;
BEGIN
  PERFORM public.miy_recording_check_core();
  SELECT oid::bigint INTO STRICT actor_oid FROM pg_catalog.pg_roles WHERE rolname=session_user;
  SELECT * INTO STRICT command FROM public.recording_stage_commands WHERE command_id=NEW.command_id;
  PERFORM public.miy_recording_lock_producer(command.producer_role_oid,command.producer_role_name,command.producer_generation,command.producer_artifact);
  PERFORM public.miy_recording_check_core();
  IF NEW.task_id<>command.task_id OR NEW.payload_digest<>command.payload_digest THEN
    RAISE EXCEPTION 'recording_managed_publication_binding_invalid' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.state<>'pending' OR NEW.publication_token IS NOT NULL OR NEW.attempted_at IS NOT NULL OR NEW.observed_at IS NOT NULL THEN
      RAISE EXCEPTION 'recording_managed_publication_transition_invalid' USING ERRCODE='23514'; END IF;
    NEW.issuer_role_oid:=actor_oid; NEW.issuer_role_name:=session_user;
    NEW.created_at:=timezone('UTC',clock_timestamp());
  ELSE
    IF OLD.issuer_role_oid<>actor_oid OR OLD.issuer_role_name<>session_user
      OR (to_jsonb(NEW)-ARRAY['state','publication_token','attempted_at','observed_at']) IS DISTINCT FROM
         (to_jsonb(OLD)-ARRAY['state','publication_token','attempted_at','observed_at']) THEN
      RAISE EXCEPTION 'recording_managed_publication_identity_immutable' USING ERRCODE='23514'; END IF;
    IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
    IF OLD.state IN ('pending','unknown') AND NEW.state='publishing'
      AND command.state='pending' AND command.due_at<=timezone('UTC',clock_timestamp())
      AND NEW.publication_token IS NOT NULL AND NEW.publication_token IS DISTINCT FROM OLD.publication_token THEN
      NEW.attempted_at:=timezone('UTC',clock_timestamp()); NEW.observed_at:=NULL;
    ELSIF OLD.state='publishing' AND NEW.state IN ('acknowledged','unknown')
      AND NEW.publication_token IS NOT DISTINCT FROM OLD.publication_token
      AND NEW.attempted_at IS NOT DISTINCT FROM OLD.attempted_at THEN
      NEW.observed_at:=timezone('UTC',clock_timestamp());
    ELSIF OLD.state IN ('publishing','acknowledged','unknown') AND NEW.state='consumed'
      AND command.state IN ('running','succeeded','retry_scheduled','failed')
      AND NEW.publication_token IS NOT DISTINCT FROM OLD.publication_token
      AND NEW.attempted_at IS NOT DISTINCT FROM OLD.attempted_at THEN
      NEW.observed_at:=timezone('UTC',clock_timestamp());
    ELSE RAISE EXCEPTION 'recording_managed_publication_transition_invalid' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.miy_recording_publication_guard() FROM PUBLIC;
CREATE TRIGGER miy_recording_publication_guard BEFORE INSERT OR UPDATE ON public.core_recording_publications
  FOR EACH ROW EXECUTE FUNCTION public.miy_recording_publication_guard();
""")


def downgrade():
    guard = _guard((*_PREVIOUS_SOURCES, _COMMAND), upgrading=False)
    if guard == _ROLE:
        raise RuntimeError("recording_managed_requires_explicit_retirement")
    db = op.get_bind()
    db.exec_driver_sql(
        f"LOCK TABLE public.{_COMMAND},public.{_PUBLICATION} IN ACCESS EXCLUSIVE MODE"
    )
    if db.execute(
        sa.text(
            f"SELECT EXISTS(SELECT 1 FROM public.{_COMMAND}) OR EXISTS(SELECT 1 FROM public.{_PUBLICATION})"
        )
    ).scalar():
        raise RuntimeError("recording_managed_history_retention_required")
    op.drop_table(_PUBLICATION)
    op.drop_table(_COMMAND)
    for signature in (
        "miy_recording_publication_guard()",
        "miy_recording_publication_scope()",
        "miy_recording_publication_admit(uuid,uuid,text)",
        "miy_recording_command_guard()",
        "miy_recording_check_core()",
        "miy_recording_lock_producer(bigint,text,integer,text)",
        "miy_recording_keep_history()",
    ):
        op.execute(f"DROP FUNCTION public.{signature}")
