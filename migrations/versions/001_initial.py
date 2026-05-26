"""initial schema

Revision ID: 001
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

RLS_TABLES = [
    "users", "ojs_targets", "scan_jobs", "scan_findings",
    "scan_schedules", "reports", "notifications", "audit_logs",
]

_TS = dict(type_=sa.DateTime(timezone=True), server_default=sa.func.now())


def _uuid_col(name="id", **kw):
    return sa.Column(name, UUID(as_uuid=True), **kw)


def upgrade() -> None:
    op.create_table("tenants",
        _uuid_col(primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("users",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("must_change_password", sa.Boolean, default=False),
        sa.Column("notif_email", sa.Boolean, default=True),
        sa.Column("notif_telegram", sa.Boolean, default=False),
        sa.Column("telegram_chat_id", sa.String(50)),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("ojs_targets",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("is_verified", sa.Boolean, default=False),
        sa.Column("verification_token", sa.String(64)),
        sa.Column("plugin_api_key_encrypted", sa.Text),
        sa.Column("plugin_last_seen", sa.DateTime(timezone=True)),
        sa.Column("ojs_version", sa.String(20)),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("scan_jobs",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("target_id", sa.ForeignKey("ojs_targets.id"), nullable=False),
        sa.Column("scan_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), default="queued"),
        sa.Column("overall_score", sa.Float),
        sa.Column("risk_level", sa.String(20)),
        sa.Column("critical_count", sa.Integer, default=0),
        sa.Column("high_count", sa.Integer, default=0),
        sa.Column("medium_count", sa.Integer, default=0),
        sa.Column("low_count", sa.Integer, default=0),
        sa.Column("error_message", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("scan_findings",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("job_id", sa.ForeignKey("scan_jobs.id"), nullable=False),
        sa.Column("finding_type", sa.String(100), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("affected_path", sa.String(1000), nullable=False),
        sa.Column("evidence", sa.Text, nullable=False),
        sa.Column("remediation", sa.Text, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("cvss_score", sa.Float, nullable=False),
        sa.Column("cve_id", sa.String(30)),
        sa.Column("owasp_category", sa.String(100)),
        sa.Column("is_false_positive", sa.Boolean, default=False),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("scan_schedules",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("target_id", sa.ForeignKey("ojs_targets.id"), nullable=False),
        sa.Column("cron_expression", sa.String(100), nullable=False),
        sa.Column("scan_type", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("reports",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("job_id", sa.ForeignKey("scan_jobs.id"), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("storage_path", sa.Text),
        sa.Column("file_size_bytes", sa.Integer),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("notifications",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("job_id", sa.ForeignKey("scan_jobs.id"), nullable=False),
        _uuid_col("user_id", sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("notif_type", sa.String(30), nullable=False),
        sa.Column("is_sent", sa.Boolean, default=False),
        sa.Column("error_log", sa.Text),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )
    op.create_table("audit_logs",
        _uuid_col(primary_key=True),
        _uuid_col("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
        _uuid_col("user_id", sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100)),
        sa.Column("details", JSONB),
        sa.Column("created_at", **_TS), sa.Column("updated_at", **_TS),
    )

    # Indexes
    op.create_index("idx_scan_jobs_target_id", "scan_jobs", ["target_id"])
    op.create_index("idx_scan_jobs_status", "scan_jobs", ["status"])
    op.create_index("idx_scan_findings_job_id", "scan_findings", ["job_id"])
    op.create_index("idx_scan_findings_severity", "scan_findings", ["severity"])
    op.create_index("idx_users_tenant_id", "users", ["tenant_id"])
    op.create_index("idx_ojs_targets_tenant_id", "ojs_targets", ["tenant_id"])

    # RLS — use true() fallback so saas_admin seed (without tenant context) still works
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                tenant_id = current_setting('app.current_tenant_id', true)::uuid
                OR current_setting('app.current_tenant_id', true) = ''
            )
        """)


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    for t in ["audit_logs", "notifications", "reports", "scan_schedules",
              "scan_findings", "scan_jobs", "ojs_targets", "users", "tenants"]:
        op.drop_table(t)
