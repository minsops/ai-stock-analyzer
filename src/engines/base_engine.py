"""评分引擎基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class ScoreResult:
    """单个引擎的评分结果。"""

    score: float
    confidence: float
    details: dict[str, Any] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "confidence": self.confidence,
            "details": self.details,
            "signals": self.signals,
            "available": self.available,
        }


class BaseEngine(ABC):
    """评分引擎基类，所有引擎必须继承。"""

    min_available_confidence = 0.3

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎名称。"""

    @abstractmethod
    def score(self, code: str, data: dict[str, Any]) -> ScoreResult:
        """计算评分。"""

    def _normalize(self, value: float, min_val: float, max_val: float) -> float:
        """将原始指标归一化到 0-100。"""
        if pd.isna(value) or max_val == min_val:
            return 50.0
        return float(max(0, min(100, (value - min_val) / (max_val - min_val) * 100)))

    def _inverse_percentile_score(self, percentile: float) -> float:
        """分位数越低，得分越高。"""
        if pd.isna(percentile):
            return np.nan
        return float(max(0, min(100, (1 - percentile) * 100)))

    def _weighted_result(
        self,
        scores: dict[str, float],
        weights: dict[str, float],
        details: dict[str, Any],
        signals: list[str],
        total_items: int,
    ) -> ScoreResult:
        available_scores = {key: value for key, value in scores.items() if not pd.isna(value)}
        confidence = len(available_scores) / total_items if total_items else 0.0
        available = confidence >= self.min_available_confidence and bool(available_scores)
        if not available:
            return ScoreResult(
                score=0.0,
                confidence=confidence,
                details=details,
                signals=signals or [f"{self.name} 数据不足，暂不参与综合评分"],
                available=False,
            )

        usable_weights = {key: weights[key] for key in available_scores if key in weights}
        weight_sum = sum(usable_weights.values())
        if weight_sum <= 0:
            normalized_weights = {key: 1 / len(available_scores) for key in available_scores}
        else:
            normalized_weights = {key: value / weight_sum for key, value in usable_weights.items()}
        score = sum(available_scores[key] * normalized_weights[key] for key in normalized_weights)
        return ScoreResult(
            score=float(round(score, 2)),
            confidence=float(round(confidence, 4)),
            details=details,
            signals=signals or [f"{self.name} 评分完成"],
            available=True,
        )

    def _latest_value(self, data: dict[str, Any], key: str) -> float:
        financial = data.get("financial") or {}
        if isinstance(financial, pd.DataFrame):
            if financial.empty or key not in financial:
                return np.nan
            return pd.to_numeric(financial[key], errors="coerce").dropna().iloc[-1] if pd.to_numeric(financial[key], errors="coerce").dropna().any() else np.nan
        value = financial.get(key)
        return float(value) if value is not None and not pd.isna(value) else np.nan

