"""市场状态识别。"""

from __future__ import annotations

from typing import Any

import pandas as pd


class RegimeDetector:
    """市场状态识别器。"""

    def detect(self, market_data: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        hs300 = pd.DataFrame(market_data.get("hs300", []))
        details: dict[str, Any] = {}
        if hs300.empty or "close" not in hs300:
            return "shock", 0.3, {"reason": "市场数据不足，默认震荡"}

        hs300 = hs300.copy()
        hs300["close"] = pd.to_numeric(hs300["close"], errors="coerce")
        close = hs300["close"].dropna()
        if len(close) < 60:
            return "shock", 0.4, {"reason": "沪深300历史不足 60 日"}

        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        latest_return = close.iloc[-1] / close.iloc[-2] - 1 if len(close) >= 2 and close.iloc[-2] else 0
        three_day_return = close.iloc[-1] / close.iloc[-4] - 1 if len(close) >= 4 and close.iloc[-4] else 0
        volatility = close.pct_change().rolling(20).std().iloc[-1]
        advancers = int(market_data.get("advancers", 0) or 0)
        decliners = int(market_data.get("decliners", 0) or 0)
        breadth = advancers / (advancers + decliners) if advancers + decliners > 0 else 0.5

        details.update(
            {
                "ma20": float(ma20),
                "ma60": float(ma60),
                "latest_return": float(latest_return),
                "three_day_return": float(three_day_return),
                "volatility_20d": float(volatility),
                "breadth": breadth,
            }
        )

        if latest_return <= -0.03 or three_day_return <= -0.06:
            return "extreme_fear", 0.85, details
        if latest_return >= 0.03 and breadth >= 0.75:
            return "extreme_greed", 0.8, details
        if ma20 > ma60 and breadth >= 0.55:
            return "bull", 0.75, details
        if ma20 < ma60 and breadth <= 0.45:
            return "bear", 0.75, details
        return "shock", 0.65, details

