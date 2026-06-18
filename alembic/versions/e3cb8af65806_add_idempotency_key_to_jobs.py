"""add idempotency key to jobs

Revision ID: e3cb8af65806
Revises: 378b67c3a747
Create Date: 2026-06-18 11:57:48.181843

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e3cb8af65806"
down_revision: Union[str, Sequence[str], None] = "378b67c3a747"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "jobs",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_jobs_idempotency_key",
        "jobs",
        ["idempotency_key"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_jobs_idempotency_key",
        "jobs",
        type_="unique",
    )
    op.drop_column("jobs", "idempotency_key")