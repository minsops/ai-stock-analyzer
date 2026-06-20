"""交易计划：在综合评分之上，给出可执行的建议买入区间 / 止损价 / 目标价。

- 技术派：买入区间贴近 MA20 支撑，止损按 ATR，目标按风险报酬 1:2。
- 价值派：目标价 = 估值回归历史中位(PE 中位)对应的价格。
两者都给，外加按综合分的操作建议。结果仅供研究参考，不构成投资建议。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class TradePlan:
    """由评分 + 技术 + 估值生成交易计划。"""

    def build(self, composite_score: float, quotes: pd.DataFrame | None, valuation_pe: dict | None = None) -> dict[str, Any]:
        if not isinstance(quotes, pd.DataFrame) or len(quotes) < 20 or "close" not in quotes:
            return {"available": False, "reason": "行情数据不足，无法给出交易计划"}
        q = quotes.sort_values("trade_date").copy()
        for column in ("high", "low", "close"):
            q[column] = pd.to_numeric(q.get(column), errors="coerce")
        close = float(q["close"].iloc[-1])
        if not close or pd.isna(close):
            return {"available": False, "reason": "无有效收盘价"}

        atr = self._atr(q)
        ma20 = float(q["close"].rolling(20).mean().iloc[-1])

        # 买入区间：回踩到 MA20 / 现价下方约 1.5×ATR 与现价之间。
        entry_low = round(min(close, max(ma20, close - 1.5 * atr)), 2)
        entry_high = round(close, 2)
        # 止损：买入区下沿再下 1.5×ATR。
        stop_loss = round(entry_low - 1.5 * atr, 2)
        risk = max(entry_low - stop_loss, 1e-6)
        # 技术目标：风险报酬 1:2。
        target_tech = round(entry_high + 2 * risk, 2)

        # 价值目标：PE 回归历史中位对应价格。
        target_value = None
        if valuation_pe:
            current_pe = valuation_pe.get("current_value")
            median_pe = valuation_pe.get("median")
            if current_pe and median_pe and current_pe > 0:
                target_value = round(close * median_pe / current_pe, 2)

        action, horizon = self._action(composite_score)
        upside_tech = round((target_tech / close - 1) * 100, 1)
        upside_value = round((target_value / close - 1) * 100, 1) if target_value else None
        return {
            "available": True,
            "last_close": round(close, 2),
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop_loss": stop_loss,
            "target_technical": target_tech,
            "target_value": target_value,
            "risk_reward": round((target_tech - entry_high) / risk, 2),
            "upside_technical_pct": upside_tech,
            "upside_value_pct": upside_value,
            "action": action,
            "horizon": horizon,
            "atr_pct": round(atr / close * 100, 2),
        }

    def _atr(self, q: pd.DataFrame, window: int = 14) -> float:
        if not {"high", "low", "close"}.issubset(q.columns) or len(q) < window + 1:
            return float(q["close"].pct_change().std() * q["close"].iloc[-1]) or q["close"].iloc[-1] * 0.02
        prev_close = q["close"].shift(1)
        tr = pd.concat(
            [(q["high"] - q["low"]), (q["high"] - prev_close).abs(), (q["low"] - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(window).mean().iloc[-1]
        return float(atr) if not pd.isna(atr) else float(q["close"].iloc[-1] * 0.02)

    def _action(self, composite_score: float) -> tuple[str, str]:
        if composite_score >= 75:
            return "强烈关注", "趋势/中线"
        if composite_score >= 60:
            return "关注/逢低布局", "中线"
        if composite_score >= 45:
            return "观望", "等待信号"
        return "回避", "—"
