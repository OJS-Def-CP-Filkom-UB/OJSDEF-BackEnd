"""add ON DELETE CASCADE to target/job foreign keys

Menghapus OJSTarget sebelumnya gagal dengan ForeignKeyViolationError karena
scan_jobs (dan turunannya) serta scan_schedules mereferensi target tanpa
ON DELETE CASCADE. Migrasi ini menjadikan penghapusan target meng-cascade ke
seluruh data scan miliknya.

Rantai cascade:
    ojs_targets ─┬─► scan_jobs ─┬─► scan_findings
                 │              ├─► reports
                 │              └─► notifications
                 └─► scan_schedules

Revision ID: 011
Revises: 010
Create Date: 2026-06-15
"""
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

# (child_table, child_column, parent_table, parent_column)
_FKS = [
    ("scan_jobs", "target_id", "ojs_targets", "id"),
    ("scan_schedules", "target_id", "ojs_targets", "id"),
    ("scan_findings", "job_id", "scan_jobs", "id"),
    ("reports", "job_id", "scan_jobs", "id"),
    ("notifications", "job_id", "scan_jobs", "id"),
]


def _drop_existing_fk(table: str, column: str) -> str:
    """Drop FK constraint yang mengatur table.column apa pun namanya (name-agnostic)."""
    return f"""
DO $$
DECLARE cname text;
BEGIN
  SELECT tc.constraint_name INTO cname
  FROM information_schema.table_constraints tc
  JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
   AND tc.table_schema = kcu.table_schema
  WHERE tc.constraint_type = 'FOREIGN KEY'
    AND tc.table_schema = 'public'
    AND tc.table_name = '{table}'
    AND kcu.column_name = '{column}'
  LIMIT 1;
  IF cname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I', '{table}', cname);
  END IF;
END $$;
"""


def upgrade() -> None:
    for child_table, child_col, parent_table, parent_col in _FKS:
        op.execute(_drop_existing_fk(child_table, child_col))
        op.create_foreign_key(
            f"{child_table}_{child_col}_fkey",
            child_table,
            parent_table,
            [child_col],
            [parent_col],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for child_table, child_col, parent_table, parent_col in _FKS:
        op.execute(_drop_existing_fk(child_table, child_col))
        op.create_foreign_key(
            f"{child_table}_{child_col}_fkey",
            child_table,
            parent_table,
            [child_col],
            [parent_col],
        )
