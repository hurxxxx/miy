"""One release owner; the explicitly covered sources are a separate contract.

The current suite is one artifact/transaction owner, not one service per app.
Adding a table requires its model, versioned migration and PostgreSQL coverage.
This inventory does not activate the suite or cover its other write surfaces.
"""

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

SUITE_SCOPE = "official.suite"
# Source transports are distinct from the fixed 88 business source tables.
APPEND_ONLY_TRANSPORT_TABLES = ("official_projection_outbox",)
MUTABLE_TRANSPORT_TABLES = ("recording_stage_commands",)
WRITER_TRANSPORT_TABLES = (*APPEND_ONLY_TRANSPORT_TABLES, *MUTABLE_TRANSPORT_TABLES)
WRITER_READ_TABLES = ("core_recording_publications",)
COVERED_SOURCE_TABLES = (
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


class OfficialWriterSource:
    """Fixed source/control integrity and restore ordering, without ORM-only fencing."""

    @declared_attr
    def writer_scope(cls) -> Mapped[str]:
        table = cls.__tablename__
        if table not in COVERED_SOURCE_TABLES:
            raise ValueError("Official writer source must be explicitly catalogued")
        return mapped_column(
            String(80),
            ForeignKey("official_runtime_ownership.scope", name=f"fk_{table}_writer_scope"),
            CheckConstraint(f"writer_scope = '{SUITE_SCOPE}'", name=f"ck_{table}_writer_scope"),
            server_default=SUITE_SCOPE,
            nullable=False,
        )
