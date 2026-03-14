"""Strategy evaluation logic."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from src.data.espn_game_clock import ESPNGameClockClient, ESPNUnavailableError

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrategyDecision:
    should_place_entry_order: bool
    continue_monitoring: bool
    reason: str


class StrategyEvaluator:
    """Gate strategy entries on odds quality and game clock context."""

    def __init__(self, game_clock_client: ESPNGameClockClient | None = None):
        self.game_clock_client = game_clock_client or ESPNGameClockClient()

    def evaluate(self, game_id: str, implied_win_probability: float) -> StrategyDecision:
        if not 0.92 <= implied_win_probability <= 0.97:
            return StrategyDecision(
                should_place_entry_order=False,
                continue_monitoring=True,
                reason="win_probability_out_of_range",
            )

        try:
            late_game = self.game_clock_client.is_late_game(game_id)
        except ESPNUnavailableError:
            LOGGER.warning(
                "ESPN unavailable during strategy evaluation; skipping new entry orders and continuing monitoring.",
                extra={"game_id": game_id},
            )
            return StrategyDecision(
                should_place_entry_order=False,
                continue_monitoring=True,
                reason="espn_unavailable",
            )

        if not late_game:
            return StrategyDecision(
                should_place_entry_order=False,
                continue_monitoring=True,
                reason="not_late_game",
            )

        return StrategyDecision(
            should_place_entry_order=True,
            continue_monitoring=True,
            reason="entry_conditions_met",
        )
