"""SQLite/PostgreSQL 数据库存储层。"""

from __future__ import annotations

from datetime import UTC, date, datetime
import json
from typing import Any

import pandas as pd
from loguru import logger
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from config import settings


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类。"""


class Stock(Base):
    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[str] = mapped_column(String, nullable=False)
    industry_l1: Mapped[str | None] = mapped_column(String, nullable=True)
    industry_l2: Mapped[str | None] = mapped_column(String, nullable=True)
    list_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_st: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class DailyQuote(Base):
    __tablename__ = "daily_quotes"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    turnover: Mapped[float | None] = mapped_column(Float)
    pct_change: Mapped[float | None] = mapped_column(Float)


class FinancialData(Base):
    __tablename__ = "financial_data"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    pe_ttm: Mapped[float | None] = mapped_column(Float)
    pb: Mapped[float | None] = mapped_column(Float)
    ps_ttm: Mapped[float | None] = mapped_column(Float)
    roe: Mapped[float | None] = mapped_column(Float)
    revenue: Mapped[float | None] = mapped_column(Float)
    net_profit: Mapped[float | None] = mapped_column(Float)
    revenue_yoy: Mapped[float | None] = mapped_column(Float)
    profit_yoy: Mapped[float | None] = mapped_column(Float)
    gross_margin: Mapped[float | None] = mapped_column(Float)
    debt_ratio: Mapped[float | None] = mapped_column(Float)
    free_cash_flow: Mapped[float | None] = mapped_column(Float)
    dividend_yield: Mapped[float | None] = mapped_column(Float)


class CapitalFlow(Base):
    __tablename__ = "capital_flow"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    main_net_inflow: Mapped[float | None] = mapped_column(Float)
    north_net_flow: Mapped[float | None] = mapped_column(Float)
    margin_balance: Mapped[float | None] = mapped_column(Float)
    holder_count: Mapped[int | None] = mapped_column(Integer)


class IndustryIndex(Base):
    __tablename__ = "industry_index"

    industry_code: Mapped[str] = mapped_column(String, primary_key=True)
    industry_name: Mapped[str] = mapped_column(String, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float | None] = mapped_column(Float)
    pct_change: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)


class Score(Base):
    __tablename__ = "scores"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    score_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    value_score: Mapped[float | None] = mapped_column(Float)
    trend_score: Mapped[float | None] = mapped_column(Float)
    capital_score: Mapped[float | None] = mapped_column(Float)
    industry_score: Mapped[float | None] = mapped_column(Float)
    event_score: Mapped[float | None] = mapped_column(Float)
    composite_score: Mapped[float | None] = mapped_column(Float, index=True)
    regime: Mapped[str | None] = mapped_column(String)
    weights_json: Mapped[str | None] = mapped_column(Text)


class MarketRegime(Base):
    __tablename__ = "market_regime"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    regime: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    details_json: Mapped[str | None] = mapped_column(Text)


class DataStorage:
    """数据库 CRUD 操作。"""

    def __init__(self, db_url: str | None = None) -> None:
        self.db_url = db_url or settings.DATABASE_URL
        if self.db_url.startswith("sqlite:///"):
            db_path = self.db_url.removeprefix("sqlite:///")
            if db_path and db_path != ":memory:":
                from pathlib import Path

                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(self.db_url, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, future=True)

    def init_db(self) -> None:
        """创建所有数据库表。"""
        Base.metadata.create_all(self.engine)
        logger.info("数据库表初始化完成")

    def upsert_stocks(self, df: pd.DataFrame) -> int:
        return self._upsert_dataframe(df, Stock, ["code"])

    def upsert_daily_quotes(self, df: pd.DataFrame) -> int:
        return self._upsert_dataframe(df, DailyQuote, ["code", "trade_date"])

    def upsert_financial_data(self, df: pd.DataFrame) -> int:
        return self._upsert_dataframe(df, FinancialData, ["code", "report_date"])

    def upsert_capital_flow(self, df: pd.DataFrame) -> int:
        return self._upsert_dataframe(df, CapitalFlow, ["code", "trade_date"])

    def upsert_industry_index(self, df: pd.DataFrame) -> int:
        return self._upsert_dataframe(df, IndustryIndex, ["industry_code", "trade_date"])

    def get_quotes(self, code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        """读取日线数据。"""
        stmt = select(DailyQuote).where(DailyQuote.code == code)
        if start_date:
            stmt = stmt.where(DailyQuote.trade_date >= pd.to_datetime(start_date).date())
        if end_date:
            stmt = stmt.where(DailyQuote.trade_date <= pd.to_datetime(end_date).date())
        stmt = stmt.order_by(DailyQuote.trade_date)
        return pd.read_sql(stmt, self.engine)

    def get_latest_financial(self, code: str) -> dict[str, Any]:
        """获取最新一期财务数据。"""
        with self.SessionLocal() as session:
            row = session.execute(
                select(FinancialData).where(FinancialData.code == code).order_by(FinancialData.report_date.desc()).limit(1)
            ).scalar_one_or_none()
            return self._model_to_dict(row) if row else {}

    def get_financial_history(self, code: str) -> pd.DataFrame:
        """获取财务历史数据。"""
        stmt = select(FinancialData).where(FinancialData.code == code).order_by(FinancialData.report_date)
        return pd.read_sql(stmt, self.engine)

    def get_capital_flow(self, code: str) -> pd.DataFrame:
        """获取资金流向历史数据。"""
        stmt = select(CapitalFlow).where(CapitalFlow.code == code).order_by(CapitalFlow.trade_date)
        return pd.read_sql(stmt, self.engine)

    def get_stock_info(self, code: str) -> dict[str, Any]:
        """获取股票基础信息。"""
        with self.SessionLocal() as session:
            row = session.get(Stock, code)
            return self._model_to_dict(row) if row else {}

    def get_industry_history(self, industry_name: str) -> pd.DataFrame:
        """按行业名称获取行业指数历史。"""
        stmt = select(IndustryIndex).where(IndustryIndex.industry_name == industry_name).order_by(IndustryIndex.trade_date)
        return pd.read_sql(stmt, self.engine)

    def get_all_industry_history(self) -> pd.DataFrame:
        """获取全部行业指数历史。"""
        stmt = select(IndustryIndex).order_by(IndustryIndex.industry_name, IndustryIndex.trade_date)
        return pd.read_sql(stmt, self.engine)

    def get_all_active_codes(self) -> list[str]:
        """获取所有正常交易股票代码。"""
        with self.SessionLocal() as session:
            rows = session.execute(select(Stock.code).where(Stock.is_active.is_(True))).scalars().all()
            return list(rows)

    def save_scores(self, scores_df: pd.DataFrame) -> int:
        """保存评分结果。"""
        if "weights" in scores_df.columns and "weights_json" not in scores_df.columns:
            scores_df = scores_df.copy()
            scores_df["weights_json"] = scores_df["weights"].map(lambda value: json.dumps(value, ensure_ascii=False))
        return self._upsert_dataframe(scores_df, Score, ["code", "score_date"])

    def get_top_scores(self, date: str, top_n: int = 50) -> pd.DataFrame:
        """获取某日综合评分 Top N。"""
        stmt = (
            select(
                Score.code,
                Stock.name,
                Stock.industry_l1.label("industry"),
                Score.score_date,
                Score.value_score,
                Score.trend_score,
                Score.capital_score,
                Score.industry_score,
                Score.event_score,
                Score.composite_score,
                Score.regime,
                Score.weights_json,
            )
            .join(Stock, Stock.code == Score.code, isouter=True)
            .where(Score.score_date == pd.to_datetime(date).date())
            .order_by(Score.composite_score.desc())
            .limit(top_n)
        )
        return pd.read_sql(stmt, self.engine)

    def save_market_regime(self, trade_date: date, regime: str, confidence: float, details: dict[str, Any]) -> int:
        """保存市场状态记录。"""
        frame = pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "regime": regime,
                    "confidence": confidence,
                    "details_json": json.dumps(details, ensure_ascii=False),
                }
            ]
        )
        return self._upsert_dataframe(frame, MarketRegime, ["trade_date"])

    def get_latest_market_regime(self) -> dict[str, Any]:
        """读取最近一次市场状态。"""
        with self.SessionLocal() as session:
            row = session.execute(select(MarketRegime).order_by(MarketRegime.trade_date.desc()).limit(1)).scalar_one_or_none()
            return self._model_to_dict(row) if row else {}

    def _upsert_dataframe(self, df: pd.DataFrame, model: type[Base], key_columns: list[str]) -> int:
        if df.empty:
            logger.warning(f"{model.__tablename__} 收到空数据，跳过写入")
            return 0
        records = self._records_for_model(df, model)
        if not records:
            return 0
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "sqlite":
                stmt = sqlite_insert(model).values(records)
                update_columns = {
                    column.name: getattr(stmt.excluded, column.name)
                    for column in model.__table__.columns
                    if column.name not in key_columns
                }
                connection.execute(stmt.on_conflict_do_update(index_elements=key_columns, set_=update_columns))
            else:
                with Session(bind=connection) as session:
                    session.bulk_save_objects([model(**record) for record in records])
        logger.info(f"{model.__tablename__} 写入/更新 {len(records)} 行")
        return len(records)

    def _records_for_model(self, df: pd.DataFrame, model: type[Base]) -> list[dict[str, Any]]:
        columns = {column.name for column in model.__table__.columns}
        records: list[dict[str, Any]] = []
        for row in df.to_dict("records"):
            record = {key: self._normalize_value(value) for key, value in row.items() if key in columns}
            if all(value is not None for key, value in record.items() if key in self._primary_keys(model)):
                records.append(record)
        return records

    def _primary_keys(self, model: type[Base]) -> set[str]:
        return {column.name for column in model.__table__.primary_key.columns}

    def _normalize_value(self, value: Any) -> Any:
        if pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.date()
        return value

    def _model_to_dict(self, row: Base) -> dict[str, Any]:
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}
