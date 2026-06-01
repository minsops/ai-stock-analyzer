"""动态权重管理。"""

from __future__ import annotations

from src.engines.base_engine import ScoreResult


class WeightManager:
    """根据市场状态动态调整各引擎权重。"""

    WEIGHT_TABLE = {
        "bull": {"value": 0.15, "trend": 0.35, "capital": 0.25, "industry": 0.15, "event": 0.10},
        "bear": {"value": 0.40, "trend": 0.15, "capital": 0.20, "industry": 0.10, "event": 0.15},
        "shock": {"value": 0.30, "trend": 0.25, "capital": 0.20, "industry": 0.15, "event": 0.10},
        "extreme_fear": {"value": 0.45, "trend": 0.05, "capital": 0.25, "industry": 0.10, "event": 0.15},
        "extreme_greed": {"value": 0.20, "trend": 0.20, "capital": 0.30, "industry": 0.15, "event": 0.15},
    }

    def get_weights(self, regime: str) -> dict[str, float]:
        """返回指定市场状态下的权重字典。"""
        weights = self.WEIGHT_TABLE.get(regime, self.WEIGHT_TABLE["shock"]).copy()
        total = sum(weights.values())
        return {key: value / total for key, value in weights.items()}

    def compute_composite(self, scores: dict[str, ScoreResult], regime: str) -> float:
        """加权计算综合评分，置信度低的引擎自动降权。"""
        weights = self.get_weights(regime)
        weighted_items: list[tuple[float, float]] = []
        for name, result in scores.items():
            if not result.available:
                continue
            effective_weight = weights.get(name, 0) * result.confidence
            if effective_weight > 0:
                weighted_items.append((result.score, effective_weight))
        total_weight = sum(weight for _, weight in weighted_items)
        if total_weight <= 0:
            return 0.0
        return round(sum(score * weight for score, weight in weighted_items) / total_weight, 2)

