"""Release cleaned temporary origins without deleting installation history."""

from alembic import op
import sqlalchemy as sa

revision = "independent_archive_20261011"
down_revision = "independent_workspaces_20261011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "independent_app_installations", sa.Column("archived_origin", sa.String(300), nullable=True)
    )
    op.alter_column(
        "independent_app_installations", "origin", existing_type=sa.String(300), nullable=True
    )
    op.create_check_constraint(
        "ck_independent_app_origin_lifecycle",
        "independent_app_installations",
        "(state = 'archived' AND environment = 'development' AND NOT enabled "
        "AND origin IS NULL AND archived_origin IS NOT NULL) OR "
        "(state <> 'archived' AND origin IS NOT NULL AND archived_origin IS NULL)",
    )


def downgrade():
    # Restoring a retired origin could collide with its new owner or reopen a
    # historical audience. Code rollback does not require this schema downgrade.
    archived = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM independent_app_installations "
                "WHERE archived_origin IS NOT NULL OR state = 'archived' LIMIT 1"
            )
        )
        .scalar()
    )
    if archived is not None:
        raise RuntimeError("Archived installation history prevents schema downgrade")
    op.drop_constraint(
        "ck_independent_app_origin_lifecycle", "independent_app_installations", type_="check"
    )
    op.alter_column(
        "independent_app_installations", "origin", existing_type=sa.String(300), nullable=False
    )
    op.drop_column("independent_app_installations", "archived_origin")
