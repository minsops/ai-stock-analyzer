"""行业热度排名 + 行业内分类选股。

- 行业热度：用各行业成分股近一年涨幅的均值/中位数衡量，挑出热门行业。
- 行业内选股：对热门行业的成分股做综合评分，按行业规模自适应取前 20–50 只。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from src.data_layer.storage import DataStorage


@dataclass
class IndustrySelection:
    """单个行业的选股结果。"""

    industry: str
    rank: int
    mean_return: float
    median_return: float
    stock_count: int
    top_stocks: list[dict[str, Any]] = field(default_factory=list)


class IndustryRanker:
    """行业轮动排名与行业内分类选股。"""

    def __init__(self, storage: DataStorage) -> None:
        self.storage = storage

    def industry_strength(self, lookback_days: int = 250, min_stocks: int = 3) -> pd.DataFrame:
        """计算各行业近一年（约 lookback_days 个交易日）涨幅，返回按均值降序的排名表。"""
        stocks = self.storage.get_active_stocks()
        if stocks.empty or "industry_l1" not in stocks:
            return pd.DataFrame(columns=["industry", "mean_return", "median_return", "stock_count", "rank"])
        stocks = stocks.dropna(subset=["industry_l1"])

        records: list[dict[str, Any]] = []
        for row in stocks.to_dict("records"):
            ret = self._stock_return(row["code"], lookback_days)
            if ret is not None:
                records.append({"industry": row["industry_l1"], "code": row["code"], "ret": ret})
        if not records:
            return pd.DataFrame(columns=["industry", "mean_return", "median_return", "stock_count", "rank"])

        frame = pd.DataFrame(records)
        grouped = (
            frame.groupby("industry")
            .agg(mean_return=("ret", "mean"), median_return=("ret", "median"), stock_count=("ret", "size"))
            .reset_index()
        )
        grouped = grouped[grouped["stock_count"] >= min_stocks]
        # 按中位数排序：对妖股(个别暴涨)更稳健，避免等权均值被极端值带偏。
        grouped = grouped.sort_values("median_return", ascending=False).reset_index(drop=True)
        grouped["rank"] = range(1, len(grouped) + 1)
        return grouped

    def select(
        self,
        top_industries: int = 8,
        lookback_days: int = 250,
        min_stocks: int = 3,
        scorer: Callable[[str], dict[str, Any]] | None = None,
        min_pick: int = 20,
        max_pick: int = 50,
    ) -> list[IndustrySelection]:
        """挑出热门行业，并在每个行业内按综合评分自适应取前 N 只。"""
        strength = self.industry_strength(lookback_days=lookback_days, min_stocks=min_stocks)
        if strength.empty:
            return []
        stocks = self.storage.get_active_stocks().dropna(subset=["industry_l1"])
        selections: list[IndustrySelection] = []
        for row in strength.head(top_industries).to_dict("records"):
            industry = row["industry"]
            members = stocks[stocks["industry_l1"] == industry]["code"].tolist()
            ranked = self._rank_members(members, lookback_days, scorer)
            pick = self._pick_count(len(ranked), min_pick, max_pick)
            selections.append(
                IndustrySelection(
                    industry=industry,
                    rank=int(row["rank"]),
                    mean_return=float(row["mean_return"]),
                    median_return=float(row["median_return"]),
                    stock_count=int(row["stock_count"]),
                    top_stocks=ranked[:pick],
                )
            )
        return selections

    def industry_members_ranked(self, industry: str, lookback_days: int = 250, limit: int = 15) -> list[dict[str, Any]]:
        """某行业内成分股按近一年涨幅排序的头部(含名称)，供产业链分析/展示使用。"""
        stocks = self.storage.get_active_stocks()
        if stocks.empty or "industry_l1" not in stocks:
            return []
        stocks = stocks.dropna(subset=["industry_l1"])
        members = stocks[stocks["industry_l1"] == industry]
        names = dict(zip(members["code"], members["name"]))
        ranked = self._rank_members(members["code"].tolist(), lookback_days, scorer=None)
        for row in ranked:
            row["name"] = names.get(row["code"], row["code"])
        return ranked[:limit]

    def _pick_count(self, available: int, min_pick: int, max_pick: int) -> int:
        """按行业规模自适应：大行业多取（至多 max_pick），小行业少取（至多其全部）。"""
        if available <= min_pick:
            return available
        return min(max_pick, max(min_pick, available))

    def _rank_members(
        self,
        codes: list[str],
        lookback_days: int,
        scorer: Callable[[str], dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for code in codes:
            ret = self._stock_return(code, lookback_days)
            if ret is None:
                continue
            entry: dict[str, Any] = {"code": code, "return_1y": ret}
            if scorer is not None:
                try:
                    report = scorer(code)
                    entry["name"] = report.get("name", code)
                    entry["composite_score"] = report.get("composite_score", 0.0)
                    entry["passed"] = report.get("filter_passed", True) and not report.get("quarantined", False)
                except Exception:  # noqa: BLE001 - 单股评分失败不影响整体
                    entry["composite_score"] = 0.0
                    entry["passed"] = True
            rows.append(entry)
        # 有评分按综合评分排序，否则按近一年涨幅排序。
        key = "composite_score" if scorer is not None else "return_1y"
        rows = [r for r in rows if r.get("passed", True)]
        return sorted(rows, key=lambda r: r.get(key, 0.0), reverse=True)

    def _stock_return(self, code: str, lookback_days: int) -> float | None:
        quotes = self.storage.get_quotes(code)
        if quotes.empty or "close" not in quotes:
            return None
        close = pd.to_numeric(quotes.sort_values("trade_date")["close"], errors="coerce").dropna()
        window = close.tail(lookback_days)
        if len(window) < 2 or window.iloc[0] == 0:
            return None
        return float(window.iloc[-1] / window.iloc[0] - 1)
