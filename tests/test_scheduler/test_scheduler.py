from __future__ import annotations

import pandas as pd

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
