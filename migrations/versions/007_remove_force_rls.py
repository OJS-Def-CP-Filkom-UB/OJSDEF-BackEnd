"""remove force rls — dual-engine architecture sudah cukup untuk tenant isolation

FORCE RLS tidak diperlukan karena:
- ojsdef_app (non-owner, runtime) sudah kena RLS secara default
- ojsdef (owner) hanya dipakai untuk seed/migrations/workers — tidak perlu dibatasi

Revision ID: 007
Revises: 006
Create Date: 2026-06-06
"""
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

RLS_TABLES = [
    "users", "ojs_targets", "scan_jobs", "scan_findings",
    "scan_schedules", "reports", "notifications", "audit_logs",
]


def upgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
