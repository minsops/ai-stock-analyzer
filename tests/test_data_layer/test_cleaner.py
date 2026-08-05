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


def test_clean_stocks_infers_market_and_marks_st() -> None:
    cleaner = DataCleaner()
    raw = pd.DataFrame(
        {
            "代码": ["600000", "000001", "830001", "bad"],
            "名称": ["浦发银行", "*ST示例", "北交示例", "无效代码"],
            "上市日期": ["1999-11-10", "1991-04-03", None, "2020-01-01"],
        }
    )

    cleaned = cleaner.clean_stocks(raw)

    assert cleaned["code"].tolist() == ["600000", "000001", "830001"]
    assert cleaned["market"].tolist() == ["SH", "SZ", "BJ"]
    assert cleaned["is_st"].tolist() == [False, True, False]
    assert cleaned["is_active"].all()


def test_clean_quotes_without_date_returns_empty_schema() -> None:
    cleaned = DataCleaner().clean_quotes(pd.DataFrame({"收盘": ["10.0"]}))

    assert cleaned.empty
    assert list(cleaned.columns) == [
        "code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turnover",
        "pct_change",
    ]


def test_clean_financial_drops_invalid_dates_and_keeps_latest_duplicate() -> None:
    raw = pd.DataFrame(
        {
            "报告期": ["2025-03-10", "2025-03-20", "invalid"],
            "股票代码": ["000001", "000001", "000001"],
            "市盈率(TTM)": ["12.0", "11.5", "9.0"],
            "股息率(TTM)": ["2.5%", "3.0%", "4.0%"],
        }
    )

    cleaned = DataCleaner().clean_financial(raw)

    assert len(cleaned) == 1
    assert cleaned.iloc[0]["report_date"].isoformat() == "2025-03-31"
    assert cleaned.iloc[0]["pe_ttm"] == 11.5
    assert cleaned.iloc[0]["dividend_yield"] == 3.0


def test_clean_capital_flow_handles_missing_metrics_and_invalid_date() -> None:
    raw = pd.DataFrame(
        {
            "日期": ["2026-01-02", "invalid"],
            "代码": ["000001", "000001"],
            "主力净流入-净额": ["1,200", "300"],
            "股东户数": ["10000", "bad"],
        }
    )

    cleaned = DataCleaner().clean_capital_flow(raw)

    assert len(cleaned) == 1
    assert cleaned.iloc[0]["main_net_inflow"] == 1200.0
    assert cleaned.iloc[0]["holder_count"] == 10000
    assert pd.isna(cleaned.iloc[0]["north_net_flow"])


def test_clean_industry_index_requires_code_and_date() -> None:
    raw = pd.DataFrame(
        {
            "板块代码": ["BK001", None],
            "板块名称": ["银行", "无代码"],
            "日期": ["2026-01-02", "2026-01-02"],
            "收盘": ["1,234.5", "100"],
        }
    )

    cleaned = DataCleaner().clean_industry_index(raw)

    assert len(cleaned) == 1
    assert cleaned.iloc[0]["industry_code"] == "BK001"
    assert cleaned.iloc[0]["close"] == 1234.5
    assert pd.isna(cleaned.iloc[0]["pct_change"])


def test_cleaners_return_stable_schemas_for_empty_inputs() -> None:
    cleaner = DataCleaner()

    assert list(cleaner.clean_stocks(pd.DataFrame()).columns)[0] == "code"
    assert list(cleaner.clean_financial(pd.DataFrame()).columns)[1] == "report_date"
    assert list(cleaner.clean_capital_flow(pd.DataFrame()).columns)[1] == "trade_date"
    assert list(cleaner.clean_industry_index(pd.DataFrame()).columns)[0] == "industry_code"
