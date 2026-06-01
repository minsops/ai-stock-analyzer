"""资金面评分引擎。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.engines.base_engine import BaseEngine, ScoreResult


class CapitalEngine(BaseEngine):
    """资金面评分引擎。"""

    WEIGHTS = {
        "main_net_inflow": 0.30,
        "north_net_flow": 0.20,
        "margin_balance": 0.20,
        "holder_count": 0.30,
    }

    @property
    def name(self) -> str:
        return "capital"

    def score(self, code: str, data: dict[str, Any]) -> ScoreResult:
        capital = data.get("capital")
        if not isinstance(capital, pd.DataFrame) or capital.empty:
            return ScoreResult(0.0, 0.0, {}, ["资金面数据不足，暂不参与综合评分"], False)
        c = capital.sort_values("trade_date").copy()
        scores: dict[str, float] = {}
        details: dict[str, Any] = {}
        signals: list[str] = []
        weights = self.WEIGHTS.copy()
        total_items = len(self.WEIGHTS)

        if "main_net_inflow" in c:
            values = pd.to_numeric(c["main_net_inflow"], errors="coerce").dropna().tail(5)
            if len(values) >= 3:
                total = values.sum()
                scores["main_net_inflow"] = 100.0 if total > 0 and values.iloc[-1] >= values.iloc[0] else 0.0 if total < 0 else 50.0
                details["main_net_inflow_5d"] = float(total)
                signals.append("主力近 5 日净流入" if total > 0 else "主力近 5 日净流出")
            else:
                scores["main_net_inflow"] = np.nan

        if "north_net_flow" in c and pd.to_numeric(c["north_net_flow"], errors="coerce").notna().any():
            north = pd.to_numeric(c["north_net_flow"], errors="coerce").dropna().tail(5).sum()
            scores["north_net_flow"] = 100.0 if north > 0 else 0.0 if north < 0 else 50.0
            details["north_net_flow_5d"] = float(north)
        else:
            weights.pop("north_net_flow", None)
            total_items -= 1
            scores["north_net_flow"] = np.nan
            signals.append("北向资金数据不可用")

        if "margin_balance" in c:
            margin = pd.to_numeric(c["margin_balance"], errors="coerce").dropna().tail(20)
            if len(margin) >= 2 and margin.iloc[0] != 0:
                change = margin.iloc[-1] / margin.iloc[0] - 1
                scores["margin_balance"] = 100.0 if change > 0.05 else 0.0 if change < -0.05 else 50.0
                details["margin_balance_change_20d"] = float(change)
            else:
                scores["margin_balance"] = np.nan

        if "holder_count" in c:
            holders = pd.to_numeric(c["holder_count"], errors="coerce").dropna().tail(2)
            if len(holders) >= 2 and holders.iloc[0] != 0:
                change = holders.iloc[-1] / holders.iloc[0] - 1
                scores["holder_count"] = 100.0 if change < -0.05 else 0.0 if change > 0.10 else 60.0
                details["holder_count_change"] = float(change)
            else:
                scores["holder_count"] = np.nan

        return self._weighted_result(scores, weights, details, signals, total_items=max(total_items, 1))

