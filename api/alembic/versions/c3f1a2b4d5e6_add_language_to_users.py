"""add language to users

Revision ID: c3f1a2b4d5e6
Revises: da6a1efd016a
Create Date: 2026-11-14 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f1a2b4d5e6"
down_revision: str | Sequence[str] | None = "da6a1efd016a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 今いる利用者は英語（server_default）。画面と週次レビューは、これまで英語だけだった
    op.add_column(
        "users", sa.Column("language", sa.String(length=8), server_default="en", nullable=False)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "language")
