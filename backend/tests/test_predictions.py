from datetime import UTC, datetime, timedelta

from app.services.predictions import project_player_from_international_history


class Appearance:
    def __init__(self, days_ago: int, minutes: int, goals: int, assists: int, rating: float) -> None:
        self.match_date = datetime.now(UTC) - timedelta(days=days_ago)
        self.minutes = minutes
        self.goals = goals
        self.assists = assists
        self.rating = rating


def test_projection_uses_all_appearances() -> None:
    appearances = [
        Appearance(days_ago=30, minutes=90, goals=1, assists=0, rating=8.0),
        Appearance(days_ago=900, minutes=90, goals=0, assists=1, rating=7.0),
    ]

    projection = project_player_from_international_history(appearances)  # type: ignore[arg-type]

    assert projection.appearances_used == 2
    assert projection.chance_to_score > 0
    assert projection.expected_rating is not None


def test_projection_hides_zero_forecast_for_partial_or_sparse_records() -> None:
    partial = Appearance(days_ago=1, minutes=0, goals=2, assists=0, rating=9.0)
    partial.rating_kind = "event_pulse"
    projection = project_player_from_international_history([partial])  # type: ignore[arg-type]

    assert projection.appearances_used == 0
    assert projection.expected_minutes == 0
    assert projection.chance_to_score == 0
    assert projection.expected_rating is None
