from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Protocol


class PolymarketClient(Protocol):
    def get_implied_probability(self, market_id: str, outcome_id: str) -> float:
        ...


class OrderExecutor(Protocol):
    def place_sell_order(self, market_id: str, outcome_id: str, size: float) -> str:
        ...


@dataclass
class PositionState:
    market_id: str
    outcome_id: str
    entry_order_id: Optional[str] = None
    entry_timestamp: Optional[datetime] = None
    entry_prob: Optional[float] = None
    size: float = 0.0
    status: str = "pending_entry"
    exit_order_id: Optional[str] = None
    exit_timestamp: Optional[datetime] = None
    exit_prob: Optional[float] = None
    sell_attempt_pending_until: Optional[datetime] = None

    @property
    def has_open_position(self) -> bool:
        return self.status == "open" and self.size > 0


@dataclass
class HighConfidenceLateGameStrategy:
    polymarket_client: PolymarketClient
    order_executor: OrderExecutor
    tracked_games: Dict[str, PositionState] = field(default_factory=dict)
    stop_loss_prob: float = 0.33
    sell_cooldown_seconds: int = 60
    partial_exit_size: Optional[float] = None

    def monitor_positions(self, now: Optional[datetime] = None) -> None:
        """Monitor tracked games and trigger exits for open positions below stop-loss probability."""
        now = now or datetime.now(timezone.utc)

        for game_id, position in self.tracked_games.items():
            # Rule only applies after successful entry and while a position is open.
            if not position.has_open_position:
                continue

            # Debounce repeated sell attempts while an order is still considered pending.
            if position.sell_attempt_pending_until and now < position.sell_attempt_pending_until:
                continue

            current_prob = self.polymarket_client.get_implied_probability(
                position.market_id,
                position.outcome_id,
            )

            if current_prob < self.stop_loss_prob:
                sell_size = self._resolve_sell_size(position.size)
                order_id = self.order_executor.place_sell_order(
                    position.market_id,
                    position.outcome_id,
                    sell_size,
                )

                # Persist exit metadata.
                position.exit_prob = current_prob
                position.exit_timestamp = now
                position.exit_order_id = order_id
                position.status = "closed"
                position.size = max(0.0, position.size - sell_size)
                position.sell_attempt_pending_until = now + timedelta(seconds=self.sell_cooldown_seconds)

    def _resolve_sell_size(self, held_size: float) -> float:
        if self.partial_exit_size is None:
            return held_size
        return min(held_size, self.partial_exit_size)
