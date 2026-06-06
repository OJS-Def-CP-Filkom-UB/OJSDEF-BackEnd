"""fix role guc name — ganti app.current_role -> app.user_role di RLS policy

current_role adalah reserved keyword PostgreSQL sehingga SET app.current_role
menyebabkan PostgresSyntaxError. Ganti semua referensi ke app.user_role.

Revision ID: 008
Revises: 007
Create Date: 2026-06-06
"""
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

RLS_TABLES = [
    "users", "ojs_targets", "scan_jobs", "scan_findings",
    "scan_schedules", "reports", "notifications", "audit_logs",
]


def upgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                current_setting('app.user_role', true) = 'saas_admin'
                OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
            )
        """)


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                current_setting('app.current_role', true) = 'saas_admin'
                OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
            )
        """)
