from __future__ import annotations

from datetime import UTC, datetime, timedelta

_DEMO_KICKOFF = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=58)


def demo_fixtures() -> list[dict]:
    """Sample content for local development only.

    The UI labels demo mode. These are not intended to represent real fixtures or scores.
    """

    now = datetime.now(UTC).replace(second=0, microsecond=0)
    elapsed = min(max(int((now - _DEMO_KICKOFF).total_seconds() // 60), 0), 90)
    return [
        {
            "provider_id": "demo-arg-fra",
            "kickoff_at": _DEMO_KICKOFF,
            "status": "LIVE" if elapsed < 90 else "FT",
            "minute": elapsed,
            "home_score": 1,
            "away_score": 1,
            "stage": "Demo · Group Stage",
            "venue": "Example Stadium",
            "home_team": {"provider_id": "demo-arg", "name": "Argentina", "code": "ARG", "logo_url": None},
            "away_team": {"provider_id": "demo-fra", "name": "France", "code": "FRA", "logo_url": None},
        },
        {
            "provider_id": "demo-bra-eng",
            "kickoff_at": _DEMO_KICKOFF + timedelta(hours=4),
            "status": "SCHEDULED",
            "minute": None,
            "home_score": None,
            "away_score": None,
            "stage": "Demo · Group Stage",
            "venue": "Sample Park",
            "home_team": {"provider_id": "demo-bra", "name": "Brazil", "code": "BRA", "logo_url": None},
            "away_team": {"provider_id": "demo-eng", "name": "England", "code": "ENG", "logo_url": None},
        },
        {
            "provider_id": "demo-jpn-mar",
            "kickoff_at": _DEMO_KICKOFF - timedelta(days=1, hours=2),
            "status": "FT",
            "minute": 90,
            "home_score": 2,
            "away_score": 0,
            "stage": "Demo · Group Stage",
            "venue": "Test Field",
            "home_team": {"provider_id": "demo-jpn", "name": "Japan", "code": "JPN", "logo_url": None},
            "away_team": {"provider_id": "demo-mar", "name": "Morocco", "code": "MAR", "logo_url": None},
        },
    ]
