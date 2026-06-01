"""本地通知服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from loguru import logger


@dataclass
class NotificationMessage:
    """通知消息。"""

    title: str
    content: str
    level: str = "info"
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.now()


class Notifier(Protocol):
    """通知器协议。"""

    def send(self, message: NotificationMessage) -> bool:
        """发送通知。"""


class ConsoleNotifier:
    """终端日志通知器，作为阶段二默认实现。"""

    def send(self, message: NotificationMessage) -> bool:
        logger.info(f"[通知:{message.level}] {message.title} - {message.content}")
        return True


class NotificationService:
    """通知服务，支持多个通知器。"""

    def __init__(self, notifiers: list[Notifier] | None = None) -> None:
        self.notifiers = notifiers or [ConsoleNotifier()]

    def send(self, title: str, content: str, level: str = "info") -> int:
        """发送通知，返回成功数量。"""
        message = NotificationMessage(title=title, content=content, level=level)
        success = 0
        for notifier in self.notifiers:
            try:
                success += int(notifier.send(message))
            except Exception as exc:  # noqa: BLE001 - 单个通知器失败不影响其他通知器
                logger.warning(f"通知发送失败，已跳过: {exc}")
        return success

