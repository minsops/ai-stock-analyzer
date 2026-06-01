"""个股相关 API。"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.dependencies import get_ranker, get_storage
from src.api.schemas import ScoreReport
from src.valuation import HistoricalValuation


router = APIRouter(prefix="/stock", tags=["stock"])


@router.get("/{code}/score", response_model=ScoreReport)
def get_stock_score(code: str) -> dict:
    return get_ranker().score_single(code)


@router.get("/{code}/valuation")
def get_stock_valuation(code: str) -> dict:
    valuation = HistoricalValuation(get_storage())
    return {
        "code": code,
        "metrics": {metric: valuation.compute_percentile(code, metric) for metric in ("pe_ttm", "pb", "ps_ttm", "dividend_yield")},
    }


@router.get("/{code}/chart-data")
def get_chart_data(code: str, period: str = "120d") -> dict:
    days = {"60d": 60, "120d": 120, "1y": 365}.get(period, 120)
    storage = get_storage()
    quotes = storage.get_quotes(code).tail(days)
    return {"code": code, "period": period, "quotes": quotes.to_dict("records")}

