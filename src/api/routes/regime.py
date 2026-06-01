"""市场状态 API。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from src.api.dependencies import get_fetcher
from src.api.schemas import RegimeResponse
from src.fusion import RegimeDetector


router = APIRouter(prefix="/regime", tags=["regime"])


@router.get("", response_model=RegimeResponse)
def get_regime() -> dict:
    regime, confidence, details = RegimeDetector().detect(get_fetcher().get_market_overview())
    return {"date": date.today().isoformat(), "regime": regime, "confidence": confidence, "details": details}

