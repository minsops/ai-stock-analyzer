"""回测 API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from src.api.dependencies import get_storage
from src.api.schemas import BacktestRequest
from src.backtest import BacktestSimulator
from src.risk import PositionSizer


router = APIRouter(tags=["backtest", "position"])


@router.post("/backtest")
def run_backtest(request: BacktestRequest) -> dict:
    result = BacktestSimulator(get_storage()).run(request.model_dump())
    return {
        "metrics": result.metrics,
        "equity_curve": result.equity_curve.to_dict("records"),
        "positions": result.positions,
    }


@router.get("/position/suggest")
def suggest_position(
    code: Annotated[str, Query(pattern=r"^\d{6}$")],
    capital: Annotated[float, Query(gt=0)],
    composite_score: float = 60,
    regime: str = "shock",
    industry: str | None = None,
) -> dict:
    return PositionSizer().suggest(code, composite_score, regime, capital, industry=industry)
