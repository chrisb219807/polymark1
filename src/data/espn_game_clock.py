"""ESPN game clock data access utilities."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

LOGGER = logging.getLogger(__name__)


class ESPNUnavailableError(RuntimeError):
    """Raised when the ESPN scoreboard endpoint is unavailable."""


@dataclass(frozen=True)
class GameClock:
    game_id: str
    clock_seconds_remaining: int
    period: int
    status: str


class ESPNGameClockClient:
    """Client to fetch and normalize basketball game clock data from ESPN."""

    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball"

    def __init__(self, league: str = "nba", timeout_seconds: float = 5.0):
        self.league = league
        self.timeout_seconds = timeout_seconds

    def fetch_scoreboard(self) -> dict[str, Any]:
        endpoint = f"{self.BASE_URL}/{self.league}/scoreboard"
        try:
            with urlopen(endpoint, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except (URLError, TimeoutError, OSError) as exc:
            raise ESPNUnavailableError("Unable to fetch ESPN scoreboard") from exc

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ESPNUnavailableError("Invalid ESPN scoreboard response") from exc

    def get_game_clock(self, game_id: str) -> GameClock:
        scoreboard = self.fetch_scoreboard()
        for event in scoreboard.get("events", []):
            if str(event.get("id")) == str(game_id):
                return self._normalize_event(event)

        raise ValueError(f"Game id {game_id} not found in ESPN scoreboard")

    def is_late_game(self, game_id: str, threshold_seconds: int = 480) -> bool:
        game_clock = self.get_game_clock(game_id)
        return (
            game_clock.status == "in-progress"
            and game_clock.clock_seconds_remaining < threshold_seconds
        )

    def _normalize_event(self, event: dict[str, Any]) -> GameClock:
        competition = (event.get("competitions") or [{}])[0]
        status_block = competition.get("status") or event.get("status") or {}
        status_type = status_block.get("type") or {}

        status = self._normalize_status(status_type)
        period = int(status_type.get("period") or 0)

        if status == "in-progress":
            display_clock = str(status_block.get("displayClock") or "0:00")
            clock_seconds_remaining = self._clock_to_seconds(display_clock)
        else:
            clock_seconds_remaining = 0

        return GameClock(
            game_id=str(event.get("id", "")),
            clock_seconds_remaining=clock_seconds_remaining,
            period=period,
            status=status,
        )

    @staticmethod
    def _normalize_status(status_type: dict[str, Any]) -> str:
        state = str(status_type.get("state", "")).lower()
        if state == "in":
            return "in-progress"
        if state == "post":
            return "final"
        if state == "pre":
            return "pre-game"

        name = str(status_type.get("name") or "unknown").lower()
        return name.replace("_", "-")

    @staticmethod
    def _clock_to_seconds(display_clock: str) -> int:
        parts = display_clock.strip().split(":")
        if len(parts) != 2:
            return 0

        minutes_raw, seconds_raw = parts
        try:
            minutes = int(minutes_raw)
            seconds = int(float(seconds_raw))
        except ValueError:
            LOGGER.debug("Unable to parse display clock: %s", display_clock)
            return 0

        return max((minutes * 60) + seconds, 0)


def is_late_game(
    game_id: str,
    threshold_seconds: int = 480,
    client: ESPNGameClockClient | None = None,
) -> bool:
    """Convenience helper for late-game checks."""
    clock_client = client or ESPNGameClockClient()
    return clock_client.is_late_game(game_id, threshold_seconds=threshold_seconds)
