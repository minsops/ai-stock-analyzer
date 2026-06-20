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

