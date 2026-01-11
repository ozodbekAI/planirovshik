"""lessons

Revision ID: 1f2c3d4e5a6b
Revises: 0dd2a47388a1
Create Date: 2026-01-11 00:00:00.000000

"""

from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1f2c3d4e5a6b"
down_revision: Union[str, None] = "0dd2a47388a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Idempotent migration.

    Some environments create tables via SQLAlchemy metadata before running Alembic.
    In that case, `alembic upgrade head` would fail with DuplicateTable.
    """

    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("lessons"):
        op.create_table(
            "lessons",
            sa.Column("lesson_id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("post_type", sa.String(length=50), nullable=True),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("file_id", sa.String(length=255), nullable=True),
            sa.Column("caption", sa.Text(), nullable=True),
            sa.Column("buttons", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint("lesson_id"),
        )

    # Ensure index exists (safe when table was created outside Alembic)
    existing_indexes = {i.get("name") for i in (insp.get_indexes("lessons") if insp.has_table("lessons") else [])}
    if "idx_lessons_active" not in existing_indexes:
        op.create_index("idx_lessons_active", "lessons", ["is_active"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("lessons"):
        existing_indexes = {i.get("name") for i in insp.get_indexes("lessons")}
        if "idx_lessons_active" in existing_indexes:
            op.drop_index("idx_lessons_active", table_name="lessons")
        op.drop_table("lessons")
