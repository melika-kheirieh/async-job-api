"""add jobs status created_at index

Revision ID: 2f7c18962da7
Revises: ed0860b2d07e
Create Date: 2026-06-19 13:01:30.171763

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "2f7c18962da7"
down_revision: Union[str, Sequence[str], None] = "ed0860b2d07e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_jobs_status_created_at_id",
        "jobs",
        ["status", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_jobs_status_created_at_id",
        table_name="jobs",
    )