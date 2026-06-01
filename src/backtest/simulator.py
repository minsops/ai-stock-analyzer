"""历史回测模拟器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from config import settings
from src.backtest.metrics import PerformanceMetrics
from src.data_layer.storage import DataStorage


@dataclass
class BacktestResult:
    """回测结果。"""

    equity_curve: pd.DataFrame
    positions: list[dict[str, Any]]
    metrics: dict[str, Any]


class BacktestSimulator:
    """阶段一基础回测模拟器。"""

    def __init__(self, storage: DataStorage) -> None:
        self.storage = storage
        self.metrics = PerformanceMetrics()

    def run(self, config: dict) -> BacktestResult:
        start_date = pd.to_datetime(config["start_date"]).date()
        end_date = pd.to_datetime(config["end_date"]).date()
        initial_capital = float(config.get("initial_capital", 100_000))
        top_n = int(config.get("top_n", 10))
        rebalance_freq = config.get("rebalance_freq", "monthly")

        codes = self.storage.get_all_active_codes()
        prices = self._load_price_panel(codes, start_date, end_date)
        if prices.empty:
            equity = pd.DataFrame({"trade_date": [], "equity": [], "daily_return": []})
            return BacktestResult(equity, [], self.metrics.compute(pd.Series(dtype=float)))

        rebalance_dates = self._rebalance_dates(prices.index, rebalance_freq)
        holdings: list[str] = []
        positions: list[dict[str, Any]] = []
        daily_returns: list[float] = []
        dates: list[date] = []

        returns = prices.pct_change().fillna(0)
        for current_date in prices.index:
            if current_date in rebalance_dates:
                momentum = self._momentum_scores(prices.loc[:current_date], lookback=60)
                holdings = momentum.head(top_n).index.tolist()
                positions.append({"date": current_date, "holdings": holdings})
            if holdings:
                day_return = float(returns.loc[current_date, holdings].mean())
                day_return -= settings.BACKTEST_COMMISSION_RATE if current_date in rebalance_dates else 0
            else:
                day_return = 0.0
            dates.append(current_date)
            daily_returns.append(day_return)

        returns_series = pd.Series(daily_returns, index=dates)
        equity_values = initial_capital * (1 + returns_series).cumprod()
        equity_curve = pd.DataFrame({"trade_date": dates, "equity": equity_values.values, "daily_return": daily_returns})
        metrics = self.metrics.compute(returns_series)
        return BacktestResult(equity_curve, positions, metrics)

    def _load_price_panel(self, codes: list[str], start_date: date, end_date: date) -> pd.DataFrame:
        frames: list[pd.Series] = []
        for code in codes:
            quotes = self.storage.get_quotes(code, start_date.isoformat(), end_date.isoformat())
            if quotes.empty:
                continue
            series = pd.to_numeric(quotes.set_index("trade_date")["close"], errors="coerce").rename(code)
            frames.append(series)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=1).sort_index().ffill().dropna(how="all")

    def _rebalance_dates(self, dates: pd.Index, freq: str) -> set:
        frame = pd.DataFrame(index=pd.to_datetime(dates))
        if freq == "weekly":
            selected = frame.groupby([frame.index.year, frame.index.isocalendar().week]).head(1).index
        else:
            selected = frame.groupby([frame.index.year, frame.index.month]).head(1).index
        return {item.date() for item in selected}

    def _momentum_scores(self, prices: pd.DataFrame, lookback: int) -> pd.Series:
        if len(prices) <= 1:
            return pd.Series(dtype=float)
        actual_lookback = min(lookback, len(prices) - 1)
        base = prices.iloc[-actual_lookback - 1]
        latest = prices.iloc[-1]
        return ((latest / base) - 1).dropna().sort_values(ascending=False)

