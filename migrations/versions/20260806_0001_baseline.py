"""Create the baseline application schema.

Revision ID: 20260806_0001
Revises:
Create Date: 2026-08-06
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_definitions() -> dict[str, tuple[list[sa.Column], tuple[str, ...]]]:
    return {
        "stocks": (
            [
                sa.Column("code", sa.String(), nullable=False),
                sa.Column("name", sa.String(), nullable=False),
                sa.Column("market", sa.String(), nullable=False),
                sa.Column("industry_l1", sa.String(), nullable=True),
                sa.Column("industry_l2", sa.String(), nullable=True),
                sa.Column("list_date", sa.Date(), nullable=True),
                sa.Column("is_st", sa.Boolean(), nullable=False, server_default=sa.false()),
                sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
            ],
            ("code",),
        ),
        "daily_quotes": (
            [
                sa.Column("code", sa.String(), nullable=False),
                sa.Column("trade_date", sa.Date(), nullable=False),
                sa.Column("open", sa.Float(), nullable=True),
                sa.Column("high", sa.Float(), nullable=True),
                sa.Column("low", sa.Float(), nullable=True),
                sa.Column("close", sa.Float(), nullable=True),
                sa.Column("volume", sa.Float(), nullable=True),
                sa.Column("amount", sa.Float(), nullable=True),
                sa.Column("turnover", sa.Float(), nullable=True),
                sa.Column("pct_change", sa.Float(), nullable=True),
            ],
            ("code", "trade_date"),
        ),
        "financial_data": (
            [
                sa.Column("code", sa.String(), nullable=False),
                sa.Column("report_date", sa.Date(), nullable=False),
                sa.Column("pe_ttm", sa.Float(), nullable=True),
                sa.Column("pb", sa.Float(), nullable=True),
                sa.Column("ps_ttm", sa.Float(), nullable=True),
                sa.Column("roe", sa.Float(), nullable=True),
                sa.Column("revenue", sa.Float(), nullable=True),
                sa.Column("net_profit", sa.Float(), nullable=True),
                sa.Column("revenue_yoy", sa.Float(), nullable=True),
                sa.Column("profit_yoy", sa.Float(), nullable=True),
                sa.Column("gross_margin", sa.Float(), nullable=True),
                sa.Column("debt_ratio", sa.Float(), nullable=True),
                sa.Column("free_cash_flow", sa.Float(), nullable=True),
                sa.Column("dividend_yield", sa.Float(), nullable=True),
            ],
            ("code", "report_date"),
        ),
        "capital_flow": (
            [
                sa.Column("code", sa.String(), nullable=False),
                sa.Column("trade_date", sa.Date(), nullable=False),
                sa.Column("main_net_inflow", sa.Float(), nullable=True),
                sa.Column("north_net_flow", sa.Float(), nullable=True),
                sa.Column("margin_balance", sa.Float(), nullable=True),
                sa.Column("holder_count", sa.Integer(), nullable=True),
            ],
            ("code", "trade_date"),
        ),
        "industry_index": (
            [
                sa.Column("industry_code", sa.String(), nullable=False),
                sa.Column("industry_name", sa.String(), nullable=False),
                sa.Column("trade_date", sa.Date(), nullable=False),
                sa.Column("close", sa.Float(), nullable=True),
                sa.Column("pct_change", sa.Float(), nullable=True),
                sa.Column("volume", sa.Float(), nullable=True),
            ],
            ("industry_code", "trade_date"),
        ),
        "scores": (
            [
                sa.Column("code", sa.String(), nullable=False),
                sa.Column("score_date", sa.Date(), nullable=False),
                sa.Column("value_score", sa.Float(), nullable=True),
                sa.Column("trend_score", sa.Float(), nullable=True),
                sa.Column("capital_score", sa.Float(), nullable=True),
                sa.Column("industry_score", sa.Float(), nullable=True),
                sa.Column("event_score", sa.Float(), nullable=True),
                sa.Column("composite_score", sa.Float(), nullable=True),
                sa.Column("regime", sa.String(), nullable=True),
                sa.Column("weights_json", sa.Text(), nullable=True),
            ],
            ("code", "score_date"),
        ),
        "news": (
            [
                sa.Column("code", sa.String(), nullable=False),
                sa.Column("pub_date", sa.Date(), nullable=False),
                sa.Column("title", sa.String(), nullable=False),
                sa.Column("source", sa.String(), nullable=True),
            ],
            ("code", "pub_date", "title"),
        ),
        "market_regime": (
            [
                sa.Column("trade_date", sa.Date(), nullable=False),
                sa.Column("regime", sa.String(), nullable=False),
                sa.Column("confidence", sa.Float(), nullable=True),
                sa.Column("details_json", sa.Text(), nullable=True),
            ],
            ("trade_date",),
        ),
        "watchlist": (
            [
                sa.Column("code", sa.String(), nullable=False),
                sa.Column("note", sa.String(), nullable=True),
                sa.Column("group_name", sa.String(), nullable=False, server_default="默认"),
                sa.Column("alert_above", sa.Float(), nullable=True),
                sa.Column("alert_below", sa.Float(), nullable=True),
                sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
            ],
            ("code",),
        ),
    }


INDEXES = {
    "ix_daily_quotes_trade_date": ("daily_quotes", ["trade_date"]),
    "ix_scores_score_date": ("scores", ["score_date"]),
    "ix_scores_composite_score": ("scores", ["composite_score"]),
    "idx_scores_date_composite": ("scores", ["score_date", sa.desc("composite_score")]),
}


def upgrade() -> None:
    if op.get_context().as_sql:
        for table_name, (columns, primary_key) in _table_definitions().items():
            op.create_table(table_name, *columns, sa.PrimaryKeyConstraint(*primary_key))
        for index_name, (table_name, columns) in INDEXES.items():
            op.create_index(index_name, table_name, columns, unique=False)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table_name, (columns, primary_key) in _table_definitions().items():
        if table_name not in existing_tables:
            op.create_table(table_name, *columns, sa.PrimaryKeyConstraint(*primary_key))
            existing_tables.add(table_name)
            continue

        existing_columns = {item["name"] for item in sa.inspect(bind).get_columns(table_name)}
        for column in columns:
            if column.name not in existing_columns:
                op.add_column(table_name, column)

    for index_name, (table_name, columns) in INDEXES.items():
        existing_indexes = {item["name"] for item in sa.inspect(bind).get_indexes(table_name)}
        if index_name not in existing_indexes:
            op.create_index(index_name, table_name, columns, unique=False)


def downgrade() -> None:
    if op.get_context().as_sql:
        for table_name in reversed(list(_table_definitions())):
            op.drop_table(table_name)
        return

    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    for table_name in reversed(list(_table_definitions())):
        if table_name in existing_tables:
            op.drop_table(table_name)
