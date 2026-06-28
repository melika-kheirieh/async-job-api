"""add canceled job status

Revision ID: 9d9b4e4d7a6f
Revises: 2f7c18962da7
Create Date: 2026-06-28 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9d9b4e4d7a6f"
down_revision: Union[str, Sequence[str], None] = "2f7c18962da7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE jobstatus ADD VALUE IF NOT EXISTS 'CANCELED'")


def downgrade() -> None:
    """Downgrade schema."""
    pass
