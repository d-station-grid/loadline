"""add detail to weekly reviews

Revision ID: e7b2c4d6f8a1
Revises: c3f1a2b4d5e6
Create Date: 2026-11-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b2c4d6f8a1"
down_revision: str | Sequence[str] | None = "c3f1a2b4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 今ある週次レビューは NULL（画面で読む長めの文はない）
    op.add_column("weekly_reviews", sa.Column("detail", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("weekly_reviews", "detail")
