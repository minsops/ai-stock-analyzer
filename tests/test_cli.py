"""CLI command tests with all external side effects isolated."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest
from click.testing import CliRunner

from src.cli import main as cli_main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_init_db_initializes_storage(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeStorage:
        def init_db(self) -> None:
            calls.append("init_db")

    monkeypatch.setattr(cli_main, "DataStorage", FakeStorage)

    result = runner.invoke(cli_main.cli, ["init-db"])

    assert result.exit_code == 0, result.output
    assert calls == ["init_db"]


def test_update_data_forwards_cli_options(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = object()
    storage = object()
    captured: dict[str, object] = {}

    class FakeUpdater:
        def __init__(self, actual_fetcher: object, actual_storage: object) -> None:
            assert actual_fetcher is fetcher
            assert actual_storage is storage

        def update(self, **kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(to_dict=lambda: {"updated": 2})

    monkeypatch.setattr(cli_main, "make_fetcher", lambda source: fetcher if source == "baostock" else None)
    monkeypatch.setattr(cli_main, "DataStorage", lambda: storage)
    monkeypatch.setattr(cli_main, "DataUpdater", FakeUpdater)

    result = runner.invoke(
        cli_main.cli,
        [
            "update-data",
            "--full",
            "--limit",
            "2",
            "--sample",
            "1",
            "--codes",
            "000001, 600519",
            "--years",
            "3",
            "--workers",
            "4",
            "--source",
            "baostock",
            "--include-slow-data",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "full": True,
        "limit": 2,
        "include_slow_data": True,
        "codes": ["000001", "600519"],
        "sample": 1,
        "max_workers": 4,
        "years": 3,
    }


def test_score_runs_local_score_and_optional_ai(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = object()
    fetcher = object()
    report = {"code": "000001"}
    calls: list[object] = []

    class FakeRanker:
        def __init__(self) -> None:
            self.storage = storage
            self.fetcher = fetcher

        def score_single(self, code: str) -> dict[str, str]:
            calls.append(("score", code))
            return report

    monkeypatch.setattr(cli_main, "make_ranker", FakeRanker)
    monkeypatch.setattr(
        cli_main,
        "ensure_recent_quotes",
        lambda actual_storage, actual_fetcher, code: calls.append(("ensure", actual_storage, actual_fetcher, code)),
    )
    monkeypatch.setattr(cli_main, "render_score_report", lambda actual: calls.append(("render", actual)))
    monkeypatch.setattr(cli_main, "LLMAnalyst", lambda: SimpleNamespace(analyze=lambda actual: {"report": actual}))
    monkeypatch.setattr(cli_main, "render_ai_analysis", lambda actual: calls.append(("ai", actual)))

    result = runner.invoke(cli_main.cli, ["score", "000001", "--ai"])

    assert result.exit_code == 0, result.output
    assert calls == [
        ("ensure", storage, fetcher, "000001"),
        ("score", "000001"),
        ("render", report),
        ("ai", {"report": report}),
    ]


def test_scan_renders_ranked_rows(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    rows = pd.DataFrame(
        [{"code": "000001", "name": "平安银行", "industry": "银行", "composite_score": 88.5}]
    )
    monkeypatch.setattr(
        cli_main,
        "make_ranker",
        lambda: SimpleNamespace(scan_all=lambda top_n: calls.append(top_n) or rows),
    )

    result = runner.invoke(cli_main.cli, ["scan", "--top-n", "7"])

    assert result.exit_code == 0, result.output
    assert calls == [7]


def test_regime_uses_persisted_market_state(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = object()
    detector = object()
    calls: list[tuple[object, object]] = []
    monkeypatch.setattr(cli_main, "DataStorage", lambda: storage)
    monkeypatch.setattr(cli_main, "RegimeDetector", lambda: detector)
    monkeypatch.setattr(
        cli_main,
        "resolve_local_regime",
        lambda actual_storage, actual_detector: calls.append((actual_storage, actual_detector))
        or ("bull", 0.85, {"source": "persisted"}),
    )

    result = runner.invoke(cli_main.cli, ["regime"])

    assert result.exit_code == 0, result.output
    assert calls == [(storage, detector)]
    assert "bull" in result.output


def test_valuation_computes_all_metrics(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = object()
    calls: list[tuple[str, str]] = []

    class FakeValuation:
        def __init__(self, actual_storage: object) -> None:
            assert actual_storage is storage

        def compute_percentile(self, code: str, metric: str) -> dict[str, object]:
            calls.append((code, metric))
            return {"current_value": 12.5, "percentile": 0.3, "assessment": "normal"}

    monkeypatch.setattr(cli_main, "DataStorage", lambda: storage)
    monkeypatch.setattr(cli_main, "HistoricalValuation", FakeValuation)

    result = runner.invoke(cli_main.cli, ["valuation", "000001"])

    assert result.exit_code == 0, result.output
    assert calls == [
        ("000001", "pe_ttm"),
        ("000001", "pb"),
        ("000001", "ps_ttm"),
        ("000001", "dividend_yield"),
    ]


def test_position_forwards_industry_and_risk_inputs(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        cli_main,
        "PositionSizer",
        lambda: SimpleNamespace(
            suggest=lambda code, score, regime, capital, industry=None: calls.append(
                (code, score, regime, capital, industry)
            )
            or {"suggested_pct": 0.2}
        ),
    )

    result = runner.invoke(
        cli_main.cli,
        [
            "position",
            "000001",
            "--score",
            "82.5",
            "--regime",
            "bear",
            "--capital",
            "200000",
            "--industry",
            "银行",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("000001", 82.5, "bear", 200000.0, "银行")]


def test_backtest_forwards_complete_configuration(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = object()
    captured: list[dict[str, object]] = []

    class FakeSimulator:
        def __init__(self, actual_storage: object) -> None:
            assert actual_storage is storage

        def run(self, config: dict[str, object]) -> SimpleNamespace:
            captured.append(config)
            return SimpleNamespace(metrics={"total_return": 0.12})

    monkeypatch.setattr(cli_main, "DataStorage", lambda: storage)
    monkeypatch.setattr(cli_main, "BacktestSimulator", FakeSimulator)

    result = runner.invoke(
        cli_main.cli,
        [
            "backtest",
            "--start",
            "2024-01-01",
            "--end",
            "2024-12-31",
            "--top-n",
            "8",
            "--freq",
            "weekly",
            "--capital",
            "300000",
            "--method",
            "momentum",
            "--timing",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == [
        {
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "top_n": 8,
            "rebalance_freq": "weekly",
            "initial_capital": 300000.0,
            "selection": "momentum",
            "regime_timing": True,
        }
    ]


def test_serve_delegates_to_uvicorn_without_starting_server(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    fake_uvicorn = SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    result = runner.invoke(cli_main.cli, ["serve", "--port", "8765"])

    assert result.exit_code == 0, result.output
    assert calls == [(('src.api.main:app',), {"host": "0.0.0.0", "port": 8765, "reload": False})]


@pytest.mark.parametrize(
    ("refresh_result", "expected_text"),
    [
        ({"written": 0, "covered": 0}, "没有可更新的股票"),
        ({"written": 12, "covered": 2}, "写入 12 条"),
    ],
)
def test_update_news_handles_empty_and_success_results(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    refresh_result: dict[str, int],
    expected_text: str,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli_main,
        "_refresh_news",
        lambda **kwargs: calls.append(kwargs) or refresh_result,
    )

    result = runner.invoke(
        cli_main.cli,
        ["update-news", "--days", "5", "--limit", "6", "--workers", "2", "--codes", "000001, 600519"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [{"days": 5, "limit": 6, "workers": 2, "codes": ["000001", "600519"]}]
    assert expected_text in result.output


@pytest.mark.parametrize(
    ("refresh_result", "expected_text"),
    [
        ({"written": 0, "covered": 0, "failed": 0}, "没有可更新的股票"),
        ({"written": 9, "covered": 2, "failed": 1}, "失败 1"),
    ],
)
def test_update_capital_handles_empty_and_success_results(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    refresh_result: dict[str, int],
    expected_text: str,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli_main,
        "_refresh_capital",
        lambda **kwargs: calls.append(kwargs) or refresh_result,
    )

    result = runner.invoke(
        cli_main.cli,
        ["update-capital", "--workers", "3", "--codes", "000001,600519"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [{"workers": 3, "codes": ["000001", "600519"]}]
    assert expected_text in result.output


def test_schedule_run_once_executes_each_daily_step(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.scheduler as scheduler_package

    calls: list[object] = []
    fetcher = object()
    storage = object()
    ranker = object()

    class FakeService:
        def __init__(self, updater: object, actual_ranker: object, **kwargs: object) -> None:
            calls.append(("init", updater, actual_ranker, kwargs))

        def run_daily_update(self) -> SimpleNamespace:
            calls.append("update")
            return SimpleNamespace(ok=True, name="daily_update", detail={"updated": 2})

        def run_daily_capital(self) -> SimpleNamespace:
            calls.append("capital")
            return SimpleNamespace(ok=True, name="daily_capital", detail="skipped")

        def run_daily_news(self) -> SimpleNamespace:
            calls.append("news")
            return SimpleNamespace(ok=False, name="daily_news", detail="temporary failure")

        def run_daily_scan(self, top_n: int) -> SimpleNamespace:
            calls.append(("scan", top_n))
            return SimpleNamespace(ok=True, name="daily_scan", detail={"rows": top_n})

    updater = object()
    monkeypatch.setattr(scheduler_package, "SchedulerService", FakeService)
    monkeypatch.setattr(cli_main, "make_fetcher", lambda source: fetcher if source == "baostock" else None)
    monkeypatch.setattr(cli_main, "DataStorage", lambda: storage)
    monkeypatch.setattr(
        cli_main,
        "DataUpdater",
        lambda actual_fetcher, actual_storage: updater
        if (actual_fetcher, actual_storage) == (fetcher, storage)
        else None,
    )
    monkeypatch.setattr(cli_main, "make_ranker", lambda: ranker)

    result = runner.invoke(
        cli_main.cli,
        ["schedule", "--run-once", "--source", "baostock", "--top-n", "11", "--no-news", "--no-capital"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        ("init", updater, ranker, {"news_fn": None, "capital_fn": None}),
        "update",
        "capital",
        "news",
        ("scan", 11),
    ]
