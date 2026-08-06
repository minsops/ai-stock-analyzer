"""仓位建议计算。"""

from __future__ import annotations

from typing import Any

from config import settings


class PositionSizer:
    """阶段一仓位管理建议。"""

    def suggest(
        self,
        code: str,
        composite_score: float,
        regime: str,
        total_capital: float,
        current_positions: dict[str, Any] | None = None,
        industry: str | None = None,
    ) -> dict:
        current_positions = current_positions or {}
        regime_total_cap = settings.REGIME_TOTAL_POSITION.get(regime, settings.REGIME_TOTAL_POSITION["shock"])
        score_pct = max(0.0, min(settings.MAX_SINGLE_POSITION, composite_score / 100 * settings.MAX_SINGLE_POSITION))
        suggested_pct = min(score_pct, settings.MAX_SINGLE_POSITION)
        warnings: list[str] = []

        current_total_pct = sum(float(item.get("pct", 0)) for item in current_positions.values() if isinstance(item, dict))
        remaining_total_pct = max(0.0, regime_total_cap - current_total_pct)
        if suggested_pct > remaining_total_pct:
            suggested_pct = remaining_total_pct
            warnings.append("当前总仓位接近市场状态上限")

        if industry:
            current_industry_pct = sum(
                float(item.get("pct", 0))
                for item in current_positions.values()
                if isinstance(item, dict) and item.get("industry") == industry
            )
            remaining_industry_pct = max(0.0, settings.MAX_INDUSTRY_POSITION - current_industry_pct)
            if suggested_pct > remaining_industry_pct:
                suggested_pct = remaining_industry_pct
                warnings.append("同行业仓位接近上限")

        suggested_amount = round(total_capital * suggested_pct, 2)
        return {
            "code": code,
            "suggested_pct": round(suggested_pct, 4),
            "suggested_amount": suggested_amount,
            "max_allowed_pct": settings.MAX_SINGLE_POSITION,
            "regime_total_cap": regime_total_cap,
            "warnings": warnings,
        }
