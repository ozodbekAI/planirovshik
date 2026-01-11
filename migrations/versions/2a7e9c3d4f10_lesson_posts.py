"""lesson posts

Revision ID: 2a7e9c3d4f10
Revises: 1f2c3d4e5a6b
Create Date: 2026-01-11 00:00:00.000000

"""

from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2a7e9c3d4f10"
down_revision: Union[str, None] = "1f2c3d4e5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Idempotent migration.

    Some environments create tables via SQLAlchemy metadata before running Alembic.
    In that case, `alembic upgrade head` would fail with DuplicateTable.
    """

    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("lesson_posts"):
        op.create_table(
            "lesson_posts",
            sa.Column("post_id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("lesson_id", sa.Integer(), nullable=False),
            sa.Column("post_type", sa.String(length=50), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("file_id", sa.String(length=255), nullable=True),
            sa.Column("caption", sa.Text(), nullable=True),
            sa.Column("delay_seconds", sa.Integer(), server_default="0", nullable=False),
            sa.Column("buttons", sa.JSON(), nullable=True),
            sa.Column("order_number", sa.Integer(), server_default="0", nullable=False),
            sa.Column("survey_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["lesson_id"], ["lessons.lesson_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["survey_id"], ["surveys.survey_id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("post_id"),
        )

    # Ensure indexes exist (safe when table was created outside Alembic)
    existing_indexes = {
        i.get("name")
        for i in (insp.get_indexes("lesson_posts") if insp.has_table("lesson_posts") else [])
    }
    if "idx_lesson_posts_lesson" not in existing_indexes:
        op.create_index("idx_lesson_posts_lesson", "lesson_posts", ["lesson_id"], unique=False)
    if "idx_lesson_posts_order" not in existing_indexes:
        op.create_index(
            "idx_lesson_posts_order",
            "lesson_posts",
            ["lesson_id", "order_number"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("lesson_posts"):
        existing_indexes = {i.get("name") for i in insp.get_indexes("lesson_posts")}
        if "idx_lesson_posts_order" in existing_indexes:
            op.drop_index("idx_lesson_posts_order", table_name="lesson_posts")
        if "idx_lesson_posts_lesson" in existing_indexes:
            op.drop_index("idx_lesson_posts_lesson", table_name="lesson_posts")
        op.drop_table("lesson_posts")
