from src.data.espn_game_clock import ESPNGameClockClient, GameClock


def test_normalize_in_progress_clock():
    client = ESPNGameClockClient()
    event = {
        "id": "401547689",
        "competitions": [
            {
                "status": {
                    "type": {"state": "in", "period": 4},
                    "displayClock": "2:35",
                }
            }
        ],
    }

    game_clock = client._normalize_event(event)

    assert game_clock == GameClock(
        game_id="401547689",
        clock_seconds_remaining=155,
        period=4,
        status="in-progress",
    )


def test_is_late_game_requires_in_progress_and_threshold():
    class StubClient(ESPNGameClockClient):
        def get_game_clock(self, game_id: str):
            return GameClock(
                game_id=game_id,
                clock_seconds_remaining=300,
                period=4,
                status="in-progress",
            )

    assert StubClient().is_late_game("game")


def test_is_not_late_when_final():
    class StubClient(ESPNGameClockClient):
        def get_game_clock(self, game_id: str):
            return GameClock(
                game_id=game_id,
                clock_seconds_remaining=10,
                period=4,
                status="final",
            )

    assert not StubClient().is_late_game("game")
