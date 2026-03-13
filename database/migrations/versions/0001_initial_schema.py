"""Initial schema: strategies, backtest_runs, analyses, improvements, news_events

Revision ID: 0001
Revises:
Create Date: 2026-03-13
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # strategies
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version_str", sa.String(32), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=True),
        sa.Column("code_path", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("strategies.id"), nullable=True),
        sa.Column("change_rationale", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_str"),
    )
    op.create_index("idx_strategies_config", "strategies", ["config"],
                    postgresql_using="gin")

    # backtest_runs
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy_id", sa.Integer(), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("symbol", sa.String(10), nullable=True, server_default="EURUSD"),
        sa.Column("timeframe", sa.String(5), nullable=True, server_default="H1"),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("initial_capital", sa.Float(), nullable=True, server_default="1000.0"),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("net_profit", sa.Float(), nullable=True),
        sa.Column("gross_profit", sa.Float(), nullable=True),
        sa.Column("gross_loss", sa.Float(), nullable=True),
        sa.Column("expected_payoff", sa.Float(), nullable=True),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=True),
        sa.Column("recovery_factor", sa.Float(), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("win_rate_pct", sa.Float(), nullable=True),
        sa.Column("avg_win_usd", sa.Float(), nullable=True),
        sa.Column("avg_loss_usd", sa.Float(), nullable=True),
        sa.Column("avg_win_loss_ratio", sa.Float(), nullable=True),
        sa.Column("max_consecutive_losses", sa.Integer(), nullable=True),
        sa.Column("sharpe_ratio", sa.Float(), nullable=True),
        sa.Column("margin_level_min_pct", sa.Float(), nullable=True),
        sa.Column("meets_pf_target", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("meets_dd_target", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("meets_rf_target", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("meets_rr_target", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("meets_all_targets", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_champion", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )

    # analyses
    op.create_table(
        "analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("backtest_run_id", sa.Integer(), sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("model_used", sa.String(64), nullable=True, server_default="llama3.2:3b"),
        sa.Column("weaknesses_json", postgresql.JSONB(), nullable=True),
        sa.Column("recommendations_json", postgresql.JSONB(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )

    # improvements
    op.create_table(
        "improvements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("from_strategy_id", sa.Integer(), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("to_strategy_id", sa.Integer(), sa.ForeignKey("strategies.id"), nullable=True),
        sa.Column("improvement_type", sa.String(32), nullable=True),
        sa.Column("param_changes_json", postgresql.JSONB(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )

    # news_events
    op.create_table(
        "news_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("impact", sa.String(10), nullable=False),
        sa.Column("event_name", sa.String(256), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("news_events")
    op.drop_table("improvements")
    op.drop_table("analyses")
    op.drop_table("backtest_runs")
    op.drop_index("idx_strategies_config", table_name="strategies")
    op.drop_table("strategies")
