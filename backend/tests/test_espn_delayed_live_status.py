from __future__ import annotations

from app.config import Settings
from app.services.espn import EspnScoreboardClient


def _delayed_event() -> dict:
    return {
        "id": "760457",
        "date": "2026-06-22T21:00Z",
        "competitions": [{
            "date": "2026-06-22T21:00Z",
            "status": {
                "displayClock": "45'+3'",
                "type": {
                    "name": "STATUS_DELAYED",
                    "state": "in",
                    "completed": False,
                    "description": "Delayed",
                    "detail": "45'+3'",
                },
            },
            "competitors": [
                {"homeAway": "home", "score": "1", "team": {"id": "478", "displayName": "France", "abbreviation": "FRA"}},
                {"homeAway": "away", "score": "0", "team": {"id": "4375", "displayName": "Iraq", "abbreviation": "IRQ"}},
            ],
        }],
    }


def test_in_progress_delayed_match_stays_live_with_score_and_clock() -> None:
    client = EspnScoreboardClient(Settings())
    row = client.normalize_event(_delayed_event())

    assert row["status"] == "SUSP"
    assert row["minute"] == 45
    assert row["home_score"] == 1
    assert row["away_score"] == 0
