"""rbac tenancy fix — FORCE RLS + policy update + ojsdef_app role

Revision ID: 006
Revises: 005
Create Date: 2026-06-06
"""
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

RLS_TABLES = [
    "users", "ojs_targets", "scan_jobs", "scan_findings",
    "scan_schedules", "reports", "notifications", "audit_logs",
]


def upgrade() -> None:
    # Buat role ojsdef_app (non-owner, subject to RLS)
    # Jika DATABASE_URL user bukan superuser, buat role manual dulu di psql:
    #   CREATE ROLE ojsdef_app WITH LOGIN PASSWORD 'ganti_password_aman';
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ojsdef_app'
            ) THEN
                CREATE ROLE ojsdef_app WITH LOGIN PASSWORD 'changeme_set_via_psql';
            END IF;
        END
        $$;
    """)

    op.execute("GRANT USAGE ON SCHEMA public TO ojsdef_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ojsdef_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ojsdef_app")

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
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
                tenant_id = current_setting('app.current_tenant_id', true)::uuid
                OR current_setting('app.current_tenant_id', true) = ''
            )
        """)
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM ojsdef_app")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM ojsdef_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM ojsdef_app")
    op.execute("DROP ROLE IF EXISTS ojsdef_app")
