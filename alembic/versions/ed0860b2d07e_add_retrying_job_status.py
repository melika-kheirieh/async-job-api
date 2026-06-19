"""add retrying job status

Revision ID: ed0860b2d07e
Revises: e3cb8af65806
Create Date: 2026-06-19 07:52:09.481937

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ed0860b2d07e"
down_revision: Union[str, Sequence[str], None] = "e3cb8af65806"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE jobstatus ADD VALUE IF NOT EXISTS 'RETRYING'")


def downgrade() -> None:
    """Downgrade schema."""
    pass