"""数据更新调度。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from loguru import logger

from src.data_layer.fetcher import StockDataFetcher
from src.data_layer.storage import DataStorage


@dataclass
class UpdateSummary:
    """数据更新摘要。"""

    stocks: int = 0
    quotes: int = 0
    financial: int = 0
    capital: int = 0
    industry_index: int = 0
    failed_codes: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            "stocks": self.stocks,
            "quotes": self.quotes,
            "financial": self.financial,
            "capital": self.capital,
            "industry_index": self.industry_index,
            "failed_codes": self.failed_codes or [],
        }


class DataUpdater:
    """负责全量和增量数据更新。"""

    def __init__(self, fetcher: StockDataFetcher, storage: DataStorage) -> None:
        self.fetcher = fetcher
        self.storage = storage

    def update(self, full: bool = False, limit: int | None = None, include_slow_data: bool | None = None) -> UpdateSummary:
        """
        执行数据更新。

        full=True 时拉取更长行情，并默认补财务、资金和行业指数；增量更新默认只补最近行情，避免日常运行过慢。
        """
        include_slow_data = full if include_slow_data is None else include_slow_data
        self.storage.init_db()
        summary = UpdateSummary(failed_codes=[])

        stocks = self.fetcher.get_stock_list()
        if not stocks.empty:
            summary.stocks = self.storage.upsert_stocks(stocks)
        codes = stocks["code"].dropna().tolist() if not stocks.empty else self.storage.get_all_active_codes()
        if limit:
            codes = codes[:limit]

        end = date.today()
        start = end - timedelta(days=365 * 5 if full else 10)
        for code in codes:
            try:
                quotes = self.fetcher.get_daily_quotes(code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
                if not quotes.empty:
                    summary.quotes += self.storage.upsert_daily_quotes(quotes)

                if include_slow_data:
                    financial = self.fetcher.get_financial_data(code)
                    if not financial.empty:
                        summary.financial += self.storage.upsert_financial_data(financial)

                    capital = self.fetcher.get_capital_flow(code)
                    if not capital.empty:
                        summary.capital += self.storage.upsert_capital_flow(capital)
            except Exception as exc:  # noqa: BLE001 - 单股失败不中断整体更新
                logger.warning(f"{code} 数据更新失败，已跳过: {exc}")
                summary.failed_codes = summary.failed_codes or []
                summary.failed_codes.append(code)

        if include_slow_data:
            industry_index = self.fetcher.get_industry_index()
            if not industry_index.empty:
                summary.industry_index = self.storage.upsert_industry_index(industry_index)

        return summary

