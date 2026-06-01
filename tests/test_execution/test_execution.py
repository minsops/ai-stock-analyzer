from __future__ import annotations

from src.broker import Order, SimulatedBroker
from src.execution import ExecutionEngine


def test_execution_engine_rejects_order_by_risk() -> None:
    broker = SimulatedBroker(initial_cash=10_000)
    engine = ExecutionEngine(broker)

    result = engine.submit_order(Order("000001", "buy", 1000, 10), total_capital=10_000)

    assert not result.accepted
    assert "单笔买入超过单只仓位上限" in result.message


def test_execution_engine_accepts_valid_order() -> None:
    broker = SimulatedBroker(initial_cash=10_000)
    engine = ExecutionEngine(broker)

    result = engine.submit_order(Order("000001", "buy", 100, 10), total_capital=10_000)

    assert result.accepted
    assert broker.get_positions()["000001"].quantity == 100

