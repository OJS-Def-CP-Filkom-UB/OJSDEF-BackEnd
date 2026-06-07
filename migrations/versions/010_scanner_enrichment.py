"""scanner enrichment: add references/remediation_steps to scan_findings, module_errors to scan_jobs

Revision ID: 010
Revises: 009
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scan_findings",
        sa.Column("references", sa.Text(), nullable=True))
    op.add_column("scan_findings",
        sa.Column("remediation_steps", sa.Text(), nullable=True))
    op.add_column("scan_jobs",
        sa.Column("module_errors", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("scan_jobs", "module_errors")
    op.drop_column("scan_findings", "remediation_steps")
    op.drop_column("scan_findings", "references")
