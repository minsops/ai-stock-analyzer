"""订单执行引擎。"""

from __future__ import annotations

from src.broker import Broker, Order, OrderResult
from src.risk.risk_manager import RiskManager


class ExecutionEngine:
    """阶段三执行引擎，默认搭配模拟券商。"""

    def __init__(self, broker: Broker, risk_manager: RiskManager | None = None) -> None:
        self.broker = broker
        self.risk_manager = risk_manager or RiskManager()

    def submit_order(self, order: Order, total_capital: float | None = None) -> OrderResult:
        """风控通过后提交订单。"""
        check = self.risk_manager.validate_order(order, self.broker.get_positions(), self.broker.get_cash(), total_capital)
        if not check["passed"]:
            return OrderResult(False, order, "；".join(check["reasons"]))
        return self.broker.submit_order(order)

