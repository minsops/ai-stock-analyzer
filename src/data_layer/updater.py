"""数据更新调度。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from loguru import logger

from config import settings
from src.data_layer.fetcher import StockDataFetcher
from src.data_layer.storage import DataStorage
from src.fusion.regime_detector import RegimeDetector


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
        self.regime_detector = RegimeDetector()

    def update(
        self,
        full: bool = False,
        limit: int | None = None,
        include_slow_data: bool | None = None,
        codes: list[str] | None = None,
        sample: int | None = None,
        max_workers: int | None = None,
        years: int | None = None,
    ) -> UpdateSummary:
        """
        执行数据更新。

        full=True 时拉取更长行情，并默认补财务、资金和行业指数；增量更新默认只补最近行情，避免日常运行过慢。
        years 指定时按该年数拉取行情（覆盖 full/增量的默认窗口）。
        codes 指定后只更新这些代码；sample 指定后只取列表前 N 只（快速 bootstrap）。
        per-股票行情/财务/资金为网络 I/O 密集，使用线程池并发拉取。
        """
        include_slow_data = full if include_slow_data is None else include_slow_data
        workers = max(1, max_workers or settings.UPDATE_MAX_WORKERS)
        self.storage.init_db()
        summary = UpdateSummary(failed_codes=[])

        # 拉取慢数据时同时获取行业分类（行业轮动/分类需要）；
        # akshare 的行业映射较贵，仅在 include_slow_data 时才取。
        stocks = self.fetcher.get_stock_list(with_industry=include_slow_data)
        if not stocks.empty:
            summary.stocks = self.storage.upsert_stocks(stocks)
        all_codes = stocks["code"].dropna().tolist() if not stocks.empty else self.storage.get_all_active_codes()
        target_codes = self._select_codes(all_codes, codes=codes, sample=sample, limit=limit)

        end = date.today()
        if years is not None:
            lookback_days = 365 * years
        else:
            lookback_days = 365 * 5 if full else 10
        start = end - timedelta(days=lookback_days)
        start_str, end_str = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

        def fetch(code: str) -> tuple[str, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
            """仅做网络拉取（无 DB 写入），可安全并发。"""
            quotes = self.fetcher.get_daily_quotes(code, start_str, end_str)
            financial = self.fetcher.get_financial_data(code) if include_slow_data else pd.DataFrame()
            capital = self.fetcher.get_capital_flow(code) if include_slow_data else pd.DataFrame()
            return code, quotes, financial, capital

        # 网络 I/O 并发拉取，DB 写入在主线程串行执行：
        # 避免 SQLite 多连接（内存库各线程互不可见、文件库写锁竞争）的问题。
        logger.info(f"开始更新 {len(target_codes)} 只股票，并发 {workers}，slow_data={include_slow_data}")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(fetch, code): code for code in target_codes}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    _, quotes, financial, capital = future.result()
                except Exception as exc:  # noqa: BLE001 - 单股失败不中断整体更新
                    logger.warning(f"{code} 数据更新失败，已跳过: {exc}")
                    summary.failed_codes = summary.failed_codes or []
                    summary.failed_codes.append(code)
                    continue
                if not quotes.empty:
                    summary.quotes += self.storage.upsert_daily_quotes(quotes)
                if include_slow_data and not financial.empty:
                    summary.financial += self.storage.upsert_financial_data(financial)
                if include_slow_data and not capital.empty:
                    summary.capital += self.storage.upsert_capital_flow(capital)

        if include_slow_data:
            industry_index = self.fetcher.get_industry_index()
            if not industry_index.empty:
                summary.industry_index = self.storage.upsert_industry_index(industry_index)

        try:
            market_data = self.fetcher.get_market_overview()
        except Exception as exc:  # noqa: BLE001 - 市场状态失败不影响个股数据更新
            logger.warning(f"市场状态数据获取失败，按震荡处理: {exc}")
            market_data = {}
        regime, confidence, details = self.regime_detector.detect(market_data)
        self.storage.save_market_regime(date.today(), regime, confidence, details)

        return summary

    def _select_codes(
        self,
        all_codes: list[str],
        codes: list[str] | None,
        sample: int | None,
        limit: int | None,
    ) -> list[str]:
        if codes:
            normalized = {self.fetcher._normalize_code(code) for code in codes}
            selected = [code for code in all_codes if code in normalized]
            # 列表里没有的代码也尝试更新（例如本地库尚无该股）。
            selected += [self.fetcher._normalize_code(code) for code in codes if self.fetcher._normalize_code(code) not in set(all_codes)]
            return list(dict.fromkeys(selected))
        if sample:
            return all_codes[:sample]
        if limit:
            return all_codes[:limit]
        return all_codes
