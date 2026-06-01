"""价值评分引擎。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.engines.base_engine import BaseEngine, ScoreResult


class ValueEngine(BaseEngine):
    """价值评分引擎。"""

    WEIGHTS = {
        "pe_percentile": 0.25,
        "pb_percentile": 0.15,
        "roe": 0.20,
        "revenue_yoy": 0.15,
        "profit_yoy": 0.15,
        "dividend_yield": 0.10,
    }

    @property
    def name(self) -> str:
        return "value"

    def score(self, code: str, data: dict[str, Any]) -> ScoreResult:
        financial = data.get("financial") or {}
        history = data.get("financial_history")
        scores: dict[str, float] = {}
        details: dict[str, Any] = {}
        signals: list[str] = []

        pe_percentile = self._metric_percentile(financial, history, "pe_ttm")
        pb_percentile = self._metric_percentile(financial, history, "pb")
        scores["pe_percentile"] = self._inverse_percentile_score(pe_percentile)
        scores["pb_percentile"] = self._inverse_percentile_score(pb_percentile)
        details["pe_percentile"] = pe_percentile if not pd.isna(pe_percentile) else None
        details["pb_percentile"] = pb_percentile if not pd.isna(pb_percentile) else None
        if not pd.isna(pe_percentile):
            signals.append(f"PE 处于历史 {pe_percentile:.0%} 分位")
        if not pd.isna(pb_percentile):
            signals.append(f"PB 处于历史 {pb_percentile:.0%} 分位")

        roe = self._get_financial_value(financial, "roe")
        revenue_yoy = self._get_financial_value(financial, "revenue_yoy")
        profit_yoy = self._get_financial_value(financial, "profit_yoy")
        dividend_yield = self._get_financial_value(financial, "dividend_yield")

        scores["roe"] = self._normalize(roe, 0, 20) if not pd.isna(roe) else np.nan
        scores["revenue_yoy"] = self._normalize(revenue_yoy, -20, 30) if not pd.isna(revenue_yoy) else np.nan
        scores["profit_yoy"] = self._normalize(profit_yoy, -20, 30) if not pd.isna(profit_yoy) else np.nan
        scores["dividend_yield"] = self._normalize(dividend_yield, 0, 5) if not pd.isna(dividend_yield) else np.nan
        details.update({"roe": roe, "revenue_yoy": revenue_yoy, "profit_yoy": profit_yoy, "dividend_yield": dividend_yield})

        if not pd.isna(roe):
            signals.append(f"ROE {roe:.2f}%")
        if not pd.isna(profit_yoy):
            signals.append(f"净利同比 {profit_yoy:.2f}%")

        return self._weighted_result(scores, self.WEIGHTS, details, signals, total_items=len(self.WEIGHTS))

    def _metric_percentile(self, financial: dict[str, Any] | pd.DataFrame, history: pd.DataFrame | None, metric: str) -> float:
        current = self._get_financial_value(financial, metric)
        if pd.isna(current):
            return np.nan
        if history is None or history.empty or metric not in history:
            return np.nan
        values = pd.to_numeric(history[metric], errors="coerce").dropna()
        if values.empty:
            return np.nan
        return float((values <= current).mean())

    def _get_financial_value(self, financial: dict[str, Any] | pd.DataFrame, key: str) -> float:
        if isinstance(financial, pd.DataFrame):
            if financial.empty or key not in financial:
                return np.nan
            values = pd.to_numeric(financial[key], errors="coerce").dropna()
            return float(values.iloc[-1]) if not values.empty else np.nan
        value = financial.get(key)
        return float(value) if value is not None and not pd.isna(value) else np.nan

