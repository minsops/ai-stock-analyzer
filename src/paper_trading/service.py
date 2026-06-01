"""模拟盘服务。"""

from __future__ import annotations

from src.broker import Order, SimulatedBroker
from config import settings
from src.execution import ExecutionEngine


class PaperTradingService:
    """根据候选池在模拟账户中构建等权组合。"""

    def __init__(self, broker: SimulatedBroker | None = None, execution_engine: ExecutionEngine | None = None) -> None:
        self.broker = broker or SimulatedBroker()
        self.execution_engine = execution_engine or ExecutionEngine(self.broker)

    def rebalance_equal_weight(self, candidates: list[dict], total_slots: int = 10) -> list[dict]:
        """按候选股等权买入，返回订单结果。"""
        selected = candidates[:total_slots]
        if not selected:
            return []
        available_cash = self.broker.get_cash()
        total_capital = available_cash + sum(position.market_value for position in self.broker.get_positions().values())
        cash_per_stock = min(available_cash / len(selected), total_capital * settings.MAX_SINGLE_POSITION)
        results: list[dict] = []
        for item in selected:
            price = float(item.get("price") or item.get("close") or 0)
            code = str(item.get("code"))
            if price <= 0:
                results.append({"code": code, "accepted": False, "message": "缺少有效价格"})
                continue
            quantity = int(cash_per_stock // price // 100 * 100)
            if quantity <= 0:
                results.append({"code": code, "accepted": False, "message": "资金不足以买入一手"})
                continue
            result = self.execution_engine.submit_order(Order(code=code, side="buy", quantity=quantity, price=price))
            results.append({"code": code, "accepted": result.accepted, "message": result.message, "quantity": result.filled_quantity})
        return results
