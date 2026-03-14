"""High-confidence late-game entry strategy for basketball markets.

This strategy enforces a single entry per game and persists entry metadata to disk
so duplicate entries are prevented across process restarts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class HighConfidenceLateGameStrategy:
    """Buy-only strategy for high-probability late-game basketball markets."""

    def __init__(
        self,
        entry_min_prob: float = 0.92,
        entry_max_prob: float = 0.97,
        exit_prob: float = 0.33,
        max_bets_per_game: int = 1,
        state_path: str | Path = "data/placed_bets.json",
    ) -> None:
        self.entry_min_prob = entry_min_prob
        self.entry_max_prob = entry_max_prob
        self.exit_prob = exit_prob
        self.max_bets_per_game = max_bets_per_game
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()

    def _load_state(self) -> dict[str, dict[str, Any]]:
        if not self.state_path.exists():
            return {}

        try:
            with self.state_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load strategy state from %s: %s", self.state_path, exc)
            return {}

        if not isinstance(data, dict):
            logger.warning("State file %s does not contain a dict; resetting", self.state_path)
            return {}

        return data

    def _save_state(self) -> None:
        with self.state_path.open("w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2, sort_keys=True)

    def _is_basketball(self, market: dict[str, Any]) -> bool:
        sport = str(market.get("sport", "")).strip().lower()
        category = str(market.get("category", "")).strip().lower()
        tags = [str(tag).strip().lower() for tag in market.get("tags", []) or []]

        basketball_markers = {"basketball", "nba", "wnba", "ncaab", "ncaa basketball"}
        if sport in basketball_markers or category in basketball_markers:
            return True
        return any(marker in tags for marker in basketball_markers)

    def should_enter(
        self,
        *,
        game_id: str,
        market_id: str,
        current_prob: float,
        market: dict[str, Any],
        position_size: float,
    ) -> bool:
        """Return whether an entry should be made and log skip reasons."""
        game_state = self._state.get(game_id, {})

        if not self._is_basketball(market):
            logger.info(
                "Skipping game_id=%s market_id=%s: non-basketball market",
                game_id,
                market_id,
            )
            return False

        if game_state.get("has_bet", False):
            logger.info(
                "Skipping game_id=%s market_id=%s: already bet",
                game_id,
                market_id,
            )
            return False

        if not (self.entry_min_prob <= current_prob <= self.entry_max_prob):
            logger.info(
                (
                    "Skipping game_id=%s market_id=%s: probability %.4f outside "
                    "[%.4f, %.4f]"
                ),
                game_id,
                market_id,
                current_prob,
                self.entry_min_prob,
                self.entry_max_prob,
            )
            return False

        return True

    def record_entry(
        self,
        *,
        game_id: str,
        market_id: str,
        entry_prob: float,
        position_size: float,
    ) -> None:
        """Persist a successful buy entry for the game to prevent duplicates."""
        self._state[game_id] = {
            "has_bet": True,
            "entry_prob": entry_prob,
            "position_size": position_size,
            "market_id": market_id,
        }
        self._save_state()

    def should_exit(self, *, current_prob: float) -> bool:
        """Simple exit check against configured probability threshold."""
        return current_prob <= self.exit_prob
