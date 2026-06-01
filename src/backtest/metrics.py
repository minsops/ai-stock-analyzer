"""回测绩效指标。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import settings


class PerformanceMetrics:
    """计算回测绩效指标。"""

    def compute(self, daily_returns: pd.Series, benchmark_returns: pd.Series | None = None) -> dict:
        returns = pd.to_numeric(daily_returns, errors="coerce").fillna(0)
        benchmark = pd.to_numeric(benchmark_returns, errors="coerce").fillna(0) if benchmark_returns is not None else pd.Series(0, index=returns.index)
        if returns.empty:
            return {
                "total_return": 0.0,
                "annual_return": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "win_rate": 0.0,
                "profit_loss_ratio": 0.0,
                "alpha": 0.0,
                "beta": 0.0,
                "calmar_ratio": 0.0,
                "trading_days": 0,
                "total_trades": 0,
            }

        equity = (1 + returns).cumprod()
        total_return = float(equity.iloc[-1] - 1)
        trading_days = len(returns)
        annual_return = float((1 + total_return) ** (252 / trading_days) - 1) if trading_days else 0.0
        drawdown = equity / equity.cummax() - 1
        max_drawdown = float(drawdown.min())
        excess = returns - settings.RISK_FREE_RATE / 252
        sharpe = float(excess.mean() / returns.std() * np.sqrt(252)) if returns.std() else 0.0
        downside = returns[returns < 0].std()
        sortino = float(excess.mean() / downside * np.sqrt(252)) if downside else 0.0
        win_rate = float((returns > 0).mean())
        gains = returns[returns > 0]
        losses = returns[returns < 0]
        profit_loss_ratio = float(gains.mean() / abs(losses.mean())) if not gains.empty and not losses.empty and losses.mean() else 0.0
        aligned = pd.concat([returns, benchmark.reindex(returns.index).fillna(0)], axis=1).dropna()
        aligned.columns = ["strategy", "benchmark"]
        beta = float(aligned.cov().iloc[0, 1] / aligned["benchmark"].var()) if aligned["benchmark"].var() else 0.0
        alpha = float(annual_return - (settings.RISK_FREE_RATE + beta * ((1 + aligned["benchmark"]).prod() ** (252 / len(aligned)) - 1 - settings.RISK_FREE_RATE))) if len(aligned) else 0.0
        calmar = float(annual_return / abs(max_drawdown)) if max_drawdown else 0.0

        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "win_rate": win_rate,
            "profit_loss_ratio": profit_loss_ratio,
            "alpha": alpha,
            "beta": beta,
            "calmar_ratio": calmar,
            "trading_days": trading_days,
            "total_trades": int((returns != 0).sum()),
        }

