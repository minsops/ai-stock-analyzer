from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.backtest import BacktestSimulator, PerformanceMetrics
from src.data_layer.storage import DataStorage


def test_performance_metrics_computes_basic_values() -> None:
    returns = pd.Series([0.01, -0.005, 0.002])

    result = PerformanceMetrics().compute(returns)

    assert result["trading_days"] == 3
    assert "max_drawdown" in result


def test_backtest_simulator_runs_with_price_data() -> None:
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
    start = date(2025, 1, 1)
    for idx, code in enumerate(["000001", "000002"]):
        close = np.linspace(10 + idx, 12 + idx, 80)
        storage.upsert_daily_quotes(
            pd.DataFrame(
                {
                    "code": [code] * 80,
                    "trade_date": [start + timedelta(days=i) for i in range(80)],
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": [1000] * 80,
                    "amount": [10_000_000] * 80,
                    "turnover": [1] * 80,
                    "pct_change": pd.Series(close).pct_change().fillna(0) * 100,
                }
            )
        )

    result = BacktestSimulator(storage).run({"start_date": "2025-01-01", "end_date": "2025-03-20", "top_n": 1})

    assert not result.equity_curve.empty
    assert result.metrics["trading_days"] > 0


def test_backtest_score_selection_uses_engines() -> None:
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
    start = date(2024, 6, 1)
    days = 200
    # 000001 持续上行（趋势更强），000002 持续下行
    for idx, (code, trend) in enumerate([("000001", 1.0), ("000002", -1.0)]):
        close = np.linspace(20, 20 + trend * 8, days)
        storage.upsert_daily_quotes(
            pd.DataFrame(
                {
                    "code": [code] * days,
                    "trade_date": [start + timedelta(days=i) for i in range(days)],
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": np.linspace(1000, 2000, days),
                    "amount": [10_000_000] * days,
                    "turnover": [1] * days,
                    "pct_change": pd.Series(close).pct_change().fillna(0) * 100,
                }
            )
        )

    result = BacktestSimulator(storage).run(
        {"start_date": "2024-06-01", "end_date": "2024-12-15", "top_n": 1, "selection": "score"}
    )

    assert not result.equity_curve.empty
    assert result.metrics["trading_days"] > 0
    # 最终调仓应当选中走势更强的 000001
    assert result.positions
    assert result.positions[-1]["holdings"] == ["000001"]
    # 调仓记录应带换手率(用于交易成本计算)，取值合理
    assert all(0.0 <= pos["turnover"] <= 1.0 for pos in result.positions)
    # 首次建仓(第一个有持仓的调仓日)应为全额买入
    first_with_holding = next(pos for pos in result.positions if pos["holdings"])
    assert first_with_holding["turnover"] == 1.0


def test_backtest_returns_empty_result_without_prices() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()

    result = BacktestSimulator(storage).run(
        {"start_date": "2025-01-01", "end_date": "2025-03-01"}
    )

    assert result.equity_curve.empty
    assert result.positions == []
    assert result.metrics["trading_days"] == 0


def test_backtest_helpers_use_point_in_time_membership_and_weekly_rebalance() -> None:
    simulator = BacktestSimulator(DataStorage("sqlite:///:memory:"))
    membership = {
        date(2025, 2, 1): {"000001"},
        date(2025, 3, 1): {"000002"},
    }
    dates = pd.date_range("2025-01-01", periods=15, freq="D")

    assert simulator._members_asof(membership, date(2025, 1, 1)) == {"000001"}
    assert simulator._members_asof(membership, date(2025, 3, 15)) == {"000002"}
    weekly = simulator._rebalance_dates(dates, "weekly")
    monthly = simulator._rebalance_dates(dates, "monthly")
    assert len(weekly) == 3
    assert monthly == {date(2025, 1, 1)}


def test_backtest_exposure_series_covers_market_regimes() -> None:
    simulator = BacktestSimulator(DataStorage("sqlite:///:memory:"))
    tiers = {"bull": 0.8, "bear": 0.4, "shock": 0.6, "extreme_fear": 0.2}
    index = pd.date_range("2025-01-01", periods=70, freq="D")

    rising = pd.DataFrame({"000001": np.linspace(100.0, 140.0, 70)}, index=index)
    falling = pd.DataFrame({"000001": np.linspace(140.0, 100.0, 70)}, index=index)
    panic_values = np.concatenate([np.linspace(100.0, 110.0, 66), [110.0, 108.0, 104.0, 99.0]])
    panic = pd.DataFrame({"000001": panic_values}, index=index)

    rising_exposure = simulator._exposure_series(rising, tiers)
    falling_exposure = simulator._exposure_series(falling, tiers)
    panic_exposure = simulator._exposure_series(panic, tiers)

    assert rising_exposure[index[0].date()] == 0.6
    assert rising_exposure[index[-1].date()] == 0.8
    assert falling_exposure[index[-1].date()] == 0.4
    assert panic_exposure[index[-1].date()] == 0.2


def test_backtest_composite_scores_fall_back_to_momentum_without_quotes() -> None:
    simulator = BacktestSimulator(DataStorage("sqlite:///:memory:"))
    index = pd.date_range("2025-01-01", periods=61, freq="D")
    prices = pd.DataFrame(
        {
            "000001": np.linspace(10.0, 15.0, 61),
            "000002": np.linspace(10.0, 11.0, 61),
        },
        index=index,
    )

    scores = simulator._composite_scores(
        prices,
        quotes_by_code={},
        financials_by_code={},
        stock_sector={},
        industry_hist=pd.DataFrame(),
        current_date=index[-1].date(),
        regime="shock",
    )

    assert scores.index.tolist() == ["000001", "000002"]
    assert scores.iloc[0] > scores.iloc[1]


def test_backtest_slices_financials_and_computes_industry_strength_as_of_date() -> None:
    simulator = BacktestSimulator(DataStorage("sqlite:///:memory:"))
    current = date(2025, 2, 1)
    financials = pd.DataFrame(
        {
            "report_date": [date(2024, 12, 31), date(2025, 3, 31)],
            "roe": [10.0, 20.0],
        }
    )
    start = date(2025, 1, 1)
    industry = pd.DataFrame(
        {
            "industry_name": ["银行"] * 22,
            "trade_date": [start + timedelta(days=i) for i in range(22)],
            "close": np.linspace(100.0, 121.0, 22),
        }
    )

    sliced = simulator._slice_financials(financials, current)
    returns, ranks = simulator._industry_strength_asof(industry, current)

    assert sliced["roe"].tolist() == [10.0]
    assert np.isclose(returns["银行"], 121.0 / 101.0 - 1)
    assert ranks == {"银行": 1.0}
    assert simulator._slice_financials(None, current).empty
