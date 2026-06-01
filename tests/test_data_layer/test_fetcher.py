from __future__ import annotations

import pandas as pd

from src.data_layer.cache import DataCache
from src.data_layer.cleaner import DataCleaner
from src.data_layer.fetcher import StockDataFetcher


def test_fetcher_safe_call_returns_empty_dataframe_on_failure(tmp_path) -> None:
    fetcher = StockDataFetcher(cache=DataCache(tmp_path), cleaner=DataCleaner())

    def broken_call() -> pd.DataFrame:
        raise RuntimeError("network failed")

    result = fetcher._safe_call("测试失败接口", broken_call)

    assert result.empty


def test_fetcher_daily_quotes_uses_cache(tmp_path) -> None:
    cache = DataCache(tmp_path)
    cached = pd.DataFrame({"code": ["000001"], "trade_date": ["2026-01-01"], "close": [10.0]})
    cache.set("daily_quotes:000001:20260101:20260102:qfq", cached)
    fetcher = StockDataFetcher(cache=cache, cleaner=DataCleaner())

    result = fetcher.get_daily_quotes("000001", "20260101", "20260102")

    assert result.equals(cached)
