from __future__ import annotations

from datetime import date

import pandas as pd

from src.data_layer.storage import DataStorage


def test_storage_upserts_and_reads_quotes() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    quotes = pd.DataFrame(
        {
            "code": ["000001", "000001"],
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
            "open": [10.0, 10.1],
            "high": [10.2, 10.3],
            "low": [9.9, 10.0],
            "close": [10.1, 10.2],
            "volume": [1000.0, 1200.0],
            "amount": [1000000.0, 1200000.0],
            "turnover": [1.1, 1.2],
            "pct_change": [1.0, 0.99],
        }
    )

    count = storage.upsert_daily_quotes(quotes)
    loaded = storage.get_quotes("000001")

    assert count == 2
    assert len(loaded) == 2
    assert loaded.iloc[-1]["close"] == 10.2


def test_storage_skips_empty_dataframe() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()

    assert storage.upsert_daily_quotes(pd.DataFrame()) == 0


def test_storage_upserts_large_batch_without_variable_limit() -> None:
    """整张股票列表(数千行)一次写入不应触发 SQLite 'too many SQL variables'。"""
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    n = 3000
    stocks = pd.DataFrame(
        {
            "code": [f"{i:06d}" for i in range(n)],
            "name": [f"股票{i}" for i in range(n)],
            "market": ["SZ"] * n,
            "is_active": [True] * n,
        }
    )

    count = storage.upsert_stocks(stocks)

    assert count == n
    assert len(storage.get_all_active_codes()) == n


def test_upsert_fundamentals_preserves_valuation_rows() -> None:
    """回填季度基本面只更新基本面列，不应抹掉已有的估值(pe/pb)行。"""
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    # 先写一行月度估值(report_date 与待回填的 pubDate 相同 → 测试冲突更新)
    storage.upsert_financial_data(pd.DataFrame({
        "code": ["000001"],
        "report_date": [date(2024, 4, 29)],
        "pe_ttm": [12.3], "pb": [1.1],
    }))
    # 回填同日的季度基本面(只给基本面列)
    n = storage.upsert_fundamentals(pd.DataFrame({
        "code": ["000001", "000001"],
        "report_date": [date(2024, 4, 29), date(2024, 8, 30)],
        "roe": [11.0, 18.0], "profit_yoy": [5.0, 6.0], "gross_margin": [40.0, 41.0],
    }))
    assert n == 2
    hist = storage.get_financial_history("000001").set_index("report_date")
    # 冲突日:估值保留、基本面写入
    assert hist.loc[date(2024, 4, 29), "pe_ttm"] == 12.3
    assert hist.loc[date(2024, 4, 29), "roe"] == 11.0
    # 新日:基本面写入、估值为空
    assert hist.loc[date(2024, 8, 30), "roe"] == 18.0
    assert pd.isna(hist.loc[date(2024, 8, 30), "pe_ttm"])

