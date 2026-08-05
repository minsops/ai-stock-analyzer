from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

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


@pytest.fixture
def quotes_fixture() -> pd.DataFrame:
    return make_quotes()


@pytest.fixture
def financial_context_fixture() -> dict:
    return {
        "financial": {
            "pe_ttm": 10,
            "pb": 1.0,
            "roe": 15,
            "revenue_yoy": 20,
            "profit_yoy": 25,
            "dividend_yield": 3,
        },
        "financial_history": pd.DataFrame(
            {"pe_ttm": [8, 10, 12, 20], "pb": [0.8, 1.0, 1.2, 2.0]}
        ),
    }


def test_value_engine_scores_available_data(financial_context_fixture: dict) -> None:
    engine = ValueEngine()

    result = engine.score("000001", financial_context_fixture)

    assert result.available
    assert 0 <= result.score <= 100
    assert result.confidence == 1
    assert result.signals


def test_value_engine_marks_sparse_data_unavailable() -> None:
    result = ValueEngine().score("000001", {"financial": {"roe": 10}})

    assert not result.available
    assert result.confidence < 0.3


def test_value_engine_clips_extreme_metrics_to_score_boundaries() -> None:
    history = pd.DataFrame({"pe_ttm": [5, 10, 20], "pb": [0.5, 1.0, 2.0]})
    result = ValueEngine().score(
        "000001",
        {
            "financial": {
                "pe_ttm": 5,
                "pb": 0.5,
                "roe": 100,
                "revenue_yoy": 200,
                "profit_yoy": -100,
                "dividend_yield": 20,
            },
            "financial_history": history,
        },
    )

    assert result.available
    assert result.confidence == 1.0
    assert 0 <= result.score <= 100
    assert result.details["profit_yoy"] == -100


def test_trend_engine_scores_quotes(quotes_fixture: pd.DataFrame) -> None:
    result = TrendEngine().score("000001", {"quotes": quotes_fixture})

    assert result.available
    assert 0 <= result.score <= 100
    assert result.confidence >= 0.8


def test_trend_engine_handles_short_boundary_series() -> None:
    result = TrendEngine().score("000001", {"quotes": make_quotes(14)})

    assert result.available
    assert result.confidence == 0.3333
    assert 0 <= result.score <= 100


def test_trend_engine_is_unavailable_without_quotes() -> None:
    result = TrendEngine().score("000001", {"quotes": pd.DataFrame()})

    assert not result.available
    assert result.confidence == 0.0
    assert "数据不足" in result.signals[0]


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


def test_capital_engine_uses_volume_price_proxy_at_minimum_history() -> None:
    result = CapitalEngine().score("000001", {"capital": pd.DataFrame(), "quotes": make_quotes(20)})

    assert result.available
    assert result.confidence >= 0.75
    assert "量价代理" in result.signals[0]


def test_capital_engine_is_unavailable_without_capital_or_quotes() -> None:
    result = CapitalEngine().score("000001", {})

    assert not result.available
    assert result.score == 0.0
    assert "数据不足" in result.signals[0]


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


def test_industry_engine_clips_best_rank_boundary() -> None:
    result = IndustryEngine().score(
        "000001",
        {
            "quotes": pd.DataFrame(),
            "industry": {"rank_percentile": 0.0, "fund_flow_percentile": 0.0},
        },
    )

    assert result.available
    assert result.score == 100.0
    assert result.confidence == 0.6667


def test_industry_engine_is_unavailable_without_context() -> None:
    result = IndustryEngine().score("000001", {})

    assert not result.available
    assert result.confidence == 0.0


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


def test_event_engine_scores_limit_down_boundary_with_short_history() -> None:
    quotes = make_quotes(2)
    quotes["pct_change"] = [0.0, -10.0]

    result = EventEngine().score("000001", {"quotes": quotes})

    assert result.available
    assert result.score == 20.0
    assert result.confidence == 0.5
    assert result.details["limit_down_5d"] is True


def test_event_engine_is_unavailable_without_quotes() -> None:
    result = EventEngine().score("000001", {})

    assert not result.available
    assert result.score == 0.0
