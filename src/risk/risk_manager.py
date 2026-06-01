"""扩展风控校验。"""

from __future__ import annotations

from src.broker.base import Order, Position
from config import settings


class RiskManager:
    """订单级风控。"""

    def validate_order(
        self,
        order: Order,
        current_positions: dict[str, Position],
        cash: float,
        total_capital: float | None = None,
    ) -> dict:
        reasons: list[str] = []
        total_capital = total_capital or cash + sum(position.market_value for position in current_positions.values())
        amount = order.quantity * order.price
        if order.quantity <= 0:
            reasons.append("订单数量必须大于 0")
        if order.price <= 0:
            reasons.append("订单价格必须大于 0")
        if order.side == "buy":
            if amount > cash:
                reasons.append("现金不足")
            if total_capital > 0 and amount / total_capital > settings.MAX_SINGLE_POSITION:
                reasons.append("单笔买入超过单只仓位上限")
        elif order.side == "sell":
            position = current_positions.get(order.code)
            if position is None or position.quantity < order.quantity:
                reasons.append("卖出数量超过持仓")
        else:
            reasons.append("未知交易方向")
        return {"passed": not reasons, "reasons": reasons}

