from __future__ import annotations

import pandas as pd

from src.data_layer.cache import DataCache
from src.data_layer.cleaner import DataCleaner
from src.data_layer.fetcher import StockDataFetcher


def _disable_fetch_waits(monkeypatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "FETCH_DELAY_SECONDS", 0)
    monkeypatch.setattr(settings, "FETCH_RETRY_INTERVAL_SECONDS", 0)


def test_fetcher_safe_call_returns_empty_dataframe_on_failure(tmp_path, monkeypatch) -> None:
    from config import settings

    _disable_fetch_waits(monkeypatch)
    monkeypatch.setattr(settings, "FETCH_RETRY_TIMES", 3)
    fetcher = StockDataFetcher(cache=DataCache(tmp_path), cleaner=DataCleaner())
    attempts = 0

    def broken_call() -> pd.DataFrame:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("network failed")

    result = fetcher._safe_call("测试失败接口", broken_call)

    assert result.empty
    assert attempts == 3


def test_fetcher_daily_quotes_uses_cache(tmp_path) -> None:
    cache = DataCache(tmp_path)
    cached = pd.DataFrame({"code": ["000001"], "trade_date": ["2026-01-01"], "close": [10.0]})
    cache.set("daily_quotes:000001:20260101:20260102:qfq", cached)
    fetcher = StockDataFetcher(cache=cache, cleaner=DataCleaner())

    result = fetcher.get_daily_quotes("000001", "20260101", "20260102")

    assert result.equals(cached)


def test_fetcher_does_not_cache_empty_quote_response(tmp_path, monkeypatch) -> None:
    from config import settings

    class FakeAk:
        def stock_zh_a_hist(self, **kwargs) -> pd.DataFrame:
            return pd.DataFrame()

    monkeypatch.setattr(settings, "FETCH_DELAY_SECONDS", 0)
    monkeypatch.setattr(settings, "FETCH_RETRY_TIMES", 1)
    cache = DataCache(tmp_path)
    fetcher = StockDataFetcher(cache=cache, cleaner=DataCleaner())
    fetcher._ak = FakeAk()

    result = fetcher.get_daily_quotes("000001", "20260101", "20260102")

    assert result.empty
    assert not cache.is_fresh("daily_quotes:000001:20260101:20260102:qfq")


def test_fetcher_daily_quotes_falls_back_to_tencent_source(tmp_path, monkeypatch) -> None:
    from config import settings

    class FakeAk:
        tx_kwargs: dict | None = None

        def stock_zh_a_hist(self, **kwargs) -> pd.DataFrame:
            raise ConnectionError("eastmoney disconnected")

        def stock_zh_a_hist_tx(self, **kwargs) -> pd.DataFrame:
            self.tx_kwargs = kwargs
            return pd.DataFrame(
                {
                    "date": ["2026-01-02"],
                    "open": [10.0],
                    "close": [10.3],
                    "high": [10.5],
                    "low": [9.9],
                    "amount": [123_456],
                }
            )

    _disable_fetch_waits(monkeypatch)
    monkeypatch.setattr(settings, "FETCH_RETRY_TIMES", 1)
    cache = DataCache(tmp_path)
    fetcher = StockDataFetcher(cache=cache, cleaner=DataCleaner())
    fetcher._ak = FakeAk()

    result = fetcher.get_daily_quotes("SZ000001", "20260101", "20260103")

    assert result.iloc[0]["code"] == "000001"
    assert result.iloc[0]["trade_date"].isoformat() == "2026-01-02"
    assert result.iloc[0]["close"] == 10.3
    assert result.iloc[0]["volume"] == 123_456
    assert pd.isna(result.iloc[0]["amount"])
    assert fetcher._ak.tx_kwargs == {
        "symbol": "sz000001",
        "start_date": "20260101",
        "end_date": "20260103",
        "adjust": "qfq",
        "timeout": settings.FETCH_TIMEOUT_SECONDS,
    }


def test_fetcher_safe_call_retries_then_returns_data(tmp_path, monkeypatch) -> None:
    from config import settings

    _disable_fetch_waits(monkeypatch)
    monkeypatch.setattr(settings, "FETCH_RETRY_TIMES", 3)
    fetcher = StockDataFetcher(cache=DataCache(tmp_path), cleaner=DataCleaner())
    attempts = 0

    def flaky_call() -> pd.DataFrame:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("temporary")
        return pd.DataFrame({"ok": [1]})

    result = fetcher._safe_call("测试重试接口", flaky_call)

    assert result.to_dict("records") == [{"ok": 1}]
    assert attempts == 3


def test_fetcher_missing_akshare_interface_degrades_to_empty(tmp_path, monkeypatch) -> None:
    _disable_fetch_waits(monkeypatch)
    fetcher = StockDataFetcher(cache=DataCache(tmp_path), cleaner=DataCleaner())
    fetcher._ak = object()

    assert fetcher._safe_call("不存在接口", "missing_method").empty


def test_fetcher_stock_list_applies_industry_mapping_and_cache(tmp_path, monkeypatch) -> None:
    _disable_fetch_waits(monkeypatch)

    class FakeAk:
        calls = 0

        def stock_zh_a_spot_em(self) -> pd.DataFrame:
            self.calls += 1
            return pd.DataFrame({"代码": ["000001", "600000"], "名称": ["平安银行", "浦发银行"]})

    cache = DataCache(tmp_path)
    fetcher = StockDataFetcher(cache=cache, cleaner=DataCleaner())
    fetcher._ak = FakeAk()
    monkeypatch.setattr(fetcher, "_get_industry_map", lambda: {"000001": "银行"})

    first = fetcher.get_stock_list(with_industry=True)
    second = fetcher.get_stock_list(with_industry=True)

    assert first.loc[first["code"] == "000001", "industry_l1"].iloc[0] == "银行"
    assert pd.isna(first.loc[first["code"] == "600000", "industry_l1"].iloc[0])
    assert second.equals(first)
    assert fetcher._ak.calls == 1


def test_fetcher_merges_financial_and_valuation_data(tmp_path, monkeypatch) -> None:
    _disable_fetch_waits(monkeypatch)

    class FakeAk:
        def stock_financial_analysis_indicator(self, **kwargs) -> pd.DataFrame:
            return pd.DataFrame({"日期": ["2025-03-31"], "净资产收益率": [12.0]})

        def stock_value_em(self, **kwargs) -> pd.DataFrame:
            return pd.DataFrame({"数据日期": ["2025-03-31"], "PE(TTM)": [10.5], "市净率": [1.2]})

    fetcher = StockDataFetcher(cache=DataCache(tmp_path), cleaner=DataCleaner())
    fetcher._ak = FakeAk()

    result = fetcher.get_financial_data("SZ000001")

    assert len(result) == 1
    assert result.iloc[0]["code"] == "000001"
    assert result.iloc[0]["roe"] == 12.0
    assert result.iloc[0]["pe_ttm"] == 10.5


def test_fetcher_capital_flow_normalizes_market_and_limits_days(tmp_path, monkeypatch) -> None:
    _disable_fetch_waits(monkeypatch)

    class FakeAk:
        received: dict | None = None

        def stock_individual_fund_flow(self, **kwargs) -> pd.DataFrame:
            self.received = kwargs
            return pd.DataFrame(
                {
                    "日期": ["2026-01-01", "2026-01-02", "2026-01-03"],
                    "主力净流入净额": [1, 2, 3],
                }
            )

    fetcher = StockDataFetcher(cache=DataCache(tmp_path), cleaner=DataCleaner())
    fetcher._ak = FakeAk()

    result = fetcher.get_capital_flow("sh600000", recent_days=2)

    assert result["trade_date"].map(str).tolist() == ["2026-01-02", "2026-01-03"]
    assert result["code"].tolist() == ["600000", "600000"]
    assert fetcher._ak.received == {"stock": "600000", "market": "sh"}


def test_fetcher_industry_index_skips_empty_boards_and_caches(tmp_path, monkeypatch) -> None:
    _disable_fetch_waits(monkeypatch)

    class FakeAk:
        hist_calls = 0

        def stock_board_industry_name_em(self) -> pd.DataFrame:
            return pd.DataFrame({"板块名称": ["银行", ""], "板块代码": ["BK001", "BK000"]})

        def stock_board_industry_hist_em(self, symbol: str) -> pd.DataFrame:
            self.hist_calls += 1
            return pd.DataFrame({"日期": ["2026-01-01", "2026-01-02"], "收盘": [100, 101]})

    fetcher = StockDataFetcher(cache=DataCache(tmp_path), cleaner=DataCleaner())
    fetcher._ak = FakeAk()

    first = fetcher.get_industry_index(recent_days=1)
    second = fetcher.get_industry_index(recent_days=1)

    assert len(first) == 1
    assert first.iloc[0]["industry_name"] == "银行"
    assert second.equals(first)
    assert fetcher._ak.hist_calls == 1


def test_fetcher_market_overview_handles_unavailable_northbound(tmp_path, monkeypatch) -> None:
    _disable_fetch_waits(monkeypatch)

    class FakeAk:
        def stock_zh_index_daily(self, **kwargs) -> pd.DataFrame:
            return pd.DataFrame({"date": [pd.Timestamp.today().date()], "close": [4000.0]})

        def stock_zh_a_spot_em(self) -> pd.DataFrame:
            return pd.DataFrame({"涨跌幅": [1.0, -2.0, 0.0]})

    fetcher = StockDataFetcher(cache=DataCache(tmp_path), cleaner=DataCleaner())
    fetcher._ak = FakeAk()

    overview = fetcher.get_market_overview()

    assert overview["advancers"] == 1
    assert overview["decliners"] == 1
    assert overview["northbound"] == []
    assert len(overview["hs300"]) == 1


def test_fetcher_builds_and_reuses_industry_map(tmp_path, monkeypatch) -> None:
    from config import settings

    _disable_fetch_waits(monkeypatch)
    monkeypatch.setattr(settings, "INDUSTRY_MAP_MAX_WORKERS", 1)

    class FakeAk:
        constituent_calls = 0

        def stock_board_industry_name_em(self) -> pd.DataFrame:
            return pd.DataFrame({"板块名称": ["银行"]})

        def stock_board_industry_cons_em(self, symbol: str) -> pd.DataFrame:
            self.constituent_calls += 1
            return pd.DataFrame({"代码": ["000001", "600000"]})

    fetcher = StockDataFetcher(cache=DataCache(tmp_path), cleaner=DataCleaner())
    fetcher._ak = FakeAk()

    first = fetcher._get_industry_map()
    second = fetcher._get_industry_map()

    assert first == {"000001": "银行", "600000": "银行"}
    assert second == first
    assert fetcher._ak.constituent_calls == 1
