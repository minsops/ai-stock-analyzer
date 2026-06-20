"""市场状态 API。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from src.api.dependencies import get_current_regime
from src.api.schemas import RegimeResponse


router = APIRouter(prefix="/regime", tags=["regime"])


@router.get("", response_model=RegimeResponse)
def get_regime() -> dict:
    regime, confidence, details = get_current_regime()
    return {"date": date.today().isoformat(), "regime": regime, "confidence": confidence, "details": details}

