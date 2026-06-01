from __future__ import annotations

from src.broker import SimulatedBroker
from src.paper_trading import PaperTradingService


def test_paper_trading_equal_weight_buys_candidates() -> None:
    broker = SimulatedBroker(initial_cash=100_000)
    service = PaperTradingService(broker=broker)

    results = service.rebalance_equal_weight([{"code": "000001", "price": 10}, {"code": "000002", "price": 20}], total_slots=2)

    assert len(results) == 2
    assert all(item["accepted"] for item in results)
    assert set(broker.get_positions()) == {"000001", "000002"}

