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

