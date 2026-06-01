"""纵向估值分析。"""

from __future__ import annotations

import pandas as pd

from src.data_layer.storage import DataStorage


class HistoricalValuation:
    """计算个股估值指标历史分位数。"""

    def __init__(self, storage: DataStorage) -> None:
        self.storage = storage

    def compute_percentile(self, code: str, metric: str, lookback_years: int = 5) -> dict:
        history = self.storage.get_financial_history(code)
        if history.empty or metric not in history:
            return {"current_value": None, "percentile": None, "assessment": "unknown"}
        if "report_date" in history:
            cutoff = pd.Timestamp.today().date().replace(year=pd.Timestamp.today().year - lookback_years)
            history = history[pd.to_datetime(history["report_date"]).dt.date >= cutoff]
        values = pd.to_numeric(history[metric], errors="coerce").dropna()
        if values.empty:
            return {"current_value": None, "percentile": None, "assessment": "unknown"}
        current = float(values.iloc[-1])
        percentile = float((values <= current).mean())
        assessment = "undervalued" if percentile < 0.25 else "overvalued" if percentile > 0.75 else "fair"
        return {
            "current_value": current,
            "percentile": percentile,
            "min": float(values.min()),
            "max": float(values.max()),
            "median": float(values.median()),
            "mean": float(values.mean()),
            "assessment": assessment,
        }

