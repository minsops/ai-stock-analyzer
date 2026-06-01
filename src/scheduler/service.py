"""阶段二定时任务服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import schedule
from loguru import logger

from src.data_layer import DataUpdater
from src.fusion import StockRanker
from src.notification import NotificationService


@dataclass
class ScheduledJobResult:
    """调度任务结果。"""

    name: str
    ok: bool
    detail: dict | str


class SchedulerService:
    """每日数据更新、扫描和通知调度器。"""

    def __init__(
        self,
        updater: DataUpdater,
        ranker: StockRanker,
        notifier: NotificationService | None = None,
        schedule_module=schedule,
    ) -> None:
        self.updater = updater
        self.ranker = ranker
        self.notifier = notifier or NotificationService()
        self.schedule = schedule_module

    def register_daily_jobs(self, update_time: str = "17:30", scan_time: str = "18:00", top_n: int = 20) -> None:
        """注册每日增量更新和扫描任务。"""
        self.schedule.every().day.at(update_time).do(self.run_daily_update)
        self.schedule.every().day.at(scan_time).do(self.run_daily_scan, top_n=top_n)
        logger.info(f"已注册每日任务: 更新 {update_time}, 扫描 {scan_time}")

    def run_pending(self) -> None:
        """执行到期任务。"""
        self.schedule.run_pending()

    def run_daily_update(self) -> ScheduledJobResult:
        """执行每日增量更新。"""
        try:
            summary = self.updater.update(full=False)
            self.notifier.send("每日数据更新完成", str(summary.to_dict()))
            return ScheduledJobResult("daily_update", True, summary.to_dict())
        except Exception as exc:  # noqa: BLE001
            self.notifier.send("每日数据更新失败", str(exc), level="error")
            return ScheduledJobResult("daily_update", False, str(exc))

    def run_daily_scan(self, top_n: int = 20) -> ScheduledJobResult:
        """执行每日扫描。"""
        try:
            result = self.ranker.scan_all(top_n=top_n)
            self.notifier.send("每日扫描完成", f"生成 Top {len(result)} 排行榜")
            return ScheduledJobResult("daily_scan", True, {"top_n": top_n, "rows": len(result)})
        except Exception as exc:  # noqa: BLE001
            self.notifier.send("每日扫描失败", str(exc), level="error")
            return ScheduledJobResult("daily_scan", False, str(exc))

