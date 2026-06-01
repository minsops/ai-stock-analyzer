from __future__ import annotations

import pandas as pd

from src.data_layer.cleaner import DataCleaner


def test_clean_quotes_normalizes_columns_and_types() -> None:
    cleaner = DataCleaner()
    raw = pd.DataFrame(
        {
            "日期": ["2026-01-02", "2026-01-01"],
            "开盘": ["10.1", "10.0"],
            "最高": ["10.5", "10.2"],
            "最低": ["9.8", "9.9"],
            "收盘": ["10.3", "10.1"],
            "成交量": ["1000", "900"],
            "成交额": ["1000000", "900000"],
            "换手率": ["1.2", "1.1"],
            "涨跌幅": ["2.0", "1.0"],
        }
    )

    cleaned = cleaner.clean_quotes(raw)

    assert list(cleaned.columns) == ["code", "trade_date", "open", "high", "low", "close", "volume", "amount", "turnover", "pct_change"]
    assert cleaned.iloc[0]["trade_date"].isoformat() == "2026-01-01"
    assert cleaned.iloc[0]["close"] == 10.1


def test_clean_financial_handles_missing_columns() -> None:
    cleaner = DataCleaner()
    raw = pd.DataFrame({"报告期": ["2025-03-15"], "净资产收益率": ["12.5%"]})

    cleaned = cleaner.clean_financial(raw)

    assert cleaned.iloc[0]["report_date"].isoformat() == "2025-03-31"
    assert cleaned.iloc[0]["roe"] == 12.5
    assert pd.isna(cleaned.iloc[0]["pe_ttm"])

