from datetime import UTC, datetime

from app.models import InternationalAppearance
from app.repository import _complete_appearance_rows, _tournament_line


def _appearance(*, kind: str, goals: int = 0, minutes: int = 0) -> InternationalAppearance:
    return InternationalAppearance(
        player_id=1,
        match_id=1 if kind == "event_pulse" else 2,
        match_date=datetime(2026, 6, 18, tzinfo=UTC),
        opponent_name="Example opponent",
        rating_kind=kind,
        goals=goals,
        minutes=minutes,
    )


def test_event_only_rows_are_not_counted_as_complete_appearances():
    event_row = _appearance(kind="event_pulse", goals=2)
    full_row = _appearance(kind="live_pulse", goals=1, minutes=90)

    line = _tournament_line([event_row, full_row])

    assert line.event_linked_matches == 1
    assert line.full_stat_lines == 1
    assert line.appearances == 1
    assert line.games_played == 2
    assert line.minutes == 90
    assert line.goals == 3
    assert _complete_appearance_rows([event_row, full_row]) == [full_row]
