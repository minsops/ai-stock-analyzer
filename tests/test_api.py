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
    def __init__(self) -> None:
        self.scan_calls: list[tuple[int, dict]] = []

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

    def scan_all(self, top_n: int = 50, filters: dict | None = None) -> pd.DataFrame:
        self.scan_calls.append((top_n, filters or {}))
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
    fake_ranker = FakeRanker()
    monkeypatch.setattr(scan, "get_ranker", lambda: fake_ranker)

    create_response = client.post("/api/v1/scan", json={"top_n": 1, "filters": {"exclude_st": False}})
    task_id = create_response.json()["task_id"]
    status_response = client.get(f"/api/v1/scan/{task_id}")

    assert create_response.status_code == 200
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert status_response.json()["result"][0]["code"] == "000001"
    assert fake_ranker.scan_calls == [(1, {"exclude_st": False})]


def test_scan_rejects_unknown_or_invalid_filter_overrides(monkeypatch) -> None:
    monkeypatch.setattr(scan, "get_ranker", lambda: FakeRanker())

    unknown = client.post("/api/v1/scan", json={"filters": {"unknown_rule": True}})
    wrong_type = client.post("/api/v1/scan", json={"filters": {"exclude_st": "false"}})
    negative = client.post("/api/v1/scan", json={"filters": {"min_daily_amount": -1}})
    invalid_range = client.post(
        "/api/v1/scan",
        json={"filters": {"min_pe_ttm": 20, "max_pe_ttm": 10}},
    )

    assert unknown.status_code == 422
    assert wrong_type.status_code == 422
    assert negative.status_code == 422
    assert invalid_range.status_code == 422


def test_empty_regime_degrades_without_network(monkeypatch) -> None:
    from src.api import dependencies

    class EmptyRegimeStorage:
        def get_latest_market_regime(self) -> dict:
            return {}

    monkeypatch.setattr(dependencies, "get_storage", lambda: EmptyRegimeStorage())
    monkeypatch.setattr(dependencies, "get_fetcher", lambda: (_ for _ in ()).throw(AssertionError("network fallback called")))

    assert dependencies.get_current_regime() == ("shock", 0.3, {"reason": "市场数据不足，默认震荡"})


def test_ranking_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(ranking, "get_storage", lambda: FakeStorage())
    monkeypatch.setattr(ranking, "get_current_regime", lambda: ("shock", 0.65, {}))

    response = client.get("/api/v1/ranking?date=2026-06-02&top_n=1")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["name"] == "平安银行"
    assert item["industry"] == "银行"


def test_regime_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(regime, "get_current_regime", lambda: ("shock", 0.65, {"ma20": 1.0}))

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


def test_ranking_csv_export(monkeypatch) -> None:
    monkeypatch.setattr(ranking, "get_storage", lambda: FakeStorage())

    response = client.get("/api/v1/ranking/export.csv?top_n=5")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    body = response.content.decode("utf-8-sig")
    lines = [line for line in body.splitlines() if line]
    assert lines[0].split(",")[:3] == ["排名", "代码", "名称"]
    assert lines[1].startswith("1,000001,平安银行")


class FakeWatchStorage:
    def __init__(self) -> None:
        self._items: list[dict] = []

    def add_to_watchlist(self, code, note=None, group_name=None, alert_above=None, alert_below=None) -> bool:
        for it in self._items:
            if it["code"] == code:
                if group_name is not None:
                    it["group_name"] = group_name
                if alert_above is not None:
                    it["alert_above"] = alert_above
                if alert_below is not None:
                    it["alert_below"] = alert_below
                return False
        self._items.insert(0, {"code": code, "note": note, "group_name": group_name or "默认", "alert_above": alert_above, "alert_below": alert_below})
        return True

    def remove_from_watchlist(self, code: str) -> bool:
        before = len(self._items)
        self._items = [it for it in self._items if it["code"] != code]
        return len(self._items) < before

    def get_watchlist_full(self) -> list[dict]:
        return list(self._items)

    def check_watchlist_alerts(self) -> list[dict]:
        out = []
        for it in self._items:
            score = self.get_latest_score(it["code"]).get("composite_score")
            if score is None:
                continue
            if it.get("alert_above") is not None and score >= it["alert_above"]:
                out.append({"code": it["code"], "score": score, "type": "above", "threshold": it["alert_above"]})
            elif it.get("alert_below") is not None and score <= it["alert_below"]:
                out.append({"code": it["code"], "score": score, "type": "below", "threshold": it["alert_below"]})
        return out

    def get_stock_info(self, code: str) -> dict:
        return {"name": "平安银行", "industry_l1": "银行"}

    def get_latest_score(self, code: str) -> dict:
        return {"composite_score": 72.5, "score_date": date(2026, 6, 2)} if code == "000001" else {}


def test_watchlist_crud(monkeypatch) -> None:
    from src.api.routes import watchlist

    store = FakeWatchStorage()
    monkeypatch.setattr(watchlist, "get_storage", lambda: store)

    assert client.get("/api/v1/watchlist").json()["count"] == 0

    added = client.post("/api/v1/watchlist", json={"code": "000001"})
    assert added.status_code == 200 and added.json()["added"] is True
    # 重复加入不报错，added=False
    assert client.post("/api/v1/watchlist", json={"code": "000001"}).json()["added"] is False
    client.post("/api/v1/watchlist", json={"code": "600519"})

    listed = client.get("/api/v1/watchlist").json()
    assert listed["count"] == 2
    # 有评分的排在前
    assert listed["items"][0]["code"] == "000001"
    assert listed["items"][0]["composite_score"] == 72.5
    assert listed["items"][1]["composite_score"] is None

    removed = client.delete("/api/v1/watchlist/000001")
    assert removed.json()["removed"] is True
    assert client.get("/api/v1/watchlist").json()["count"] == 1


def test_watchlist_groups_and_alerts(monkeypatch) -> None:
    from src.api.routes import watchlist

    store = FakeWatchStorage()
    monkeypatch.setattr(watchlist, "get_storage", lambda: store)

    # 设分组 + 评分≥70 提醒(000001 评分 72.5 → 应触发)
    client.post("/api/v1/watchlist", json={"code": "000001", "group_name": "核心", "alert_above": 70})
    client.post("/api/v1/watchlist", json={"code": "600519", "group_name": "观察"})

    listed = client.get("/api/v1/watchlist").json()
    group_names = {g["name"] for g in listed["groups"]}
    assert group_names == {"核心", "观察"}
    core = next(it for it in listed["items"] if it["code"] == "000001")
    assert core["group"] == "核心" and core["alert_triggered"] == "above"

    alerts = client.get("/api/v1/watchlist/alerts").json()
    assert alerts["count"] == 1
    assert alerts["alerts"][0]["code"] == "000001" and alerts["alerts"][0]["name"] == "平安银行"


def test_watchlist_add_empty_code(monkeypatch) -> None:
    from src.api.routes import watchlist

    monkeypatch.setattr(watchlist, "get_storage", lambda: FakeWatchStorage())
    resp = client.post("/api/v1/watchlist", json={"code": "  "})
    assert resp.status_code == 422
