from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.engines import CapitalEngine, EventEngine, IndustryEngine, NewsEngine, TrendEngine, ValueEngine


def make_quotes(days: int = 160) -> pd.DataFrame:
    start = date(2025, 1, 1)
    close = np.linspace(10, 16, days)
    return pd.DataFrame(
        {
            "code": ["000001"] * days,
            "trade_date": [start + timedelta(days=i) for i in range(days)],
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": np.linspace(1000, 2000, days),
            "amount": np.linspace(1_000_000, 2_000_000, days),
            "turnover": np.linspace(1, 2, days),
            "pct_change": pd.Series(close).pct_change().fillna(0) * 100,
        }
    )


def test_value_engine_scores_available_data() -> None:
    engine = ValueEngine()
    history = pd.DataFrame({"pe_ttm": [8, 10, 12, 20], "pb": [0.8, 1.0, 1.2, 2.0]})
    data = {
        "financial": {"pe_ttm": 10, "pb": 1.0, "roe": 15, "revenue_yoy": 20, "profit_yoy": 25, "dividend_yield": 3},
        "financial_history": history,
    }

    result = engine.score("000001", data)

    assert result.available
    assert 0 <= result.score <= 100
    assert result.confidence == 1
    assert result.signals


def test_value_engine_marks_sparse_data_unavailable() -> None:
    result = ValueEngine().score("000001", {"financial": {"roe": 10}})

    assert not result.available
    assert result.confidence < 0.3


def test_trend_engine_scores_quotes() -> None:
    result = TrendEngine().score("000001", {"quotes": make_quotes()})

    assert result.available
    assert 0 <= result.score <= 100
    assert result.confidence >= 0.8


def test_capital_engine_handles_missing_northbound_neutrally() -> None:
    capital = pd.DataFrame(
        {
            "trade_date": [date(2026, 1, i + 1) for i in range(20)],
            "main_net_inflow": np.linspace(1, 5, 20),
            "margin_balance": np.linspace(100, 110, 20),
            "holder_count": [1000] * 19 + [930],
        }
    )

    result = CapitalEngine().score("000001", {"capital": capital})

    assert result.available
    assert "北向资金数据不可用" in result.signals
    assert result.confidence == 1


def test_industry_engine_scores_supplied_industry_context() -> None:
    result = IndustryEngine().score(
        "000001",
        {
            "quotes": make_quotes(40),
            "industry": {"rank_percentile": 0.1, "fund_flow_percentile": 0.2, "return_20d": 0.05},
        },
    )

    assert result.available
    assert 0 <= result.score <= 100


def test_news_engine_scores_positive_and_negative() -> None:
    bullish = NewsEngine().score("000001", {"news": [
        {"title": "某公司关于回购股份的公告"}, {"title": "某公司中标重大项目"}, {"title": "业绩预增公告"},
    ]})
    bearish = NewsEngine().score("000001", {"news": [
        {"title": "控股股东减持公告"}, {"title": "关于收到监管问询函的公告"}, {"title": "公司涉及诉讼"},
    ]})

    assert bullish.available and bearish.available
    assert bullish.score > 60 and bearish.score < 40
    assert bullish.details["positive"] >= 2 and bearish.details["negative"] >= 2


def test_news_engine_unavailable_without_news() -> None:
    result = NewsEngine().score("000001", {"news": []})

    assert not result.available


def test_event_engine_scores_limit_and_volatility() -> None:
    quotes = make_quotes(10)
    quotes.loc[quotes.index[-2], "pct_change"] = 10.0

    result = EventEngine().score("000001", {"quotes": quotes})

    assert result.available
    assert result.details["limit_up_5d"] is True
