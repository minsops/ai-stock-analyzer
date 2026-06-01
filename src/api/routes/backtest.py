"""回测 API。"""

from __future__ import annotations

from fastapi import APIRouter

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
def suggest_position(code: str, capital: float, composite_score: float = 60, regime: str = "shock") -> dict:
    return PositionSizer().suggest(code, composite_score, regime, capital)

