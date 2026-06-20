from __future__ import annotations

import pandas as pd
import schedule

from src.scheduler import SchedulerService


class FakeUpdater:
    def update(self, full: bool = False):
        class Summary:
            def to_dict(self):
                return {"full": full}

        return Summary()


class FakeRanker:
    def scan_all(self, top_n: int = 20) -> pd.DataFrame:
        return pd.DataFrame({"code": ["000001"]})


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []

    def send(self, title: str, content: str, level: str = "info") -> int:
        self.messages.append((title, content, level))
        return 1


def test_scheduler_runs_update_and_scan_jobs() -> None:
    notifier = FakeNotifier()
    service = SchedulerService(FakeUpdater(), FakeRanker(), notifier=notifier)  # type: ignore[arg-type]

    update = service.run_daily_update()
    scan = service.run_daily_scan(top_n=1)

    assert update.ok
    assert scan.ok
    assert len(notifier.messages) == 2


def test_register_daily_jobs_only_update_and_scan_by_default() -> None:
    sched = schedule.Scheduler()
    service = SchedulerService(FakeUpdater(), FakeRanker(), notifier=FakeNotifier(), schedule_module=sched)  # type: ignore[arg-type]

    service.register_daily_jobs()

    # 未提供 news_fn/capital_fn 时只登记 更新 + 扫描 两个任务
    assert len(sched.jobs) == 2


def test_register_daily_jobs_adds_optional_news_and_capital() -> None:
    sched = schedule.Scheduler()
    service = SchedulerService(
        FakeUpdater(),
        FakeRanker(),
        notifier=FakeNotifier(),
        news_fn=lambda: {"news": 1},
        capital_fn=lambda: {"capital": 1},
        schedule_module=sched,
    )  # type: ignore[arg-type]

    service.register_daily_jobs()

    # 更新 + 资金 + 消息 + 扫描 = 4 个任务
    assert len(sched.jobs) == 4


def test_run_daily_news_and_capital_skip_when_unset() -> None:
    service = SchedulerService(FakeUpdater(), FakeRanker(), notifier=FakeNotifier())  # type: ignore[arg-type]

    news = service.run_daily_news()
    capital = service.run_daily_capital()

    assert news.ok and news.detail == "skipped"
    assert capital.ok and capital.detail == "skipped"


class FakeRankerWithStorage:
    def __init__(self, alerts: list[dict]) -> None:
        self.storage = self  # 既当 ranker.storage 又提供 check_watchlist_alerts
        self._alerts = alerts

    def scan_all(self, top_n: int = 20) -> pd.DataFrame:
        return pd.DataFrame({"code": ["000001"]})

    def check_watchlist_alerts(self) -> list[dict]:
        return self._alerts


def test_run_watchlist_alerts_notifies_when_triggered() -> None:
    notifier = FakeNotifier()
    ranker = FakeRankerWithStorage([{"code": "000001", "score": 80.0, "type": "above", "threshold": 70}])
    service = SchedulerService(FakeUpdater(), ranker, notifier=notifier)  # type: ignore[arg-type]

    res = service.run_watchlist_alerts()

    assert res.ok and res.detail == {"triggered": 1}
    assert any("自选评分提醒" in m[0] for m in notifier.messages)


def test_run_watchlist_alerts_skip_without_storage() -> None:
    service = SchedulerService(FakeUpdater(), FakeRanker(), notifier=FakeNotifier())  # type: ignore[arg-type]
    res = service.run_watchlist_alerts()
    assert res.ok and res.detail == "skipped"


def test_run_daily_news_and_capital_invoke_callables() -> None:
    calls: list[str] = []
    service = SchedulerService(
        FakeUpdater(),
        FakeRanker(),
        notifier=FakeNotifier(),
        news_fn=lambda: calls.append("news") or {"updated": 5},
        capital_fn=lambda: calls.append("capital") or {"updated": 3},
    )  # type: ignore[arg-type]

    news = service.run_daily_news()
    capital = service.run_daily_capital()

    assert news.ok and news.detail == {"updated": 5}
    assert capital.ok and capital.detail == {"updated": 3}
    assert calls == ["news", "capital"]
