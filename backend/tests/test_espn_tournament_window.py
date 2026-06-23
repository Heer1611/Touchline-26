from __future__ import annotations

from datetime import UTC, date, datetime

from app.config import Settings
from app.services.espn import EspnScoreboardClient, extract_2026_event_player_lines, merge_event_player_lines


def _event(event_id: str, when: str) -> dict:
    return {
        "id": event_id,
        "date": when,
        "competitions": [{
            "date": when,
            "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre"}},
            "competitors": [
                {"homeAway": "home", "team": {"id": "1", "displayName": "Alpha"}},
                {"homeAway": "away", "team": {"id": "2", "displayName": "Beta"}},
            ],
        }],
    }


def test_schedule_queries_each_calendar_date_and_deduplicates() -> None:
    client = EspnScoreboardClient(Settings())
    calls: list[str] = []

    async def fake_get(params: dict):
        calls.append(str(params["dates"]))
        if params["dates"] == "20260611":
            return {"events": [_event("a", "2026-06-11T15:00Z")]}
        if params["dates"] == "20260612":
            return {"events": [_event("a", "2026-06-11T15:00Z"), _event("b", "2026-06-12T15:00Z")]}
        return {"events": []}

    client._get = fake_get  # type: ignore[method-assign]
    import asyncio
    rows = asyncio.run(client.fetch_tournament_events(date(2026, 6, 11), date(2026, 6, 13)))
    assert calls == ["20260611", "20260612", "20260613"]
    assert {row["id"] for row in rows} == {"a", "b"}


def test_goal_and_named_assist_are_retained_from_summary() -> None:
    scoreboard = {
        "competitions": [{"details": [{
            "id": "goal-8",
            "scoringPlay": True,
            "type": {"text": "Goal"},
            "team": {"id": "1"},
            "athletesInvolved": [{"id": "10", "displayName": "Scorer"}],
        }]}]
    }
    summary = {
        "plays": [{
            "id": "goal-8",
            "scoringPlay": True,
            "type": {"text": "Goal"},
            "team": {"id": "1"},
            "athletesInvolved": [
                {"id": "10", "displayName": "Scorer", "role": "scorer"},
                {"id": "11", "displayName": "Provider", "role": "assist"},
            ],
        }]
    }
    lines = merge_event_player_lines(
        extract_2026_event_player_lines(scoreboard),
        extract_2026_event_player_lines(summary),
    )
    totals = {line.name: (line.goals, line.assists) for line in lines}
    assert totals["Scorer"] == (1, 0)
    assert totals["Provider"] == (0, 1)


def test_schedule_audit_keeps_successful_days_when_one_date_fails() -> None:
    client = EspnScoreboardClient(Settings())

    async def fake_get(params: dict):
        if params["dates"] == "20260612":
            raise RuntimeError("temporary provider error")
        return {"events": [_event(str(params["dates"]), f"2026-06-{str(params['dates'])[-2:]}T15:00Z")]}

    client._get = fake_get  # type: ignore[method-assign]
    import asyncio
    rows, audit = asyncio.run(client.fetch_tournament_events_with_audit(date(2026, 6, 11), date(2026, 6, 13)))
    assert {row["id"] for row in rows} == {"20260611", "20260613"}
    assert audit.days_attempted == 3
    assert audit.days_succeeded == 2
    assert audit.failed_days == ("2026-06-12",)
