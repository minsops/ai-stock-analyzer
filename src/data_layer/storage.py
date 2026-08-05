"""SQLite/PostgreSQL 数据库存储层。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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


class NewsItem(Base):
    __tablename__ = "news"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    pub_date: Mapped[date] = mapped_column(Date, primary_key=True)
    title: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)


class MarketRegime(Base):
    __tablename__ = "market_regime"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    regime: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    details_json: Mapped[str | None] = mapped_column(Text)


class Watchlist(Base):
    __tablename__ = "watchlist"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    group_name: Mapped[str] = mapped_column(String, default="默认")
    alert_above: Mapped[float | None] = mapped_column(Float, nullable=True)  # 评分≥该值时提醒
    alert_below: Mapped[float | None] = mapped_column(Float, nullable=True)  # 评分≤该值时提醒
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


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
        # 轻量迁移:为已存在的 watchlist 表补后加的列(create_all 不会 ALTER 旧表)。
        self._ensure_columns("watchlist", {"group_name": "VARCHAR DEFAULT '默认'", "alert_above": "FLOAT", "alert_below": "FLOAT"})
        logger.info("数据库表初始化完成")

    def _ensure_columns(self, table: str, columns: dict[str, str]) -> None:
        """SQLite 下为已存在的表补缺失列(简易迁移)。其他方言交给用户的迁移工具。"""
        if self.engine.dialect.name != "sqlite":
            return
        from sqlalchemy import text

        with self.engine.begin() as connection:
            existing = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
            if not existing:  # 表还不存在(create_all 已建则不会到这);跳过
                return
            for name, ddl in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

    def upsert_stocks(self, df: pd.DataFrame) -> int:
        return self._upsert_dataframe(df, Stock, ["code"])

    def upsert_daily_quotes(self, df: pd.DataFrame) -> int:
        return self._upsert_dataframe(df, DailyQuote, ["code", "trade_date"])

    def upsert_financial_data(self, df: pd.DataFrame) -> int:
        return self._upsert_dataframe(df, FinancialData, ["code", "report_date"])

    def upsert_fundamentals(self, df: pd.DataFrame) -> int:
        """只写入/更新基本面列(roe/同比/毛利/负债等),不触碰估值列(pe/pb/ps)。

        用于按季度回填历史基本面而不覆盖已有的月度估值行(point-in-time 因子研究需要)。
        """
        if df.empty:
            return 0
        self.init_db()
        fund_cols = [c for c in ("roe", "revenue", "net_profit", "revenue_yoy", "profit_yoy", "gross_margin", "debt_ratio", "free_cash_flow", "dividend_yield") if c in df.columns]
        if not fund_cols:
            return 0
        keep = ["code", "report_date", *fund_cols]
        sub = df[keep].copy()
        sub = sub.where(pd.notnull(sub), None)
        records = sub.to_dict("records")
        chunk_size = max(1, 900 // (len(keep) + 1))
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "sqlite":
                for start in range(0, len(records), chunk_size):
                    batch = records[start : start + chunk_size]
                    stmt = sqlite_insert(FinancialData).values(batch)
                    update_columns = {c: getattr(stmt.excluded, c) for c in fund_cols}
                    connection.execute(stmt.on_conflict_do_update(index_elements=["code", "report_date"], set_=update_columns))
            else:
                from sqlalchemy import update as _sa_update

                for rec in records:
                    connection.execute(_sa_update(FinancialData).where(FinancialData.code == rec["code"], FinancialData.report_date == rec["report_date"]).values(**{c: rec[c] for c in fund_cols}))
        logger.info(f"financial_data 基本面回填 {len(records)} 行")
        return len(records)

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

    def upsert_news(self, df: pd.DataFrame) -> int:
        """写入个股公告/新闻。"""
        return self._upsert_dataframe(df, NewsItem, ["code", "pub_date", "title"])

    def get_recent_news(self, code: str, days: int = 30, limit: int = 30) -> list[dict[str, Any]]:
        """读取个股最近公告/新闻(按日期倒序)。news 表不存在时返回空，不影响其余链路。"""
        cutoff = (datetime.now(UTC).date() - timedelta(days=days)).isoformat()
        stmt = (
            select(NewsItem.code, NewsItem.pub_date, NewsItem.title, NewsItem.source)
            .where(NewsItem.code == code, NewsItem.pub_date >= pd.to_datetime(cutoff).date())
            .order_by(NewsItem.pub_date.desc())
            .limit(limit)
        )
        try:
            return pd.read_sql(stmt, self.engine).to_dict("records")
        except Exception:  # noqa: BLE001 - 表缺失或读取异常时降级
            return []

    def get_stock_info(self, code: str) -> dict[str, Any]:
        """获取股票基础信息。"""
        with self.SessionLocal() as session:
            row = session.get(Stock, code)
            return self._model_to_dict(row) if row else {}

    def get_latest_score(self, code: str) -> dict[str, Any]:
        """获取某只股票最近一次落库的综合评分(含各引擎分)。"""
        with self.SessionLocal() as session:
            row = session.execute(
                select(Score).where(Score.code == code).order_by(Score.score_date.desc()).limit(1)
            ).scalar_one_or_none()
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

    def get_active_stocks(self) -> pd.DataFrame:
        """获取正常交易股票的代码、名称、行业。"""
        stmt = select(Stock.code, Stock.name, Stock.industry_l1, Stock.is_st).where(Stock.is_active.is_(True))
        return pd.read_sql(stmt, self.engine)

    def save_scores(self, scores_df: pd.DataFrame) -> int:
        """保存评分结果。"""
        if "weights" in scores_df.columns and "weights_json" not in scores_df.columns:
            scores_df = scores_df.copy()
            scores_df["weights_json"] = scores_df["weights"].map(lambda value: json.dumps(value, ensure_ascii=False))
        return self._upsert_dataframe(scores_df, Score, ["code", "score_date"])

    def get_top_scores(self, date: str, top_n: int = 50) -> pd.DataFrame:
        """获取某日综合评分 Top N；该日无评分时回退到最近一次评分日。"""
        target = pd.to_datetime(date).date()
        with self.SessionLocal() as session:
            has_today = session.execute(select(Score.score_date).where(Score.score_date == target).limit(1)).first()
            if not has_today:
                latest = session.execute(select(Score.score_date).order_by(Score.score_date.desc()).limit(1)).scalar_one_or_none()
                if latest is not None:
                    target = latest
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
            .where(Score.score_date == target)
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

    def add_to_watchlist(
        self,
        code: str,
        note: str | None = None,
        group_name: str | None = None,
        alert_above: float | None = None,
        alert_below: float | None = None,
    ) -> bool:
        """加入自选;已存在则更新提供的字段(None 表示不改)。返回是否新增。"""
        self.init_db()
        updates: dict[str, Any] = {}
        if note is not None:
            updates["note"] = note
        if group_name is not None:
            updates["group_name"] = group_name
        if alert_above is not None:
            updates["alert_above"] = alert_above
        if alert_below is not None:
            updates["alert_below"] = alert_below
        with self.engine.begin() as connection:
            stmt = sqlite_insert(Watchlist).values(
                code=code,
                note=note,
                group_name=group_name or "默认",
                alert_above=alert_above,
                alert_below=alert_below,
                added_at=datetime.now(UTC),
            )
            if self.engine.dialect.name == "sqlite" and updates:
                stmt = stmt.on_conflict_do_update(index_elements=["code"], set_=updates)
            elif self.engine.dialect.name == "sqlite":
                stmt = stmt.on_conflict_do_nothing(index_elements=["code"])
            result = connection.execute(stmt)
            return bool(result.rowcount)

    def remove_from_watchlist(self, code: str) -> bool:
        """移除自选。返回是否确有删除。"""
        from sqlalchemy import delete

        with self.engine.begin() as connection:
            result = connection.execute(delete(Watchlist).where(Watchlist.code == code))
            return bool(result.rowcount)

    def get_watchlist(self) -> list[str]:
        """返回自选代码列表(按加入时间倒序)。"""
        self.init_db()
        with self.SessionLocal() as session:
            rows = session.execute(select(Watchlist.code).order_by(Watchlist.added_at.desc())).scalars().all()
            return list(rows)

    def get_watchlist_full(self) -> list[dict[str, Any]]:
        """返回自选完整记录(含分组/提醒阈值,按加入时间倒序)。"""
        self.init_db()
        with self.SessionLocal() as session:
            rows = session.execute(select(Watchlist).order_by(Watchlist.added_at.desc())).scalars().all()
            return [self._model_to_dict(row) for row in rows]

    def check_watchlist_alerts(self) -> list[dict[str, Any]]:
        """对每只设了阈值的自选,用最近评分判断是否触发提醒。返回触发列表。"""
        alerts: list[dict[str, Any]] = []
        for item in self.get_watchlist_full():
            above, below = item.get("alert_above"), item.get("alert_below")
            if above is None and below is None:
                continue
            score = self.get_latest_score(item["code"]).get("composite_score")
            if score is None:
                continue
            if above is not None and score >= above:
                alerts.append({"code": item["code"], "score": score, "type": "above", "threshold": above})
            elif below is not None and score <= below:
                alerts.append({"code": item["code"], "score": score, "type": "below", "threshold": below})
        return alerts

    def _upsert_dataframe(self, df: pd.DataFrame, model: type[Base], key_columns: list[str]) -> int:
        if df.empty:
            logger.warning(f"{model.__tablename__} 收到空数据，跳过写入")
            return 0
        records = self._records_for_model(df, model)
        if not records:
            return 0
        # SQLite 单条语句的绑定变量数有上限（旧版本仅 999），整表一次性写入会触发
        # "too many SQL variables"，因此按列数计算安全分块大小后分批写入。
        column_count = max(1, len(model.__table__.columns))
        chunk_size = max(1, 900 // column_count)
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "sqlite":
                update_columns = {
                    column.name: getattr(sqlite_insert(model).excluded, column.name)
                    for column in model.__table__.columns
                    if column.name not in key_columns
                }
                for start in range(0, len(records), chunk_size):
                    batch = records[start : start + chunk_size]
                    stmt = sqlite_insert(model).values(batch)
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
