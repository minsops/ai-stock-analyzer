"""模拟券商。"""

from __future__ import annotations

from src.broker.base import Order, OrderResult, Position


class SimulatedBroker:
    """只在本地内存中撮合的模拟券商。"""

    def __init__(self, initial_cash: float = 100_000) -> None:
        self.cash = float(initial_cash)
        self.positions: dict[str, Position] = {}

    def get_cash(self) -> float:
        return self.cash

    def get_positions(self) -> dict[str, Position]:
        return dict(self.positions)

    def submit_order(self, order: Order) -> OrderResult:
        if order.quantity <= 0:
            return OrderResult(False, order, "数量必须大于 0")
        if order.price <= 0:
            return OrderResult(False, order, "价格必须大于 0")
        if order.side == "buy":
            return self._buy(order)
        if order.side == "sell":
            return self._sell(order)
        return OrderResult(False, order, "未知交易方向")

    def _buy(self, order: Order) -> OrderResult:
        cost = order.quantity * order.price
        if cost > self.cash:
            return OrderResult(False, order, "现金不足")
        old = self.positions.get(order.code)
        if old is None:
            self.positions[order.code] = Position(order.code, order.quantity, order.price)
        else:
            total_quantity = old.quantity + order.quantity
            average_cost = (old.quantity * old.average_cost + cost) / total_quantity
            self.positions[order.code] = Position(order.code, total_quantity, average_cost)
        self.cash -= cost
        return OrderResult(True, order, "成交", order.quantity, order.price)

    def _sell(self, order: Order) -> OrderResult:
        old = self.positions.get(order.code)
        if old is None or old.quantity < order.quantity:
            return OrderResult(False, order, "持仓不足")
        self.cash += order.quantity * order.price
        remaining = old.quantity - order.quantity
        if remaining:
            self.positions[order.code] = Position(order.code, remaining, old.average_cost)
        else:
            self.positions.pop(order.code, None)
        return OrderResult(True, order, "成交", order.quantity, order.price)

