"""audit_log_user_email_nullable_tenant

Revision ID: 003
Revises: 002
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("user_email", sa.String(255), nullable=False, server_default="unknown"),
    )
    op.alter_column(
        "audit_logs",
        "tenant_id",
        existing_type=UUID(as_uuid=True),
        nullable=True,
    )
    op.create_index("idx_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("idx_audit_logs_action", "audit_logs", ["action"])
    op.create_index("idx_audit_logs_tenant_id", "audit_logs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_audit_logs_tenant_id", table_name="audit_logs")
    op.drop_index("idx_audit_logs_action", table_name="audit_logs")
    op.drop_index("idx_audit_logs_created_at", table_name="audit_logs")
    op.alter_column(
        "audit_logs",
        "tenant_id",
        existing_type=UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_column("audit_logs", "user_email")
