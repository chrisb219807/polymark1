from src.data.espn_game_clock import ESPNUnavailableError
from src.strategy.evaluator import StrategyEvaluator


class LateGameClient:
    def is_late_game(self, game_id: str, threshold_seconds: int = 480) -> bool:
        return True


class EarlyGameClient:
    def is_late_game(self, game_id: str, threshold_seconds: int = 480) -> bool:
        return False


class UnavailableClient:
    def is_late_game(self, game_id: str, threshold_seconds: int = 480) -> bool:
        raise ESPNUnavailableError("down")


def test_places_entry_when_probability_in_range_and_late_game():
    evaluator = StrategyEvaluator(game_clock_client=LateGameClient())
    decision = evaluator.evaluate("123", implied_win_probability=0.95)

    assert decision.should_place_entry_order
    assert decision.reason == "entry_conditions_met"


def test_blocks_entry_when_not_late_game():
    evaluator = StrategyEvaluator(game_clock_client=EarlyGameClient())
    decision = evaluator.evaluate("123", implied_win_probability=0.95)

    assert not decision.should_place_entry_order
    assert decision.reason == "not_late_game"


def test_blocks_entry_when_probability_out_of_range():
    evaluator = StrategyEvaluator(game_clock_client=LateGameClient())
    decision = evaluator.evaluate("123", implied_win_probability=0.91)

    assert not decision.should_place_entry_order
    assert decision.reason == "win_probability_out_of_range"


def test_espn_unavailable_falls_back_to_monitoring_only():
    evaluator = StrategyEvaluator(game_clock_client=UnavailableClient())
    decision = evaluator.evaluate("123", implied_win_probability=0.95)

    assert not decision.should_place_entry_order
    assert decision.continue_monitoring
    assert decision.reason == "espn_unavailable"
