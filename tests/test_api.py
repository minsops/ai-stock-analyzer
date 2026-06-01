from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import ranking, regime, scan, stock


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_position_endpoint() -> None:
    response = client.get("/api/v1/position/suggest", params={"code": "000001", "capital": 100000, "composite_score": 80})

    assert response.status_code == 200
    assert response.json()["suggested_pct"] <= 0.2


def test_openapi_available() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "paths" in response.json()


class FakeRanker:
    def score_single(self, code: str) -> dict:
        return {
            "code": code,
            "name": "平安银行",
            "composite_score": 72.5,
            "regime": "shock",
            "weights": {"value": 0.3, "trend": 0.25, "capital": 0.2, "industry": 0.15, "event": 0.1},
            "engine_scores": {
                "value": {"score": 80, "confidence": 1, "signals": ["估值合理"], "details": {}, "available": True},
                "trend": {"score": 70, "confidence": 1, "signals": ["趋势偏强"], "details": {}, "available": True},
            },
            "conflicts": [],
            "filter_passed": True,
            "quarantined": False,
            "valuation": {"pe_percentile": 0.2},
            "scored_at": "2026-06-02T10:00:00",
        }

    def scan_all(self, top_n: int = 50) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "code": ["000001"],
                "score_date": [date(2026, 6, 2)],
                "composite_score": [72.5],
            }
        )


class FakeStorage:
    def get_quotes(self, code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        return pd.DataFrame({"trade_date": [date(2026, 6, 1)], "close": [10.0]})

    def get_top_scores(self, date: str, top_n: int = 50) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "code": ["000001"],
                "name": ["平安银行"],
                "industry": ["银行"],
                "composite_score": [72.5],
                "value_score": [80.0],
                "trend_score": [70.0],
                "capital_score": [60.0],
                "industry_score": [50.0],
                "event_score": [55.0],
            }
        )

    def get_financial_history(self, code: str) -> pd.DataFrame:
        return pd.DataFrame({"report_date": [date(2026, 3, 31)], "pe_ttm": [8.0], "pb": [0.8]})


class FakeFetcher:
    def get_market_overview(self) -> dict:
        return {
            "hs300": [{"date": f"2026-03-{day:02d}", "close": 3000 + day} for day in range(1, 29)]
            + [{"date": f"2026-04-{day:02d}", "close": 3030 + day} for day in range(1, 29)]
            + [{"date": f"2026-05-{day:02d}", "close": 3060 + day} for day in range(1, 29)],
            "advancers": 2000,
            "decliners": 1800,
        }


def test_stock_score_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(stock, "get_ranker", lambda: FakeRanker())

    response = client.get("/api/v1/stock/000001/score")

    assert response.status_code == 200
    assert response.json()["code"] == "000001"
    assert response.json()["engine_scores"]["value"]["signals"] == ["估值合理"]


def test_stock_valuation_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(stock, "get_storage", lambda: FakeStorage())

    response = client.get("/api/v1/stock/000001/valuation")

    assert response.status_code == 200
    assert response.json()["metrics"]["pe_ttm"]["current_value"] == 8.0


def test_stock_chart_data_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(stock, "get_storage", lambda: FakeStorage())

    response = client.get("/api/v1/stock/000001/chart-data?period=60d")

    assert response.status_code == 200
    assert response.json()["quotes"][0]["close"] == 10.0


def test_scan_endpoints(monkeypatch) -> None:
    scan.TASKS.clear()
    monkeypatch.setattr(scan, "get_ranker", lambda: FakeRanker())

    create_response = client.post("/api/v1/scan", json={"top_n": 1, "filters": {}})
    task_id = create_response.json()["task_id"]
    status_response = client.get(f"/api/v1/scan/{task_id}")

    assert create_response.status_code == 200
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert status_response.json()["result"][0]["code"] == "000001"


def test_ranking_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(ranking, "get_storage", lambda: FakeStorage())
    monkeypatch.setattr(ranking, "get_fetcher", lambda: FakeFetcher())

    response = client.get("/api/v1/ranking?date=2026-06-02&top_n=1")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["name"] == "平安银行"
    assert item["industry"] == "银行"


def test_regime_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(regime, "get_fetcher", lambda: FakeFetcher())

    response = client.get("/api/v1/regime")

    assert response.status_code == 200
    assert response.json()["regime"] in {"bull", "bear", "shock", "extreme_fear", "extreme_greed"}


def test_backtest_endpoint(monkeypatch) -> None:
    from src.api.routes import backtest

    class EmptyBacktestStorage:
        def get_all_active_codes(self) -> list[str]:
            return []

    monkeypatch.setattr(backtest, "get_storage", lambda: EmptyBacktestStorage())

    response = client.post(
        "/api/v1/backtest",
        json={"start_date": "2026-01-01", "end_date": "2026-03-01", "top_n": 1},
    )

    assert response.status_code == 200
    assert response.json()["metrics"]["trading_days"] == 0
