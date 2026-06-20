"""动态权重管理。"""

from __future__ import annotations

from src.engines.base_engine import ScoreResult


class WeightManager:
    """根据市场状态动态调整各引擎权重。"""

    WEIGHT_TABLE = {
        "bull": {"value": 0.13, "trend": 0.32, "capital": 0.22, "industry": 0.13, "event": 0.08, "news": 0.12},
        "bear": {"value": 0.36, "trend": 0.14, "capital": 0.18, "industry": 0.09, "event": 0.13, "news": 0.10},
        "shock": {"value": 0.27, "trend": 0.23, "capital": 0.18, "industry": 0.13, "event": 0.09, "news": 0.10},
        "extreme_fear": {"value": 0.40, "trend": 0.05, "capital": 0.22, "industry": 0.08, "event": 0.13, "news": 0.12},
        "extreme_greed": {"value": 0.18, "trend": 0.18, "capital": 0.27, "industry": 0.13, "event": 0.12, "news": 0.12},
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

