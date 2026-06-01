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
        "shock": "conservative",
        "extreme_fear": "value",
        "extreme_greed": "capital",
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

        adjusted = {key: value for key, value in scores.items()}
        priority = self.PRIORITY_BY_REGIME.get(regime, "conservative")
        if priority == "conservative":
            for conflict in conflicts:
                lower = min(conflict["score_a"], conflict["score_b"])
                for engine in (conflict["engine_a"], conflict["engine_b"]):
                    original = adjusted[engine]
                    adjusted[engine] = ScoreResult(lower, original.confidence, original.details, original.signals, original.available)
        elif priority in adjusted:
            for conflict in conflicts:
                for engine in (conflict["engine_a"], conflict["engine_b"]):
                    if engine != priority and engine in adjusted:
                        original = adjusted[engine]
                        priority_score = adjusted[priority].score
                        adjusted[engine] = ScoreResult(
                            round((original.score + priority_score) / 2, 2),
                            original.confidence,
                            original.details,
                            original.signals,
                            original.available,
                        )
        return {"action": "adjusted", "adjusted_scores": adjusted, "reason": f"{regime} 状态下按规则调整冲突信号", "conflicts": conflicts}

