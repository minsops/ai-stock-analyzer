"""券商接口抽象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Order:
    """订单。"""

    code: str
    side: str
    quantity: int
    price: float


@dataclass
class OrderResult:
    """订单结果。"""

    accepted: bool
    order: Order
    message: str
    filled_quantity: int = 0
    average_price: float | None = None


@dataclass
class Position:
    """持仓。"""

    code: str
    quantity: int
    average_cost: float

    @property
    def market_value(self) -> float:
        return self.quantity * self.average_cost


class Broker(Protocol):
    """券商接口协议。"""

    def get_cash(self) -> float:
        """读取现金。"""

    def get_positions(self) -> dict[str, Position]:
        """读取持仓。"""

    def submit_order(self, order: Order) -> OrderResult:
        """提交订单。"""

