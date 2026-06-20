"""自选股 API。服务端持久化用户关注的股票(分组/评分提醒阈值)，并附带最近一次评分。"""

from __future__ import annotations

from collections import OrderedDict

from fastapi import APIRouter
from pydantic import BaseModel

from src.api.dependencies import get_storage


router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistAddRequest(BaseModel):
    code: str
    note: str | None = None
    group_name: str | None = None
    alert_above: float | None = None
    alert_below: float | None = None


def _enrich(item: dict, storage) -> dict:
    code = item["code"]
    info = storage.get_stock_info(code)
    score = storage.get_latest_score(code)
    composite = score.get("composite_score")
    above, below = item.get("alert_above"), item.get("alert_below")
    triggered = None
    if composite is not None:
        if above is not None and composite >= above:
            triggered = "above"
        elif below is not None and composite <= below:
            triggered = "below"
    return {
        "code": code,
        "name": info.get("name"),
        "industry": info.get("industry_l1"),
        "group": item.get("group_name") or "默认",
        "note": item.get("note"),
        "composite_score": composite,
        "score_date": str(score["score_date"]) if score.get("score_date") else None,
        "alert_above": above,
        "alert_below": below,
        "alert_triggered": triggered,
    }


@router.get("")
def list_watchlist() -> dict:
    storage = get_storage()
    items = [_enrich(it, storage) for it in storage.get_watchlist_full()]
    # 有评分的按分数倒序，无评分的沉底
    items.sort(key=lambda x: (x["composite_score"] is not None, x["composite_score"] or 0), reverse=True)
    # 按分组聚合(保持插入/分数顺序)
    groups: "OrderedDict[str, list]" = OrderedDict()
    for it in items:
        groups.setdefault(it["group"], []).append(it)
    return {
        "count": len(items),
        "items": items,
        "groups": [{"name": name, "items": members} for name, members in groups.items()],
    }


@router.get("/alerts")
def list_alerts() -> dict:
    """当前触发的评分提醒(供仪表盘/通知用)。"""
    storage = get_storage()
    alerts = storage.check_watchlist_alerts()
    for alert in alerts:
        alert["name"] = storage.get_stock_info(alert["code"]).get("name")
    return {"count": len(alerts), "alerts": alerts}


@router.post("")
def add_watchlist(request: WatchlistAddRequest) -> dict:
    code = request.code.strip()
    if not code:
        return {"ok": False, "reason": "代码为空"}
    added = get_storage().add_to_watchlist(
        code,
        note=request.note,
        group_name=request.group_name,
        alert_above=request.alert_above,
        alert_below=request.alert_below,
    )
    return {"ok": True, "code": code, "added": added}


@router.delete("/{code}")
def delete_watchlist(code: str) -> dict:
    removed = get_storage().remove_from_watchlist(code.strip())
    return {"ok": True, "code": code, "removed": removed}
