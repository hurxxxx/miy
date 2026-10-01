"""Initial standalone SQLite schema. Frozen at the PostgreSQL console_0010 shape."""

from alembic import op

revision = "console_sqlite_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE console_host_observations (
        id INTEGER NOT NULL,
        payload JSON NOT NULL,
        checked_at DATETIME NOT NULL,
        PRIMARY KEY (id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE console_owner (
        id INTEGER NOT NULL,
        password_hash TEXT NOT NULL,
        failed_logins INTEGER NOT NULL,
        locked_until DATETIME,
        PRIMARY KEY (id),
        CHECK (id = 1)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE console_service_observations (
        service_id VARCHAR(100) NOT NULL,
        status VARCHAR(40) NOT NULL,
        version VARCHAR(160),
        checked_at DATETIME NOT NULL,
        PRIMARY KEY (service_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE console_sessions (
        token_hash VARCHAR(64) NOT NULL,
        csrf_hash VARCHAR(64) NOT NULL,
        expires_at DATETIME NOT NULL,
        PRIMARY KEY (token_hash)
        )
        """
    )
    op.execute("CREATE INDEX ix_console_sessions_expires_at ON console_sessions (expires_at)")
    op.execute(
        """
        CREATE TABLE console_tasks (
        id VARCHAR(36) NOT NULL,
        title VARCHAR(200) NOT NULL,
        executor VARCHAR(24) DEFAULT 'session' NOT NULL,
        template_snapshot JSON,
        launch_id VARCHAR(36),
        context JSON,
        pinned BOOLEAN NOT NULL,
        thread_id VARCHAR(160),
        stage VARCHAR(24) NOT NULL,
        status VARCHAR(24) NOT NULL,
        root TEXT NOT NULL,
        last_execution_root TEXT,
        previous_execution_root TEXT,
        previous_permissions VARCHAR(24),
        worktree_owned BOOLEAN NOT NULL,
        fingerprint VARCHAR(64),
        model VARCHAR(200),
        effort VARCHAR(40),
        permissions VARCHAR(24) NOT NULL,
        progress JSON,
        runtime_generation VARCHAR(36),
        turn_id VARCHAR(160),
        current_operation_id VARCHAR(36),
        approved_revision INTEGER,
        error_code VARCHAR(80),
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (launch_id),
        UNIQUE (thread_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE console_templates (
        id VARCHAR(36) NOT NULL,
        version INTEGER NOT NULL,
        definition JSON NOT NULL,
        archived BOOLEAN NOT NULL,
        updated_at DATETIME NOT NULL,
        PRIMARY KEY (id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE console_agents (
        thread_id VARCHAR(160) NOT NULL,
        task_id VARCHAR(36) NOT NULL,
        parent_thread_id VARCHAR(160),
        session_id VARCHAR(160),
        name VARCHAR(200) NOT NULL,
        role VARCHAR(100),
        status VARCHAR(40) NOT NULL,
        flags JSON NOT NULL,
        turn_id VARCHAR(160),
        activity VARCHAR(500),
        progress JSON,
        updated_at DATETIME NOT NULL,
        PRIMARY KEY (thread_id),
        FOREIGN KEY(task_id) REFERENCES console_tasks (id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX ix_console_agents_task_id ON console_agents (task_id)")
    op.execute(
        """
        CREATE TABLE console_attachments (
        id VARCHAR(36) NOT NULL,
        task_id VARCHAR(36) NOT NULL,
        name VARCHAR(255) NOT NULL,
        size INTEGER NOT NULL,
        sha256 VARCHAR(64) NOT NULL,
        content BLOB,
        created_at DATETIME NOT NULL,
        deleted_at DATETIME,
        PRIMARY KEY (id),
        FOREIGN KEY(task_id) REFERENCES console_tasks (id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX ix_console_attachments_task_id ON console_attachments (task_id)")
    op.execute(
        """
        CREATE TABLE console_events (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        task_id VARCHAR(36) NOT NULL,
        kind VARCHAR(80) NOT NULL,
        created_at DATETIME NOT NULL,
        FOREIGN KEY(task_id) REFERENCES console_tasks (id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX ix_console_events_task_id_id ON console_events (task_id, id)")
    op.execute(
        """
        CREATE TABLE console_items (
        id INTEGER NOT NULL,
        task_id VARCHAR(36) NOT NULL,
        item_id VARCHAR(200) NOT NULL,
        turn_id VARCHAR(160) NOT NULL,
        payload JSON NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (task_id, item_id),
        FOREIGN KEY(task_id) REFERENCES console_tasks (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE console_operations (
        id VARCHAR(36) NOT NULL,
        task_id VARCHAR(36) NOT NULL,
        kind VARCHAR(24) NOT NULL,
        state VARCHAR(24) NOT NULL,
        digest VARCHAR(64) NOT NULL,
        display_text TEXT,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(task_id) REFERENCES console_tasks (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE console_requests (
        id VARCHAR(36) NOT NULL,
        task_id VARCHAR(36) NOT NULL,
        thread_id VARCHAR(160),
        turn_id VARCHAR(160) NOT NULL,
        rpc_id TEXT NOT NULL,
        generation VARCHAR(36) NOT NULL,
        method VARCHAR(100) NOT NULL,
        payload JSON NOT NULL,
        state VARCHAR(24) NOT NULL,
        answer JSON,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(task_id) REFERENCES console_tasks (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE console_resource_leases (
        task_id VARCHAR(36) NOT NULL,
        resource TEXT NOT NULL,
        "exclusive" BOOLEAN NOT NULL,
        PRIMARY KEY (task_id, resource),
        FOREIGN KEY(task_id) REFERENCES console_tasks (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE console_revisions (
        id INTEGER NOT NULL,
        task_id VARCHAR(36) NOT NULL,
        kind VARCHAR(24) NOT NULL,
        version INTEGER NOT NULL,
        body TEXT NOT NULL,
        source_turn_id VARCHAR(160),
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (task_id, kind, version),
        CONSTRAINT uq_console_revision_kind_turn UNIQUE (task_id, kind, source_turn_id),
        FOREIGN KEY(task_id) REFERENCES console_tasks (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE console_workspace_lease (
        id INTEGER NOT NULL,
        task_id VARCHAR(36),
        PRIMARY KEY (id),
        CHECK (id = 1),
        FOREIGN KEY(task_id) REFERENCES console_tasks (id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE console_message_attachments (
        operation_id VARCHAR(36) NOT NULL,
        attachment_id VARCHAR(36) NOT NULL,
        position INTEGER NOT NULL,
        PRIMARY KEY (operation_id, attachment_id),
        FOREIGN KEY(operation_id) REFERENCES console_operations (id) ON DELETE CASCADE,
        FOREIGN KEY(attachment_id) REFERENCES console_attachments (id)
        )
        """
    )
    op.execute("INSERT INTO console_workspace_lease (id) VALUES (1)")


def downgrade():
    raise RuntimeError("Restore the paired release and database backup")
