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


def test_regime_detector_degrades_when_market_data_is_missing() -> None:
    assert RegimeDetector().detect({}) == ("shock", 0.3, {"reason": "市场数据不足，默认震荡"})
    short = {"hs300": [{"close": value} for value in range(59)]}
    regime, confidence, details = RegimeDetector().detect(short)
    assert regime == "shock"
    assert confidence == 0.4
    assert "不足 60 日" in details["reason"]


def test_regime_detector_detects_extreme_fear() -> None:
    close = np.linspace(3000, 3600, 79).tolist() + [3400]
    market = {"hs300": [{"close": value} for value in close], "advancers": 500, "decliners": 3500}

    regime, confidence, _ = RegimeDetector().detect(market)

    assert regime == "extreme_fear"
    assert confidence == 0.85


def test_regime_detector_detects_extreme_greed() -> None:
    close = np.linspace(3000, 3500, 79).tolist() + [3650]
    market = {"hs300": [{"close": value} for value in close], "advancers": 3800, "decliners": 800}

    regime, confidence, _ = RegimeDetector().detect(market)

    assert regime == "extreme_greed"
    assert confidence == 0.8


def test_regime_detector_detects_bear_and_shock() -> None:
    falling = np.linspace(3600, 3000, 80)
    bear, _, _ = RegimeDetector().detect(
        {"hs300": [{"close": value} for value in falling], "advancers": 1000, "decliners": 3000}
    )
    shock, confidence, _ = RegimeDetector().detect(
        {"hs300": [{"close": value} for value in falling], "advancers": 3000, "decliners": 1000}
    )

    assert bear == "bear"
    assert shock == "shock"
    assert confidence == 0.65


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


def test_conflict_resolver_shock_uses_lower_score() -> None:
    scores = {"value": ScoreResult(80, 1.0), "trend": ScoreResult(35, 1.0)}

    result = ConflictResolver().resolve(scores, "shock")

    assert result["action"] == "adjusted"
    adjusted = result["adjusted_scores"]
    assert adjusted["value"].score == 35
    assert adjusted["trend"].score == 35
    assert adjusted["value"].confidence == 1.0
    assert adjusted["trend"].confidence == 1.0
    assert "震荡市冲突取较低分" in adjusted["value"].signals


def test_conflict_resolver_bull_prefers_trend_when_in_pair() -> None:
    scores = {"value": ScoreResult(35, 1.0), "trend": ScoreResult(80, 1.0)}

    result = ConflictResolver().resolve(scores, "bull")

    adjusted = result["adjusted_scores"]
    assert adjusted["value"].score == 80
    assert adjusted["trend"].score == 80
    assert "牛市冲突优先趋势分" in adjusted["value"].signals


def test_conflict_resolver_bear_prefers_value_when_in_pair() -> None:
    scores = {"value": ScoreResult(75, 1.0), "trend": ScoreResult(30, 1.0)}

    result = ConflictResolver().resolve(scores, "bear")

    adjusted = result["adjusted_scores"]
    assert adjusted["value"].score == 75
    assert adjusted["trend"].score == 75


def test_conflict_resolver_uses_lower_score_without_priority_engine() -> None:
    scores = {"industry": ScoreResult(75, 0.8), "event": ScoreResult(30, 0.9)}

    result = ConflictResolver().resolve(scores, "bull")

    adjusted = result["adjusted_scores"]
    assert adjusted["industry"].score == 30
    assert adjusted["event"].score == 30
    assert adjusted["industry"].confidence == 0.8


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


def test_ranker_builds_industry_context_with_return_and_volume_ranks() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    start = date(2025, 1, 1)
    frames = []
    for industry_code, industry_name, end_value, volume_end in (
        ("BK001", "银行", 130.0, 2000.0),
        ("BK002", "工业", 110.0, 1200.0),
    ):
        frames.append(
            pd.DataFrame(
                {
                    "industry_code": [industry_code] * 21,
                    "industry_name": [industry_name] * 21,
                    "trade_date": [start + timedelta(days=i) for i in range(21)],
                    "close": np.linspace(100.0, end_value, 21),
                    "volume": np.linspace(1000.0, volume_end, 21),
                }
            )
        )
    storage.upsert_industry_index(pd.concat(frames, ignore_index=True))
    ranker = StockRanker(
        fetcher=FakeFetcher(),  # type: ignore[arg-type]
        storage=storage,
        engines=[],
        regime_detector=RegimeDetector(),
        weight_manager=WeightManager(),
        conflict_resolver=ConflictResolver(),
        stock_filter=StockFilter(),
    )

    context = ranker._build_industry_context({"industry_l1": "银行"}, pd.DataFrame())

    assert np.isclose(context["return_20d"], 0.3)
    assert context["rank_percentile"] == 0.5
    assert context["fund_flow_percentile"] == 0.5
    assert ranker._build_industry_context({"industry_l1": None}, pd.DataFrame()) == {}
    assert ranker._build_industry_context({"industry_l1": "公用事业"}, pd.DataFrame()) == {}


def test_ranker_applies_configured_factor_tilt(monkeypatch) -> None:
    from config import settings

    storage = DataStorage("sqlite:///:memory:")
    ranker = StockRanker(
        fetcher=FakeFetcher(),  # type: ignore[arg-type]
        storage=storage,
        engines=[],
        regime_detector=RegimeDetector(),
        weight_manager=WeightManager(),
        conflict_resolver=ConflictResolver(),
        stock_filter=StockFilter(),
    )
    codes = [f"{index:06d}" for index in range(15)]
    frame = pd.DataFrame(
        {"code": codes, "industry": ["银行"] * 15, "composite_score": [50.0] * 15}
    )

    def fake_quotes(code: str, *args, **kwargs) -> pd.DataFrame:
        index = int(code)
        return pd.DataFrame(
            {
                "trade_date": pd.date_range("2025-01-01", periods=61),
                "close": np.linspace(10.0, 10.0 + index, 61),
                "amount": [10_000_000.0 + index * 100_000] * 61,
                "turnover": [1.0 + index / 100] * 61,
            }
        )

    def fake_financials(code: str) -> pd.DataFrame:
        index = int(code)
        return pd.DataFrame(
            {
                "report_date": [date(2025, 3, 31)],
                "pe_ttm": [5.0 + index],
                "roe": [30.0 - index],
                "profit_yoy": [40.0 - index],
            }
        )

    monkeypatch.setattr(settings, "FACTOR_TILT_STRENGTH", 4.0)
    monkeypatch.setattr(storage, "get_quotes", fake_quotes)
    monkeypatch.setattr(storage, "get_financial_history", fake_financials)

    tilted = ranker._apply_factor_tilt(frame)

    assert not tilted["composite_score"].equals(frame["composite_score"])
    assert tilted.loc[tilted["code"] == "000000", "composite_score"].iloc[0] > 50.0


def test_scan_all_skips_single_stock_failure(monkeypatch) -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    storage.upsert_stocks(
        pd.DataFrame(
            {
                "code": ["000001", "000002"],
                "name": ["股票A", "股票B"],
                "market": ["SZ", "SZ"],
                "is_active": [True, True],
            }
        )
    )
    ranker = StockRanker(
        fetcher=FakeFetcher(),  # type: ignore[arg-type]
        storage=storage,
        engines=[],
        regime_detector=RegimeDetector(),
        weight_manager=WeightManager(),
        conflict_resolver=ConflictResolver(),
        stock_filter=StockFilter(),
    )

    def fake_score(code: str, **kwargs) -> dict:
        if code == "000001":
            raise RuntimeError("bad stock")
        return {
            "code": code,
            "name": "股票B",
            "industry": None,
            "composite_score": 70.0,
            "engine_scores": {},
            "regime": "bull",
            "weights": {},
            "filter_passed": True,
            "quarantined": False,
        }

    monkeypatch.setattr(ranker, "score_single", fake_score)
    result = ranker.scan_all(top_n=5)

    assert result["code"].tolist() == ["000002"]
