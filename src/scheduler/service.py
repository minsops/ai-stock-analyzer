"""阶段二定时任务服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

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
        schedule_module: Any = schedule,
        news_fn: Callable[[], dict | str] | None = None,
        capital_fn: Callable[[], dict | str] | None = None,
    ) -> None:
        self.updater = updater
        self.ranker = ranker
        self.notifier = notifier or NotificationService()
        self.schedule = schedule_module
        # 可选的消息面/资金面刷新回调；提供时才会被注册为每日任务。
        self.news_fn = news_fn
        self.capital_fn = capital_fn

    def register_daily_jobs(self, update_time: str = "17:30", scan_time: str = "18:00", top_n: int = 20) -> None:
        """注册每日增量更新和扫描任务(扫描前先刷新可选的消息面/资金面)。"""
        self.schedule.every().day.at(update_time).do(self.run_daily_update)
        if self.capital_fn is not None:
            self.schedule.every().day.at(update_time).do(self.run_daily_capital)
        if self.news_fn is not None:
            self.schedule.every().day.at(update_time).do(self.run_daily_news)
        self.schedule.every().day.at(scan_time).do(self.run_daily_scan, top_n=top_n)
        logger.info(
            f"已注册每日任务: 更新 {update_time}, 扫描 {scan_time}"
            f"{' (+资金)' if self.capital_fn else ''}{' (+消息)' if self.news_fn else ''}"
        )

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
        """执行每日扫描，扫描后用最新评分检查自选提醒。"""
        try:
            result = self.ranker.scan_all(top_n=top_n)
            self.notifier.send("每日扫描完成", f"生成 Top {len(result)} 排行榜")
            self.run_watchlist_alerts()
            return ScheduledJobResult("daily_scan", True, {"top_n": top_n, "rows": len(result)})
        except Exception as exc:  # noqa: BLE001
            self.notifier.send("每日扫描失败", str(exc), level="error")
            return ScheduledJobResult("daily_scan", False, str(exc))

    def run_watchlist_alerts(self) -> ScheduledJobResult:
        """用最近评分检查自选阈值，触发则推送通知。失败不影响扫描。"""
        storage = getattr(self.ranker, "storage", None)
        if storage is None or not hasattr(storage, "check_watchlist_alerts"):
            return ScheduledJobResult("watchlist_alerts", True, "skipped")
        try:
            alerts = storage.check_watchlist_alerts()
            if alerts:
                lines = [
                    f"{a['code']} 评分 {a['score']:.1f} {'≥' if a['type'] == 'above' else '≤'} 阈值 {a['threshold']:.0f}"
                    for a in alerts
                ]
                self.notifier.send("自选评分提醒", "；".join(lines))
            return ScheduledJobResult("watchlist_alerts", True, {"triggered": len(alerts)})
        except Exception as exc:  # noqa: BLE001
            return ScheduledJobResult("watchlist_alerts", False, str(exc))

    def run_daily_news(self) -> ScheduledJobResult:
        """执行每日消息面刷新(可选)。失败不影响扫描。"""
        if self.news_fn is None:
            return ScheduledJobResult("daily_news", True, "skipped")
        try:
            detail = self.news_fn()
            return ScheduledJobResult("daily_news", True, detail)
        except Exception as exc:  # noqa: BLE001
            self.notifier.send("每日消息面更新失败", str(exc), level="error")
            return ScheduledJobResult("daily_news", False, str(exc))

    def run_daily_capital(self) -> ScheduledJobResult:
        """执行每日资金面刷新(可选，需能连东财)。失败不影响扫描。"""
        if self.capital_fn is None:
            return ScheduledJobResult("daily_capital", True, "skipped")
        try:
            detail = self.capital_fn()
            return ScheduledJobResult("daily_capital", True, detail)
        except Exception as exc:  # noqa: BLE001
            self.notifier.send("每日资金面更新失败", str(exc), level="error")
            return ScheduledJobResult("daily_capital", False, str(exc))
