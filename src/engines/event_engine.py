"""事件驱动评分引擎基础版。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.engines.base_engine import BaseEngine, ScoreResult


class EventEngine(BaseEngine):
    """阶段一基础事件评分引擎。"""

    WEIGHTS = {
        "limit_signal": 0.50,
        "abnormal_move": 0.50,
    }

    @property
    def name(self) -> str:
        return "event"

    def score(self, code: str, data: dict[str, Any]) -> ScoreResult:
        quotes = data.get("quotes")
        if not isinstance(quotes, pd.DataFrame) or quotes.empty:
            return ScoreResult(0.0, 0.0, {}, ["事件数据不足，暂不参与综合评分"], False)
        q = quotes.sort_values("trade_date").copy()
        pct = pd.to_numeric(q.get("pct_change"), errors="coerce").dropna()
        if pct.empty:
            close = pd.to_numeric(q.get("close"), errors="coerce").dropna()
            pct = close.pct_change().dropna() * 100

        scores: dict[str, float] = {}
        details: dict[str, Any] = {}
        signals: list[str] = []

        recent5 = pct.tail(5)
        if not recent5.empty:
            has_limit_up = bool((recent5 >= 9.5).any())
            has_limit_down = bool((recent5 <= -9.5).any())
            scores["limit_signal"] = 80.0 if has_limit_up else 20.0 if has_limit_down else 50.0
            details["limit_up_5d"] = has_limit_up
            details["limit_down_5d"] = has_limit_down
            signals.append("近 5 日出现涨停" if has_limit_up else "近 5 日出现跌停" if has_limit_down else "近 5 日无涨跌停")
        else:
            scores["limit_signal"] = np.nan

        recent3 = pct.tail(3)
        if len(recent3) >= 3:
            total_move = recent3.sum()
            scores["abnormal_move"] = 30.0 if abs(total_move) > 15 else 60.0
            details["move_3d"] = float(total_move)
            if abs(total_move) > 15:
                signals.append(f"近 3 日累计波动 {total_move:.2f}%")
            else:
                signals.append("短期波动正常")
        else:
            scores["abnormal_move"] = np.nan

        return self._weighted_result(scores, self.WEIGHTS, details, signals, total_items=len(self.WEIGHTS))
