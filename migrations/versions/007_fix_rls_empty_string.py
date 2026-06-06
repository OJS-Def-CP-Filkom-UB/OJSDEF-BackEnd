"""Fix RLS policy crash saat app.current_tenant_id berisi empty string

Root cause: get_db finally block reset ke '' (bukan NULL). Koneksi pool yang
'kotor' menyebabkan current_setting(...)::uuid gagal dengan InvalidTextRepresentation
saat plugin_auth_middleware query ojs_targets tanpa tenant context.

Fix: NULLIF(..., '') mengubah '' menjadi NULL sebelum cast ke uuid, sehingga
NULL::uuid = NULL (aman) bukan error.

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
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                current_setting('app.user_role', true) = 'saas_admin'
                OR tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
            )
        """)


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                current_setting('app.user_role', true) = 'saas_admin'
                OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
            )
        """)
