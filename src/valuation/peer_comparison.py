"""同行业横向估值对比。"""

from __future__ import annotations

import pandas as pd

from src.data_layer.storage import DataStorage


class PeerComparison:
    """同行业内横向对比。"""

    DEFAULT_METRICS = ["pe_ttm", "pb", "roe", "revenue_yoy", "profit_yoy"]

    def __init__(self, storage: DataStorage) -> None:
        self.storage = storage

    def compare(self, code: str, metrics: list[str] | None = None) -> dict:
        metrics = metrics or self.DEFAULT_METRICS
        stock = self.storage.get_stock_info(code)
        industry = stock.get("industry_l1")
        if not industry:
            return {"industry": None, "peer_count": 0, "rankings": {}, "overall_rank": None, "overall_percentile": None}

        all_codes = self.storage.get_all_active_codes()
        rows: list[dict] = []
        for peer_code in all_codes:
            peer_info = self.storage.get_stock_info(peer_code)
            if peer_info.get("industry_l1") != industry:
                continue
            latest = self.storage.get_latest_financial(peer_code)
            if latest:
                rows.append({"code": peer_code, **latest})
        frame = pd.DataFrame(rows)
        if frame.empty or code not in set(frame["code"]):
            return {"industry": industry, "peer_count": len(frame), "rankings": {}, "overall_rank": None, "overall_percentile": None}

        rankings = {}
        percentiles: list[float] = []
        for metric in metrics:
            if metric not in frame:
                continue
            values = pd.to_numeric(frame[metric], errors="coerce")
            current_series = values[frame["code"] == code].dropna()
            valid = frame.loc[values.notna(), ["code"]].assign(value=values[values.notna()])
            if current_series.empty or valid.empty:
                continue
            ascending = metric in {"pe_ttm", "pb"}
            valid = valid.sort_values("value", ascending=ascending).reset_index(drop=True)
            rank = int(valid.index[valid["code"] == code][0]) + 1
            percentile = rank / len(valid)
            percentiles.append(percentile)
            rankings[metric] = {
                "value": float(current_series.iloc[0]),
                "rank": rank,
                "percentile": percentile,
                "industry_median": float(valid["value"].median()),
            }

        overall_percentile = sum(percentiles) / len(percentiles) if percentiles else None
        overall_rank = int(round(overall_percentile * len(frame))) if overall_percentile else None
        return {
            "industry": industry,
            "peer_count": len(frame),
            "rankings": rankings,
            "overall_rank": overall_rank,
            "overall_percentile": overall_percentile,
        }

