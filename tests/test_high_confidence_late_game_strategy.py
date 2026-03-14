from datetime import datetime, timedelta, timezone

from high_confidence_late_game_strategy import HighConfidenceLateGameStrategy, PositionState


class FakePolymarketClient:
    def __init__(self, probs):
        self.probs = probs
        self.calls = []

    def get_implied_probability(self, market_id: str, outcome_id: str) -> float:
        self.calls.append((market_id, outcome_id))
        return self.probs[(market_id, outcome_id)]


class FakeOrderExecutor:
    def __init__(self):
        self.calls = []

    def place_sell_order(self, market_id: str, outcome_id: str, size: float) -> str:
        self.calls.append((market_id, outcome_id, size))
        return "sell-123"


def test_sells_and_persists_exit_metadata_when_prob_below_threshold():
    pm = FakePolymarketClient({("m1", "o1"): 0.2})
    ex = FakeOrderExecutor()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    strategy = HighConfidenceLateGameStrategy(pm, ex)
    strategy.tracked_games["g1"] = PositionState(
        market_id="m1",
        outcome_id="o1",
        entry_order_id="entry-1",
        status="open",
        size=15.0,
    )

    strategy.monitor_positions(now=now)

    position = strategy.tracked_games["g1"]
    assert ex.calls == [("m1", "o1", 15.0)]
    assert position.status == "closed"
    assert position.exit_prob == 0.2
    assert position.exit_timestamp == now
    assert position.exit_order_id == "sell-123"


def test_ignores_games_without_open_position():
    pm = FakePolymarketClient({("m1", "o1"): 0.1})
    ex = FakeOrderExecutor()
    strategy = HighConfidenceLateGameStrategy(pm, ex)
    strategy.tracked_games["g1"] = PositionState(
        market_id="m1",
        outcome_id="o1",
        status="pending_entry",
        size=0,
    )

    strategy.monitor_positions()

    assert not pm.calls
    assert not ex.calls


def test_debounces_when_previous_sell_attempt_is_pending():
    pm = FakePolymarketClient({("m1", "o1"): 0.1})
    ex = FakeOrderExecutor()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    strategy = HighConfidenceLateGameStrategy(pm, ex)
    strategy.tracked_games["g1"] = PositionState(
        market_id="m1",
        outcome_id="o1",
        status="open",
        size=5,
        sell_attempt_pending_until=now + timedelta(seconds=30),
    )

    strategy.monitor_positions(now=now)

    assert not pm.calls
    assert not ex.calls


def test_uses_partial_exit_size_when_configured():
    pm = FakePolymarketClient({("m1", "o1"): 0.2})
    ex = FakeOrderExecutor()

    strategy = HighConfidenceLateGameStrategy(pm, ex, partial_exit_size=2.5)
    strategy.tracked_games["g1"] = PositionState(
        market_id="m1",
        outcome_id="o1",
        status="open",
        size=10,
    )

    strategy.monitor_positions()

    assert ex.calls == [("m1", "o1", 2.5)]
