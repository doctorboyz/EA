"""Add framework_type column to strategies and backtest_runs tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-15
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'strategies',
        sa.Column('framework_type', sa.String(50), nullable=True, server_default='base_ea'),
    )
    op.add_column(
        'backtest_runs',
        sa.Column('framework_type', sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('backtest_runs', 'framework_type')
    op.drop_column('strategies', 'framework_type')
