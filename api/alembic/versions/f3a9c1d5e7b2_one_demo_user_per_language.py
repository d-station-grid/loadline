"""one demo user per language

Revision ID: f3a9c1d5e7b2
Revises: e7b2c4d6f8a1
Create Date: 2026-11-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a9c1d5e7b2"
down_revision: str | Sequence[str] | None = "e7b2c4d6f8a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # デモの利用者を 1 人から、言語ごとに 1 人（英語と日本語）にする
    op.drop_index("uq_users_demo", table_name="users", postgresql_where=sa.text("is_demo"))
    op.create_index(
        "uq_users_demo_language",
        "users",
        ["language"],
        unique=True,
        postgresql_where=sa.text("is_demo"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 日本語のデモの利用者がいると、1 人だけの索引を作れない。先に消す（記録は外部キーで消える）
    op.execute("DELETE FROM users WHERE is_demo AND language <> 'en'")
    op.drop_index("uq_users_demo_language", table_name="users", postgresql_where=sa.text("is_demo"))
    op.create_index(
        "uq_users_demo", "users", ["is_demo"], unique=True, postgresql_where=sa.text("is_demo")
    )
