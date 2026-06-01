from __future__ import annotations

from src.broker import Order, SimulatedBroker


def test_simulated_broker_buy_and_sell() -> None:
    broker = SimulatedBroker(initial_cash=10_000)

    buy = broker.submit_order(Order("000001", "buy", 100, 10))
    sell = broker.submit_order(Order("000001", "sell", 50, 11))

    assert buy.accepted
    assert sell.accepted
    assert broker.get_positions()["000001"].quantity == 50
    assert broker.get_cash() == 9550


def test_simulated_broker_rejects_insufficient_cash() -> None:
    broker = SimulatedBroker(initial_cash=100)

    result = broker.submit_order(Order("000001", "buy", 100, 10))

    assert not result.accepted
    assert result.message == "现金不足"

