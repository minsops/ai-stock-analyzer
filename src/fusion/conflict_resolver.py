"""评分信号冲突处理。"""

from __future__ import annotations

from itertools import combinations

from src.engines.base_engine import ScoreResult


class ConflictResolver:
    """当两个引擎评分差距过大时处理。"""

    CONFLICT_THRESHOLD = 40
    QUARANTINE_THRESHOLD = 60
    PRIORITY_BY_REGIME = {
        "bull": "trend",
        "bear": "value",
        "shock": None,
        "extreme_fear": "value",
        "extreme_greed": "capital",
    }
    PRIORITY_SIGNALS = {
        "bull": "牛市冲突优先趋势分",
        "bear": "熊市冲突优先价值分",
        "extreme_fear": "极度恐慌时冲突优先价值分",
        "extreme_greed": "极度贪婪时冲突优先资金分",
    }

    def check_conflicts(self, scores: dict[str, ScoreResult]) -> list[dict]:
        conflicts: list[dict] = []
        available = {key: value for key, value in scores.items() if value.available}
        for engine_a, engine_b in combinations(available.keys(), 2):
            score_a = available[engine_a].score
            score_b = available[engine_b].score
            gap = abs(score_a - score_b)
            if gap > self.CONFLICT_THRESHOLD:
                conflicts.append(
                    {
                        "engine_a": engine_a,
                        "engine_b": engine_b,
                        "score_a": score_a,
                        "score_b": score_b,
                        "gap": gap,
                        "recommendation": "quarantine" if gap > self.QUARANTINE_THRESHOLD else "adjusted",
                    }
                )
        return conflicts

    def resolve(self, scores: dict[str, ScoreResult], regime: str) -> dict:
        conflicts = self.check_conflicts(scores)
        if not conflicts:
            return {"action": "pass", "adjusted_scores": scores, "reason": "无明显冲突", "conflicts": []}
        if any(item["gap"] > self.QUARANTINE_THRESHOLD for item in conflicts):
            return {"action": "quarantine", "adjusted_scores": scores, "reason": "引擎分歧超过隔离阈值", "conflicts": conflicts}

        adjusted = dict(scores)
        priority = self.PRIORITY_BY_REGIME.get(regime)
        for conflict in conflicts:
            engines = (conflict["engine_a"], conflict["engine_b"])
            if priority in engines:
                target_score = scores[priority].score
                signal = self.PRIORITY_SIGNALS.get(regime, "冲突按市场状态优先引擎处理")
            else:
                target_score = min(scores[engine].score for engine in engines)
                signal = "震荡市冲突取较低分" if regime == "shock" else "冲突未包含优先引擎，取较低分"

            for engine in engines:
                original = adjusted[engine]
                adjusted[engine] = ScoreResult(
                    target_score,
                    original.confidence,
                    original.details,
                    [*original.signals, signal],
                    original.available,
                )
        return {"action": "adjusted", "adjusted_scores": adjusted, "reason": f"{regime} 状态下按规则调整冲突信号", "conflicts": conflicts}
