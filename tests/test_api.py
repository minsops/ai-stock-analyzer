from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app


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
