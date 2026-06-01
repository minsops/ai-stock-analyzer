from __future__ import annotations

from src.notification import NotificationMessage, NotificationService


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> bool:
        self.messages.append(message)
        return True


def test_notification_service_sends_to_notifiers() -> None:
    notifier = FakeNotifier()

    count = NotificationService([notifier]).send("标题", "内容")

    assert count == 1
    assert notifier.messages[0].title == "标题"

