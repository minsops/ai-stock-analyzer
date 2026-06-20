from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.data_layer.storage import DataStorage
from src.engines import CapitalEngine, EventEngine, IndustryEngine, ScoreResult, TrendEngine, ValueEngine
from src.fusion import ConflictResolver, RegimeDetector, StockFilter, StockRanker, WeightManager
from src.valuation import HistoricalValuation


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
            "amount": np.linspace(10_000_000, 20_000_000, days),
            "turnover": np.linspace(1, 2, days),
            "pct_change": pd.Series(close).pct_change().fillna(0) * 100,
        }
    )


def make_market_data() -> dict:
    close = np.linspace(3000, 3600, 80)
    return {
        "hs300": [{"date": str(date(2025, 1, 1) + timedelta(days=i)), "close": value} for i, value in enumerate(close)],
        "advancers": 3200,
        "decliners": 1200,
    }


def test_regime_detector_detects_bull() -> None:
    regime, confidence, details = RegimeDetector().detect(make_market_data())

    assert regime == "bull"
    assert confidence > 0.5
    assert "ma20" in details


def test_weight_manager_ignores_unavailable_scores() -> None:
    scores = {
        "value": ScoreResult(80, 1.0),
        "trend": ScoreResult(20, 0.0, available=False),
    }

    assert WeightManager().compute_composite(scores, "shock") == 80


def test_conflict_resolver_quarantines_large_gap() -> None:
    scores = {"value": ScoreResult(90, 1.0), "trend": ScoreResult(20, 1.0)}

    result = ConflictResolver().resolve(scores, "shock")

    assert result["action"] == "quarantine"


def test_conflict_resolver_downweights_instead_of_min() -> None:
    # 分歧但未到隔离阈值(gap 45)：保守状态应保留分数、下调置信度(降权)，而非取最小。
    scores = {"value": ScoreResult(80, 1.0), "trend": ScoreResult(35, 1.0)}

    result = ConflictResolver().resolve(scores, "shock")

    assert result["action"] == "adjusted"
    adjusted = result["adjusted_scores"]
    # 分数保留(不被抹平到最小值)
    assert adjusted["value"].score == 80
    assert adjusted["trend"].score == 35
    # 置信度被下调
    assert adjusted["value"].confidence < 1.0
    assert adjusted["trend"].confidence < 1.0


def test_stock_filter_rejects_low_liquidity() -> None:
    quotes = make_quotes(30)
    quotes["amount"] = 1000

    passed, reason = StockFilter().apply("000001", {"name": "平安银行", "is_st": False}, quotes)

    assert not passed
    assert "日均成交额" in reason


def test_historical_valuation_computes_percentile() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    financial = pd.DataFrame(
        {
            "code": ["000001"] * 4,
            "report_date": [date(2024, 3, 31), date(2024, 6, 30), date(2024, 9, 30), date(2024, 12, 31)],
            "pe_ttm": [10, 12, 14, 11],
        }
    )
    storage.upsert_financial_data(financial)

    result = HistoricalValuation(storage).compute_percentile("000001", "pe_ttm")

    assert result["current_value"] == 11
    assert 0 < result["percentile"] <= 1


class FakeFetcher:
    calls = 0

    def get_market_overview(self) -> dict:
        self.calls += 1
        return make_market_data()


def test_ranker_score_single_returns_report() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    storage.upsert_stocks(
        pd.DataFrame(
            {
                "code": ["000001"],
                "name": ["平安银行"],
                "market": ["SZ"],
                "industry_l1": ["银行"],
                "industry_l2": [None],
                "list_date": [date(1991, 4, 3)],
                "is_st": [False],
                "is_active": [True],
            }
        )
    )
    storage.upsert_daily_quotes(make_quotes())
    storage.upsert_financial_data(
        pd.DataFrame(
            {
                "code": ["000001"] * 4,
                "report_date": [date(2024, 3, 31), date(2024, 6, 30), date(2024, 9, 30), date(2024, 12, 31)],
                "pe_ttm": [10, 12, 14, 11],
                "pb": [1.0, 1.1, 1.2, 1.05],
                "roe": [12, 13, 14, 15],
                "revenue_yoy": [10, 12, 14, 16],
                "profit_yoy": [8, 10, 11, 13],
                "dividend_yield": [2, 2.2, 2.5, 2.8],
            }
        )
    )
    storage.upsert_capital_flow(
        pd.DataFrame(
            {
                "code": ["000001"] * 20,
                "trade_date": [date(2025, 1, 1) + timedelta(days=i) for i in range(20)],
                "main_net_inflow": np.linspace(1, 5, 20),
                "margin_balance": np.linspace(100, 110, 20),
                "holder_count": [1000] * 19 + [930],
            }
        )
    )
    ranker = StockRanker(
        fetcher=FakeFetcher(),  # type: ignore[arg-type]
        storage=storage,
        engines=[ValueEngine(), TrendEngine(), CapitalEngine(), IndustryEngine(), EventEngine()],
        regime_detector=RegimeDetector(),
        weight_manager=WeightManager(),
        conflict_resolver=ConflictResolver(),
        stock_filter=StockFilter(),
    )

    report = ranker.score_single("000001")

    assert report["code"] == "000001"
    assert report["filter_passed"]
    assert "engine_scores" in report


def test_scan_all_reuses_single_market_detection_and_saves_scores() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    storage.upsert_stocks(
        pd.DataFrame(
            {
                "code": ["000001", "000002"],
                "name": ["平安银行", "万科A"],
                "market": ["SZ", "SZ"],
                "industry_l1": ["银行", "地产"],
                "industry_l2": [None, None],
                "list_date": [date(1991, 4, 3), date(1991, 1, 29)],
                "is_st": [False, False],
                "is_active": [True, True],
            }
        )
    )
    q1 = make_quotes()
    q2 = make_quotes()
    q2["code"] = "000002"
    storage.upsert_daily_quotes(pd.concat([q1, q2], ignore_index=True))
    fetcher = FakeFetcher()
    ranker = StockRanker(
        fetcher=fetcher,  # type: ignore[arg-type]
        storage=storage,
        engines=[TrendEngine(), EventEngine()],
        regime_detector=RegimeDetector(),
        weight_manager=WeightManager(),
        conflict_resolver=ConflictResolver(),
        stock_filter=StockFilter(),
    )

    result = ranker.scan_all(top_n=2)
    top_scores = storage.get_top_scores(date.today().isoformat(), top_n=2)

    assert fetcher.calls == 1
    assert len(result) == 2
    assert set(top_scores["name"]) == {"平安银行", "万科A"}
    assert storage.get_latest_market_regime()["regime"] == "bull"
