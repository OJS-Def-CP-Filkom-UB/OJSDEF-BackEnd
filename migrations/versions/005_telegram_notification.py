"""005_telegram_notification

Revision ID: 005
Revises: 004
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('telegram_username', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('telegram_link_token', sa.String(64), nullable=True))
    op.create_unique_constraint('uq_users_telegram_link_token', 'users', ['telegram_link_token'])
    op.add_column('users', sa.Column(
        'telegram_link_token_expires',
        sa.DateTime(timezone=True),
        nullable=True,
    ))
    op.alter_column('notifications', 'job_id', nullable=True)


def downgrade() -> None:
    op.alter_column('notifications', 'job_id', nullable=False)
    op.drop_column('users', 'telegram_link_token_expires')
    op.drop_constraint('uq_users_telegram_link_token', 'users', type_='unique')
    op.drop_column('users', 'telegram_link_token')
    op.drop_column('users', 'telegram_username')
