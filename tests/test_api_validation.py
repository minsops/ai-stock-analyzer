from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


client = TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/v1/stock/12345/score", {}),
        ("get", "/api/v1/stock/ABCDEF/report", {}),
        ("get", "/api/v1/stock/00000A/ai-analysis", {}),
        ("get", "/api/v1/stock/1234567/valuation", {}),
        ("get", "/api/v1/stock/12-456/chart-data", {}),
        ("get", "/api/v1/position/suggest", {"params": {"code": "12345", "capital": 100_000}}),
        ("post", "/api/v1/watchlist", {"json": {"code": "ABCDEF"}}),
        ("post", "/api/v1/watchlist", {"json": {"code": "  "}}),
        ("delete", "/api/v1/watchlist/12345", {}),
    ],
)
def test_stock_code_must_be_exactly_six_digits(method: str, path: str, kwargs: dict) -> None:
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 422


def test_chart_period_rejects_unsupported_value() -> None:
    response = client.get("/api/v1/stock/000001/chart-data", params={"period": "30d"})

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/v1/ranking", {"params": {"top_n": 0}}),
        ("get", "/api/v1/ranking/export.csv", {"params": {"top_n": 0}}),
        ("post", "/api/v1/scan", {"json": {"top_n": 0}}),
        (
            "post",
            "/api/v1/backtest",
            {"json": {"start_date": "2026-01-01", "end_date": "2026-03-01", "top_n": 0}},
        ),
    ],
)
def test_top_n_must_be_positive(method: str, path: str, kwargs: dict) -> None:
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/industry/hot", {"top": 0}),
        ("/api/v1/industry/chain", {"industry": "银行", "top": 0}),
    ],
)
def test_industry_top_must_be_positive(path: str, params: dict) -> None:
    response = client.get(path, params=params)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/v1/position/suggest", {"params": {"code": "000001", "capital": -1}}),
        (
            "post",
            "/api/v1/backtest",
            {"json": {"start_date": "2026-01-01", "end_date": "2026-03-01", "initial_capital": -1}},
        ),
    ],
)
def test_capital_must_be_positive(method: str, path: str, kwargs: dict) -> None:
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "000001", "alert_above": -0.01},
        {"code": "000001", "alert_above": 100.01},
        {"code": "000001", "alert_below": -0.01},
        {"code": "000001", "alert_below": 100.01},
    ],
)
def test_watchlist_alert_thresholds_stay_between_zero_and_one_hundred(payload: dict) -> None:
    response = client.post("/api/v1/watchlist", json=payload)

    assert response.status_code == 422


def test_backtest_rejects_reversed_date_range() -> None:
    response = client.post(
        "/api/v1/backtest",
        json={"start_date": "2026-03-01", "end_date": "2026-01-01"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rebalance_freq", "daily"),
        ("selection", "random"),
    ],
)
def test_backtest_rejects_unsupported_strategy_options(field: str, value: str) -> None:
    response = client.post(
        "/api/v1/backtest",
        json={"start_date": "2026-01-01", "end_date": "2026-03-01", field: value},
    )

    assert response.status_code == 422
