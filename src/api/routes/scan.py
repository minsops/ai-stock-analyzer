"""扫描任务 API。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, BackgroundTasks
from fastapi.encoders import jsonable_encoder

from src.api.dependencies import get_ranker
from src.api.schemas import ScanRequest, ScanTaskResponse


router = APIRouter(prefix="/scan", tags=["scan"])
TASKS: dict[str, dict] = {}


@router.post("", response_model=ScanTaskResponse)
def create_scan(request: ScanRequest, background_tasks: BackgroundTasks) -> dict:
    task_id = str(uuid4())
    TASKS[task_id] = {"status": "running", "result": []}
    filters = request.filters.model_dump(exclude_none=True)
    background_tasks.add_task(_run_scan, task_id, request.top_n, filters)
    return {"task_id": task_id, "status": "running"}


@router.get("/{task_id}")
def get_scan_task(task_id: str) -> dict:
    return TASKS.get(task_id, {"status": "not_found", "result": []})


def _run_scan(task_id: str, top_n: int, filters: dict[str, Any]) -> None:
    try:
        result = get_ranker().scan_all(top_n=top_n, filters=filters)
        records = jsonable_encoder(result.to_dict("records")) if isinstance(result, pd.DataFrame) else []
        TASKS[task_id] = {"status": "completed", "result": records}
    except Exception as exc:  # noqa: BLE001
        TASKS[task_id] = {"status": "failed", "error": str(exc), "result": []}
