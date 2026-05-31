"""add plugin connection fields to ojs_targets

Revision ID: 002
Revises: 001
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ojs_targets",
        sa.Column("trigger_endpoint", sa.String(500), nullable=True))
    op.add_column("ojs_targets",
        sa.Column("probe_endpoint", sa.String(500), nullable=True))
    op.add_column("ojs_targets",
        sa.Column("connection_mode", sa.String(20), nullable=True,
                  server_default="unknown"))
    op.add_column("ojs_targets",
        sa.Column("pending_scan_job_id", UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ojs_targets", "pending_scan_job_id")
    op.drop_column("ojs_targets", "connection_mode")
    op.drop_column("ojs_targets", "probe_endpoint")
    op.drop_column("ojs_targets", "trigger_endpoint")
