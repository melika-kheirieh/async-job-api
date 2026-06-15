"""add job lifecycle metadata

Revision ID: 378b67c3a747
Revises: ce2bd16599d5
Create Date: 2026-06-15 15:20:55.134915

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '378b67c3a747'
down_revision: Union[str, Sequence[str], None] = 'ce2bd16599d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "jobs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("jobs", "attempts", server_default=None)

    op.add_column(
        "jobs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('jobs', 'failed_at')
    op.drop_column('jobs', 'completed_at')
    op.drop_column('jobs', 'started_at')
    op.drop_column('jobs', 'attempts')
