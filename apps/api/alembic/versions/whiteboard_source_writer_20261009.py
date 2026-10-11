"""Install an inactive caller-bound Whiteboard service SQL capability only."""

from alembic import op
import hashlib
import sqlalchemy as sa

revision = "wb_source_writer_20261009"
down_revision = "file_effect_20261007"
branch_labels = None
depends_on = None

CAPABILITY = "public.miy_whiteboard_lock_source_writer(integer,text)"
PRODUCER_ADMISSION = "public.miy_recording_lock_producer(bigint,text,integer,text)"
PRODUCER_BODY_SHA256 = "14f6b158322d8020ec6ebe2a1bfc728ff1f1091351b33ec5f1dd7874cc0d1617"
# Frozen full source/transport inventory from the accepted preceding migration.
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
CAPABILITY_BODY = "\nDECLARE producer record;\nBEGIN\n  IF current_setting('transaction_isolation') <> 'read committed'\n    OR expected_generation IS NULL OR expected_generation < 1\n    OR expected_artifact IS NULL OR expected_artifact !~ '^sha256:[a-f0-9]{64}$'\n  THEN RAISE EXCEPTION 'whiteboard_source_writer_refused' USING ERRCODE='55000'; END IF;\n  SELECT oid::bigint AS role_oid,rolname::text AS role_name INTO producer\n    FROM pg_catalog.pg_roles WHERE rolname=SESSION_USER\n      AND rolcanlogin AND NOT rolinherit AND NOT rolsuper AND NOT rolcreatedb\n      AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls;\n  IF producer.role_oid IS NULL OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members\n       WHERE member=producer.role_oid OR roleid=producer.role_oid)\n  THEN RAISE EXCEPTION 'whiteboard_source_writer_refused' USING ERRCODE='55000'; END IF;\n  PERFORM public.miy_recording_lock_producer(producer.role_oid,producer.role_name,\n    expected_generation,expected_artifact);\nEND\n"


def _guard(*, downgrading=False):
    db = op.get_bind()
    if (
        db.connection.driver_connection.autocommit is True
        or db.scalar(sa.text("SHOW transaction_isolation")) != "read committed"
    ):
        raise RuntimeError("whiteboard_source_writer_requires_read_committed")
    ownership = db.execute(
        sa.text(
            "SELECT active_owner,state FROM public.official_runtime_ownership "
            "WHERE scope='official.suite' FOR UPDATE"
        )
    ).one_or_none()
    if ownership is None or ownership[0] != "legacy":
        raise RuntimeError("whiteboard_source_writer_ownership_invalid")
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
        raise RuntimeError("whiteboard_source_writer_guard_inventory_invalid")
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
            raise RuntimeError("whiteboard_source_writer_role_guard_invalid")
        if downgrading and ownership[1] != "draining":
            raise RuntimeError("whiteboard_source_writer_requires_draining")
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
        raise RuntimeError("whiteboard_source_writer_producer_contract_invalid")


def upgrade() -> None:
    _guard()
    # An unexpected pre-existing function or overload is not silently adopted.
    if op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n
          ON n.oid=p.pronamespace WHERE n.nspname='public'
            AND p.proname='miy_whiteboard_lock_source_writer')
    """)
    ):
        raise RuntimeError("whiteboard_source_writer_capability_exists")
    op.execute(
        "CREATE FUNCTION public.miy_whiteboard_lock_source_writer("
        "expected_generation integer,expected_artifact text) RETURNS void "
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$"
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
          p.provolatile,p.proisstrict,p.proleakproof,p.proparallel,
          EXISTS(SELECT 1 FROM pg_catalog.aclexplode(
            COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
            WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),
          (SELECT count(*) FROM pg_catalog.pg_proc q WHERE q.pronamespace=p.pronamespace
            AND q.proname=p.proname)
        FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_language l ON l.oid=p.prolang
        WHERE p.oid=pg_catalog.to_regprocedure(:signature)
    """),
            {"signature": CAPABILITY},
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
        False,
        1,
    ):
        raise RuntimeError("whiteboard_source_writer_capability_contract_invalid")
    op.execute("DROP FUNCTION " + CAPABILITY)
