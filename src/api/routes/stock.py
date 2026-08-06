"""个股相关 API。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from src.api.dependencies import get_analyst, get_ranker, get_storage
from src.api.schemas import ScoreReport
from src.valuation import HistoricalValuation


router = APIRouter(prefix="/stock", tags=["stock"])


@router.get("/{code}/score", response_model=ScoreReport)
def get_stock_score(code: Annotated[str, Path(pattern=r"^\d{6}$")]) -> dict:
    return get_ranker().score_single(code)


@router.get("/{code}/report")
def get_stock_report(code: Annotated[str, Path(pattern=r"^\d{6}$")]) -> dict:
    """完整评分报告(含交易计划/各引擎/估值)，供仪表盘使用。"""
    return get_ranker().score_single(code)


@router.get("/{code}/ai-analysis")
def get_stock_ai_analysis(code: Annotated[str, Path(pattern=r"^\d{6}$")]) -> dict:
    report = get_ranker().score_single(code)
    analysis = get_analyst().analyze(report)
    return {"code": code, "composite_score": report.get("composite_score"), "regime": report.get("regime"), "analysis": analysis}


@router.get("/{code}/valuation")
def get_stock_valuation(code: Annotated[str, Path(pattern=r"^\d{6}$")]) -> dict:
    valuation = HistoricalValuation(get_storage())
    return {
        "code": code,
        "metrics": {metric: valuation.compute_percentile(code, metric) for metric in ("pe_ttm", "pb", "ps_ttm", "dividend_yield")},
    }


@router.get("/{code}/chart-data")
def get_chart_data(
    code: Annotated[str, Path(pattern=r"^\d{6}$")],
    period: Annotated[Literal["60d", "120d", "1y"], Query()] = "120d",
) -> dict:
    days = {"60d": 60, "120d": 120, "1y": 365}[period]
    storage = get_storage()
    quotes = storage.get_quotes(code).tail(days)
    return {"code": code, "period": period, "quotes": quotes.to_dict("records")}
