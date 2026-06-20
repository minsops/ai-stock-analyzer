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
            # 无真实主力资金数据时，用量价代理(换手/量比/OBV/资金流向量)估计资金面。
            return self._proxy_score(data)
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

    PROXY_WEIGHTS = {
        "volume_ratio": 0.25,
        "obv_trend": 0.30,
        "money_flow": 0.30,
        "turnover_trend": 0.15,
    }

    def _proxy_score(self, data: dict[str, Any]) -> ScoreResult:
        """量价资金代理：在没有真实主力净流入数据时，用量价关系估计资金强弱。"""
        quotes = data.get("quotes")
        if not isinstance(quotes, pd.DataFrame) or len(quotes) < 20 or "close" not in quotes:
            return ScoreResult(0.0, 0.0, {}, ["资金面数据不足，暂不参与综合评分"], False)
        q = quotes.sort_values("trade_date").copy()
        for column in ("high", "low", "close", "volume"):
            q[column] = pd.to_numeric(q.get(column), errors="coerce")
        close, high, low, volume = q["close"], q["high"], q["low"], q["volume"]
        scores: dict[str, float] = {}
        details: dict[str, Any] = {}
        signals: list[str] = ["资金面为量价代理估计(无真实主力资金数据)"]

        vol5 = volume.tail(5).mean()
        vol20 = volume.tail(20).mean()
        ratio = vol5 / vol20 if vol20 else np.nan
        price_up = close.iloc[-1] > close.iloc[-5] if len(close) >= 5 else False
        if not pd.isna(ratio):
            scores["volume_ratio"] = 100.0 if ratio > 1.3 and price_up else 20.0 if ratio < 0.7 and not price_up else 55.0
            details["volume_ratio_5_20"] = float(ratio)

        # OBV 趋势：放量上涨累积为正
        direction = np.sign(close.diff().fillna(0))
        obv = (direction * volume).cumsum()
        if len(obv) >= 20 and obv.tail(20).iloc[0] != 0:
            obv_change = obv.iloc[-1] - obv.tail(20).iloc[0]
            scores["obv_trend"] = 100.0 if obv_change > 0 else 20.0
            details["obv_change_20d"] = float(obv_change)
            signals.append("OBV 近 20 日净流入" if obv_change > 0 else "OBV 近 20 日净流出")

        # 资金流向量(CMF)：收盘在区间内的位置 × 量，近 20 日
        span = (high - low).replace(0, np.nan)
        mf_multiplier = ((close - low) - (high - close)) / span
        mf_volume = (mf_multiplier * volume).tail(20)
        denom = volume.tail(20).sum()
        if denom and not mf_volume.dropna().empty:
            cmf = mf_volume.sum() / denom
            scores["money_flow"] = float(max(0.0, min(100.0, (cmf + 0.3) / 0.6 * 100)))
            details["cmf_20d"] = float(cmf)
            signals.append(f"资金流向量 CMF {cmf:+.2f}")

        turn = pd.to_numeric(q.get("turnover"), errors="coerce") if "turnover" in q else None
        if turn is not None and turn.notna().sum() >= 20:
            turn_now = turn.tail(5).mean()
            turn_base = turn.tail(20).mean()
            if turn_base:
                change = turn_now / turn_base - 1
                scores["turnover_trend"] = 100.0 if change > 0.2 and price_up else 30.0 if change < -0.2 else 55.0
                details["turnover_change"] = float(change)

        return self._weighted_result(scores, self.PROXY_WEIGHTS, details, signals, total_items=len(self.PROXY_WEIGHTS))

