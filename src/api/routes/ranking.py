"""排行榜 API。"""

from __future__ import annotations

import csv
import io
from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from src.api.dependencies import get_current_regime, get_storage
from src.api.schemas import RankingItem, RankingResponse


router = APIRouter(prefix="/ranking", tags=["ranking"])

_CSV_COLUMNS = [
    ("rank", "排名"),
    ("code", "代码"),
    ("name", "名称"),
    ("industry", "行业"),
    ("composite_score", "综合评分"),
    ("value_score", "价值"),
    ("trend_score", "趋势"),
    ("capital_score", "资金"),
    ("industry_score", "行业评分"),
    ("event_score", "事件"),
    ("regime", "市场状态"),
    ("score_date", "评分日"),
]


@router.get("", response_model=RankingResponse)
def get_ranking(
    date: str | None = None,
    top_n: Annotated[int, Query(ge=1)] = 50,
    industry: str | None = None,
) -> dict:
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
    regime, _, _ = get_current_regime()
    return {"date": score_date, "regime": regime, "total_scanned": len(scores), "total_passed_filter": len(scores), "items": items}


@router.get("/export.csv")
def export_ranking_csv(
    date: str | None = None,
    top_n: Annotated[int, Query(ge=1)] = 100,
    industry: str | None = None,
) -> StreamingResponse:
    """导出综合评分排行为 CSV(供筛选/二次分析)。"""
    score_date = date or date_type.today().isoformat()
    scores = get_storage().get_top_scores(score_date, top_n=top_n)
    if industry and not scores.empty and "industry" in scores:
        scores = scores[scores["industry"] == industry]

    buffer = io.StringIO()
    buffer.write("﻿")  # BOM，Excel 正确识别 UTF-8 中文
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in _CSV_COLUMNS])
    for idx, row in enumerate(scores.to_dict("records"), start=1):
        out = []
        for key, _ in _CSV_COLUMNS:
            value = idx if key == "rank" else row.get(key)
            if isinstance(value, float):
                value = round(value, 2)
            out.append("" if value is None else value)
        writer.writerow(out)
    buffer.seek(0)
    filename = f"ranking_{score_date}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
