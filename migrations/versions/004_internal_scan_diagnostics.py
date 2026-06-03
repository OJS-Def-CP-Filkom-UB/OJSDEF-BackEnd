"""internal scan diagnostics + force_heartbeat

Revision ID: 004
Revises: 003
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scan_jobs",
        sa.Column("diagnostic_code", sa.String(40), nullable=True))
    op.add_column("scan_jobs",
        sa.Column("diagnostic_detail", sa.Text(), nullable=True))
    op.add_column("ojs_targets",
        sa.Column("force_heartbeat", sa.Boolean(), nullable=False,
                  server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("ojs_targets", "force_heartbeat")
    op.drop_column("scan_jobs", "diagnostic_detail")
    op.drop_column("scan_jobs", "diagnostic_code")
