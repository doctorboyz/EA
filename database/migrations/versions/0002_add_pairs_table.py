"""Add pairs table for metadata from pairs.yaml

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-15
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pairs table
    op.create_table(
        "pairs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(10), nullable=False, unique=True),
        sa.Column("broker_leverage", sa.String(20), nullable=False, server_default="1:2000"),
        sa.Column("typical_spread_pips", sa.Float(), nullable=False),
        sa.Column("typical_volatility_pips_h1", sa.Float(), nullable=False),
        sa.Column("trading_hours", sa.String(50), nullable=False, server_default="Unknown"),
        sa.Column("correlation_vs_eurusd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("recommended", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_pairs_symbol", "pairs", ["symbol"])


def downgrade() -> None:
    op.drop_index("idx_pairs_symbol", table_name="pairs")
    op.drop_table("pairs")
