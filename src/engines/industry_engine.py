"""行业轮动评分引擎。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.engines.base_engine import BaseEngine, ScoreResult


class IndustryEngine(BaseEngine):
    """行业轮动评分引擎。"""

    WEIGHTS = {
        "industry_strength": 0.40,
        "industry_fund_flow": 0.30,
        "stock_excess_return": 0.30,
    }

    @property
    def name(self) -> str:
        return "industry"

    def score(self, code: str, data: dict[str, Any]) -> ScoreResult:
        industry = data.get("industry") or {}
        quotes = data.get("quotes")
        scores: dict[str, float] = {}
        details: dict[str, Any] = {}
        signals: list[str] = []

        rank_percentile = industry.get("rank_percentile")
        if rank_percentile is not None and not pd.isna(rank_percentile):
            scores["industry_strength"] = self._inverse_rank_score(float(rank_percentile))
            details["rank_percentile"] = float(rank_percentile)
            signals.append(f"行业强度排名前 {rank_percentile:.0%}")
        else:
            scores["industry_strength"] = np.nan

        fund_percentile = industry.get("fund_flow_percentile")
        if fund_percentile is not None and not pd.isna(fund_percentile):
            scores["industry_fund_flow"] = self._inverse_rank_score(float(fund_percentile))
            details["fund_flow_percentile"] = float(fund_percentile)
        else:
            scores["industry_fund_flow"] = np.nan

        industry_return_20d = industry.get("return_20d")
        if isinstance(quotes, pd.DataFrame) and len(quotes) >= 21 and industry_return_20d is not None:
            close = pd.to_numeric(quotes.sort_values("trade_date")["close"], errors="coerce").dropna()
            stock_return = close.iloc[-1] / close.iloc[-21] - 1 if len(close) >= 21 and close.iloc[-21] else np.nan
            excess = stock_return - float(industry_return_20d) if not pd.isna(stock_return) else np.nan
            scores["stock_excess_return"] = self._normalize(excess, -0.10, 0.10) if not pd.isna(excess) else np.nan
            details["stock_excess_return_20d"] = float(excess) if not pd.isna(excess) else None
        else:
            scores["stock_excess_return"] = np.nan

        return self._weighted_result(scores, self.WEIGHTS, details, signals, total_items=len(self.WEIGHTS))

    def _inverse_rank_score(self, percentile: float) -> float:
        return float(max(0, min(100, (1 - percentile) * 100)))

