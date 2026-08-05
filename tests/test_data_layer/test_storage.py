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


def test_storage_round_trips_financial_capital_and_industry_data() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    storage.upsert_financial_data(
        pd.DataFrame(
            {
                "code": ["000001", "000001"],
                "report_date": [date(2025, 3, 31), date(2025, 6, 30)],
                "pe_ttm": [10.0, 11.0],
                "roe": [12.0, 13.0],
            }
        )
    )
    storage.upsert_capital_flow(
        pd.DataFrame(
            {
                "code": ["000001"],
                "trade_date": [date(2025, 7, 1)],
                "main_net_inflow": [1_000_000.0],
            }
        )
    )
    storage.upsert_industry_index(
        pd.DataFrame(
            {
                "industry_code": ["BK001"],
                "industry_name": ["银行"],
                "trade_date": [date(2025, 7, 1)],
                "close": [1200.0],
            }
        )
    )

    assert storage.get_latest_financial("000001")["report_date"] == date(2025, 6, 30)
    assert storage.get_latest_financial("missing") == {}
    assert storage.get_capital_flow("000001").iloc[0]["main_net_inflow"] == 1_000_000.0
    assert storage.get_industry_history("银行").iloc[0]["close"] == 1200.0
    assert len(storage.get_all_industry_history()) == 1


def test_storage_saves_scores_and_falls_back_to_latest_score_date() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    storage.upsert_stocks(
        pd.DataFrame(
            {
                "code": ["000001", "000002"],
                "name": ["股票A", "股票B"],
                "market": ["SZ", "SZ"],
                "is_active": [True, False],
            }
        )
    )
    score_date = date(2025, 7, 1)
    count = storage.save_scores(
        pd.DataFrame(
            {
                "code": ["000001"],
                "score_date": [score_date],
                "composite_score": [88.0],
                "regime": ["bull"],
                "weights": [{"value": 0.4, "trend": 0.6}],
            }
        )
    )

    top = storage.get_top_scores("2025-07-02", top_n=5)

    assert count == 1
    assert top.iloc[0]["score_date"] == score_date
    assert top.iloc[0]["name"] == "股票A"
    assert '"value": 0.4' in top.iloc[0]["weights_json"]
    assert storage.get_latest_score("000001")["composite_score"] == 88.0
    assert storage.get_latest_score("missing") == {}
    assert storage.get_all_active_codes() == ["000001"]
    assert storage.get_active_stocks()["code"].tolist() == ["000001"]


def test_storage_saves_latest_market_regime() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()

    assert storage.get_latest_market_regime() == {}
    assert storage.save_market_regime(date(2025, 7, 1), "bear", 0.75, {"breadth": 0.3}) == 1

    latest = storage.get_latest_market_regime()
    assert latest["regime"] == "bear"
    assert '"breadth": 0.3' in latest["details_json"]


def test_storage_ignores_rows_with_missing_primary_key() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()

    count = storage.upsert_daily_quotes(
        pd.DataFrame(
            {
                "code": ["000001", None],
                "trade_date": [pd.Timestamp("2025-07-01"), pd.Timestamp("2025-07-01")],
                "close": [10.0, 20.0],
            }
        )
    )

    assert count == 1
    assert storage.get_quotes("000001").iloc[0]["trade_date"] == date(2025, 7, 1)
