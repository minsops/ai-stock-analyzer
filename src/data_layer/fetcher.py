"""AKShare 数据拉取封装。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import time
from typing import Any, Callable, TypeVar

import pandas as pd
from loguru import logger

from config import settings
from src.data_layer.cache import DataCache
from src.data_layer.cleaner import DataCleaner


T = TypeVar("T")


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame()


class StockDataFetcher:
    """A 股数据拉取器，基于 AKShare。"""

    def __init__(self, cache: DataCache | None = None, cleaner: DataCleaner | None = None) -> None:
        self.cache = cache or DataCache()
        self.cleaner = cleaner or DataCleaner()
        self._ak: Any | None = None

    @property
    def ak(self) -> Any:
        if self._ak is None:
            import akshare as ak

            self._ak = ak
        return self._ak

    def get_stock_list(self, with_industry: bool = True) -> pd.DataFrame:
        """获取全部 A 股股票列表。

        with_industry=False 时跳过昂贵的行业成分股映射（按板块逐个拉取），
        适合只需要代码/名称的快速场景。
        """
        cache_key = f"stock_list:{date.today():%Y%m%d}:{'ind' if with_industry else 'noind'}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        df = self._safe_call("获取股票列表", "stock_zh_a_spot_em")
        if df.empty:
            return self.cleaner.clean_stocks(df)

        stocks = self.cleaner.clean_stocks(df)
        if with_industry:
            industry_map = self._get_industry_map()
            if industry_map:
                stocks["industry_l1"] = stocks["code"].map(industry_map).combine_first(stocks["industry_l1"])
        self.cache.set(cache_key, stocks)
        return stocks

    def get_daily_quotes(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取单只股票前复权日线数据。"""
        normalized_code = self._normalize_code(code)
        cache_key = f"daily_quotes:{normalized_code}:{start_date}:{end_date}:qfq"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        df = self._safe_call(
            f"获取日线数据 {normalized_code}",
            "stock_zh_a_hist",
            symbol=normalized_code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        cleaned = self.cleaner.clean_quotes(df)
        if not cleaned.empty:
            cleaned["code"] = normalized_code
            self.cache.set(cache_key, cleaned)
        return cleaned

    def get_financial_data(self, code: str) -> pd.DataFrame:
        """获取单只股票核心财务指标。"""
        normalized_code = self._normalize_code(code)
        cache_key = f"financial:{normalized_code}:{date.today():%Y%m%d}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        start_year = str(date.today().year - settings.VALUATION_LOOKBACK_YEARS - 1)
        indicator = self._safe_call(
            f"获取财务分析指标 {normalized_code}",
            "stock_financial_analysis_indicator",
            symbol=normalized_code,
            start_year=start_year,
        )
        # AKShare 1.18+ 已移除 legulegu 的 stock_a_lg_indicator，
        # 改用东方财富个股估值 stock_value_em（PE/PB/PS 等历史）。
        valuation = self._safe_call(
            f"获取估值指标 {normalized_code}",
            "stock_value_em",
            symbol=normalized_code,
        )

        financial = self.cleaner.clean_financial(indicator)
        valuation_cleaned = self.cleaner.clean_financial(valuation)
        merged = self._merge_financial_frames(financial, valuation_cleaned, normalized_code)
        if not merged.empty:
            self.cache.set(cache_key, merged)
        return merged

    def get_capital_flow(self, code: str, recent_days: int = 60) -> pd.DataFrame:
        """获取资金流向数据。"""
        normalized_code = self._normalize_code(code)
        cache_key = f"capital_flow:{normalized_code}:{recent_days}:{date.today():%Y%m%d}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        market = "sh" if normalized_code.startswith("6") else "sz"
        flow = self._safe_call(
            f"获取资金流向 {normalized_code}",
            "stock_individual_fund_flow",
            stock=normalized_code,
            market=market,
        )
        cleaned = self.cleaner.clean_capital_flow(flow)
        if not cleaned.empty:
            cleaned["code"] = normalized_code
            cleaned = cleaned.sort_values("trade_date").tail(recent_days)
            self.cache.set(cache_key, cleaned)
        return cleaned

    def get_industry_index(self, recent_days: int = 120) -> pd.DataFrame:
        """获取东方财富行业板块历史数据。"""
        cache_key = f"industry_index:{recent_days}:{date.today():%Y%m%d}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        boards = self._safe_call("获取行业板块列表", "stock_board_industry_name_em")
        if boards.empty:
            return self.cleaner.clean_industry_index(boards)

        frames: list[pd.DataFrame] = []
        for _, row in boards.iterrows():
            name = str(row.get("板块名称") or row.get("名称") or "")
            code = str(row.get("板块代码") or row.get("代码") or name)
            if not name:
                continue
            hist = self._safe_call(f"获取行业历史 {name}", "stock_board_industry_hist_em", symbol=name)
            if hist.empty:
                continue
            hist["板块代码"] = code
            hist["板块名称"] = name
            frames.append(hist.tail(recent_days))

        combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        cleaned = self.cleaner.clean_industry_index(combined)
        if not cleaned.empty:
            self.cache.set(cache_key, cleaned)
        return cleaned

    def get_market_overview(self) -> dict[str, Any]:
        """获取大盘概览数据，用于市场状态判断。"""
        cache_key = f"market_overview:{date.today():%Y%m%d}"
        cached = self.cache.get(cache_key)
        if cached is not None and not cached.empty:
            return cached.iloc[0].to_dict()

        end = date.today()
        start = end - timedelta(days=120)
        hs300 = self._safe_call(
            "获取沪深300指数",
            "stock_zh_index_daily",
            symbol="sh000300",
        )
        spot = self._safe_call("获取全市场快照", "stock_zh_a_spot_em")
        # 接口名按版本解析，缺失时 _safe_call 返回空。
        north = self._safe_call("获取北向资金", "stock_hsgt_north_net_flow_in_em")

        if not hs300.empty and "date" in hs300.columns:
            hs300["date"] = pd.to_datetime(hs300["date"], errors="coerce").dt.date
            hs300 = hs300[(hs300["date"] >= start) & (hs300["date"] <= end)]

        overview = {
            "as_of": end.isoformat(),
            "hs300": hs300.to_dict("records") if not hs300.empty else [],
            "advancers": int((pd.to_numeric(spot.get("涨跌幅", pd.Series(dtype=float)), errors="coerce") > 0).sum()) if not spot.empty else 0,
            "decliners": int((pd.to_numeric(spot.get("涨跌幅", pd.Series(dtype=float)), errors="coerce") < 0).sum()) if not spot.empty else 0,
            "northbound": north.tail(10).to_dict("records") if not north.empty else [],
        }
        if overview["hs300"] or overview["advancers"] or overview["decliners"] or overview["northbound"]:
            self.cache.set(cache_key, pd.DataFrame([overview]))
        return overview

    def _safe_call(self, description: str, func: Callable[..., pd.DataFrame] | str, *args: Any, **kwargs: Any) -> pd.DataFrame:
        # func 允许传 AKShare 接口名（字符串）：不同 AKShare 版本接口增删频繁，
        # 按名解析可在接口缺失时优雅降级为空数据，而不是抛 AttributeError 中断整条链路。
        resolved = getattr(self.ak, func, None) if isinstance(func, str) else func
        if resolved is None:
            logger.warning(f"{description}: 当前 AKShare 版本缺少接口 {func}，已跳过")
            return _empty_df()
        for attempt in range(1, settings.FETCH_RETRY_TIMES + 1):
            try:
                time.sleep(settings.FETCH_DELAY_SECONDS)
                df = resolved(*args, **kwargs)
                if df is None or df.empty:
                    logger.warning(f"{description} 返回空数据")
                    return _empty_df()
                return df
            except Exception as exc:  # noqa: BLE001 - 数据层吞掉外部接口异常
                logger.warning(f"{description} 失败，第 {attempt}/{settings.FETCH_RETRY_TIMES} 次: {exc}")
                if attempt < settings.FETCH_RETRY_TIMES:
                    time.sleep(settings.FETCH_RETRY_INTERVAL_SECONDS)
        logger.error(f"{description} 多次失败，返回空 DataFrame")
        return _empty_df()

    def _get_industry_map(self) -> dict[str, str]:
        cache_key = f"industry_map:{date.today():%Y%m%d}"
        cached = self.cache.get(cache_key)
        if cached is not None and not cached.empty:
            return dict(zip(cached["code"], cached["industry"], strict=False))

        boards = self._safe_call("获取行业板块列表", "stock_board_industry_name_em")
        mapping: dict[str, str] = {}
        if boards.empty:
            return mapping

        industries = [
            name
            for name in (str(row.get("板块名称") or row.get("名称") or "") for _, row in boards.iterrows())
            if name
        ]

        # 行业成分股逐板块拉取是整个数据更新最慢的一步（数十次网络请求），
        # 改为并发拉取以显著缩短首次建图时间。
        workers = max(1, settings.INDUSTRY_MAP_MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self._fetch_industry_constituents, name): name for name in industries}
            for future in as_completed(futures):
                industry = futures[future]
                for code in future.result():
                    mapping[code] = industry

        if mapping:
            self.cache.set(cache_key, pd.DataFrame({"code": list(mapping), "industry": list(mapping.values())}))
        return mapping

    def _fetch_industry_constituents(self, industry: str) -> list[str]:
        constituents = self._safe_call(
            f"获取行业成分股 {industry}", "stock_board_industry_cons_em", symbol=industry
        )
        if constituents.empty:
            return []
        code_column = (
            "代码" if "代码" in constituents.columns else "股票代码" if "股票代码" in constituents.columns else None
        )
        if code_column is None:
            return []
        return list(constituents[code_column].astype(str).str.extract(r"(\d{6})", expand=False).dropna())

    def _merge_financial_frames(self, financial: pd.DataFrame, valuation: pd.DataFrame, code: str) -> pd.DataFrame:
        if financial.empty and valuation.empty:
            return self.cleaner.clean_financial(pd.DataFrame())
        if financial.empty:
            result = valuation.copy()
        elif valuation.empty:
            result = financial.copy()
        else:
            result = pd.merge(financial, valuation, on=["code", "report_date"], how="outer", suffixes=("", "_valuation"))
            for column in list(result.columns):
                if column.endswith("_valuation"):
                    base = column.removesuffix("_valuation")
                    if base in result:
                        result[base] = result[base].combine_first(result[column])
                    else:
                        result[base] = result[column]
                    result = result.drop(columns=[column])
        result["code"] = code
        return result.sort_values("report_date")

    def _normalize_code(self, code: str) -> str:
        digits = "".join(ch for ch in str(code) if ch.isdigit())
        return digits[-6:] if len(digits) >= 6 else digits
