"""排行榜 API。"""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter

from src.api.dependencies import get_fetcher, get_storage
from src.api.schemas import RankingItem, RankingResponse
from src.fusion import RegimeDetector


router = APIRouter(prefix="/ranking", tags=["ranking"])


@router.get("", response_model=RankingResponse)
def get_ranking(date: str | None = None, top_n: int = 50, industry: str | None = None) -> dict:
    score_date = date or date_type.today().isoformat()
    storage = get_storage()
    scores = storage.get_top_scores(score_date, top_n=top_n)
    if industry and not scores.empty and "industry" in scores:
        scores = scores[scores["industry"] == industry]
    items = []
    for idx, row in enumerate(scores.to_dict("records"), start=1):
        items.append(
            RankingItem(
                rank=idx,
                code=row["code"],
                name=row.get("name"),
                industry=row.get("industry"),
                composite_score=row.get("composite_score") or 0,
                value_score=row.get("value_score"),
                trend_score=row.get("trend_score"),
                capital_score=row.get("capital_score"),
                industry_score=row.get("industry_score"),
                event_score=row.get("event_score"),
            )
        )
    regime, _, _ = RegimeDetector().detect(get_fetcher().get_market_overview())
    return {"date": score_date, "regime": regime, "total_scanned": len(scores), "total_passed_filter": len(scores), "items": items}
