"""行业轮动 + 产业链 API。"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.dependencies import get_analyst, get_storage
from src.industry import IndustryRanker

router = APIRouter(prefix="/industry", tags=["industry"])


@router.get("/hot")
def hot_industries(top: int = 8, lookback_days: int = 250, min_stocks: int = 15) -> dict:
    """近一年热门行业(按成分股涨幅中位数排序，稳健)。"""
    strength = IndustryRanker(get_storage()).industry_strength(lookback_days=lookback_days, min_stocks=min_stocks)
    items = []
    for row in strength.head(top).to_dict("records"):
        items.append(
            {
                "rank": int(row["rank"]),
                "industry": row["industry"],
                "median_return": round(float(row["median_return"]) * 100, 1),
                "mean_return": round(float(row["mean_return"]) * 100, 1),
                "stock_count": int(row["stock_count"]),
            }
        )
    return {"items": items}


@router.get("/chain")
def industry_chain(industry: str, top: int = 12, ai: bool = True) -> dict:
    """某行业头部个股 + 产业链(上下游/合作/受益标的)AI 分析。"""
    ranker = IndustryRanker(get_storage())
    members = ranker.industry_members_ranked(industry, limit=top)
    top_stocks = [
        {"code": m["code"], "name": m.get("name"), "return_1y": round(m.get("return_1y", 0) * 100, 1)}
        for m in members
    ]
    chain = get_analyst().analyze_industry_chain(industry, members) if ai else {"available": False, "reason": "未请求 AI"}
    return {"industry": industry, "top_stocks": top_stocks, "chain": chain}
