from __future__ import annotations

"""Normalize the parts of ESPN's public match-summary JSON that are useful here.

The public ESPN feed is not a documented product API and its soccer payload changes
occasionally. This module is intentionally defensive: unavailable fields remain
empty instead of being guessed. It only returns player rows when a full box-score
player list is present.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass
class EspnPlayerLine:
    provider_id: str | None
    name: str
    team_provider_id: str | None
    position: str | None = None
    started: bool = False
    minutes: int = 0
    goals: int = 0
    assists: int = 0
    shots: int = 0
    xg: float | None = None
    passes_completed: int = 0
    passes_attempted: int = 0
    key_passes: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    clearances: int = 0
    saves: int = 0
    fields_seen: int = 0

    def merge(self, values: dict[str, Any], *, position: str | None = None, started: bool | None = None) -> None:
        if position and not self.position:
            self.position = position
        if started is not None:
            self.started = self.started or started
        for field_name, raw_value in values.items():
            if not hasattr(self, field_name):
                continue
            value = _as_number(raw_value)
            if value is None:
                continue
            if field_name == "xg":
                self.xg = value
            else:
                setattr(self, field_name, int(round(value)))
            self.fields_seen += 1


# ESPN label spellings vary between the scorecard, tournament, and locale. The
# aliases are normalized before matching, so "Pass Completed" and "passesCompleted"
# resolve to the same local field.
_FIELD_ALIASES: dict[str, set[str]] = {
    "minutes": {"min", "minutes", "mins", "minutesplayed", "mp"},
    "goals": {"goal", "goals", "g"},
    "assists": {"assist", "assists", "a"},
    "shots": {"shot", "shots", "totalshots", "sh"},
    "xg": {"xg", "expectedgoals", "expectedgoal"},
    "passes_completed": {
        "passescompleted",
        "passcompleted",
        "completedpasses",
        "accuratepasses",
        "passcomp",
    },
    "passes_attempted": {"passesattempted", "passattempted", "totalpasses", "passatt", "passes"},
    "key_passes": {"keypasses", "keypass", "chancescreated", "chancecreated"},
    "tackles_won": {"tackleswon", "tacklewon", "won tackles", "tackles"},
    "interceptions": {"interceptions", "interception", "int"},
    "clearances": {"clearances", "clearance", "clr"},
    "saves": {"saves", "save", "sv"},
}

_ALIAS_TO_FIELD = {alias.replace(" ", ""): field for field, aliases in _FIELD_ALIASES.items() for alias in aliases}


def extract_player_lines(
    payload: dict[str, Any],
    *,
    include_confirmed_starters: bool = False,
) -> list[EspnPlayerLine]:
    """Return per-player rows from ESPN's boxscore structure, if supplied.

    A no-data result means the summary did not include a player table. It does not
    mean a player did not play.
    """
    boxscore = payload.get("boxscore") or {}
    groups = boxscore.get("players") or payload.get("players") or []
    if not isinstance(groups, list):
        return []

    by_key: dict[tuple[str | None, str | None, str], EspnPlayerLine] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        team_provider_id = _team_provider_id(group)
        statistics = group.get("statistics") or []
        if isinstance(statistics, dict):
            statistics = [statistics]

        for section in statistics:
            if not isinstance(section, dict):
                continue
            labels = section.get("names") or section.get("labels") or []
            if not isinstance(labels, list):
                labels = []
            athletes = section.get("athletes") or section.get("players") or []
            if not isinstance(athletes, list):
                continue

            for entry in athletes:
                if not isinstance(entry, dict):
                    continue
                athlete = entry.get("athlete") or entry.get("player") or entry
                if not isinstance(athlete, dict):
                    continue
                name = athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName")
                if not name:
                    continue
                athlete_id = athlete.get("id")
                provider_id = f"espn:athlete:{athlete_id}" if athlete_id is not None else None
                actual_team_id = team_provider_id or _team_provider_id(entry)
                key = (provider_id, actual_team_id, str(name).casefold())
                line = by_key.setdefault(
                    key,
                    EspnPlayerLine(
                        provider_id=provider_id,
                        name=str(name),
                        team_provider_id=actual_team_id,
                        position=_position_name(entry, athlete),
                        started=_started(entry),
                    ),
                )
                values = _stat_values(labels, entry)
                line.merge(values, position=_position_name(entry, athlete), started=_started(entry))

    # A summary can include leader cards but not a full team table. Require at least
    # one box-score metric before showing a player as an actual 2026 line.
    return [
        line
        for line in by_key.values()
        if line.fields_seen > 0
        or (include_confirmed_starters and line.started)
    ]


def pulse_rating_from_available_stats(line: EspnPlayerLine) -> float | None:
    """A transparent local 0–10 rating for current ESPN box-score rows.

    This is deliberately less detailed than the StatsBomb-event rating. ESPN may
    omit fields, so the score is only a live estimate and never an official rating.
    """
    if line.fields_seen == 0:
        return None

    rating = 5.7
    if line.minutes:
        rating += min(line.minutes, 100) * 0.006
    rating += line.goals * 1.55 + line.assists * 0.85
    rating += line.shots * 0.07 + (line.xg or 0.0) * 0.6
    rating += line.key_passes * 0.12
    rating += line.tackles_won * 0.10 + line.interceptions * 0.09 + line.clearances * 0.05 + line.saves * 0.10
    if line.passes_attempted:
        rating += (line.passes_completed / max(1, line.passes_attempted)) * 0.32
    return round(max(0.0, min(10.0, rating)), 1)


def _team_provider_id(value: dict[str, Any]) -> str | None:
    team = value.get("team") or value.get("competitor") or {}
    if not isinstance(team, dict):
        return None
    team_id = team.get("id")
    return f"espn:team:{team_id}" if team_id is not None else None


def _position_name(entry: dict[str, Any], athlete: dict[str, Any]) -> str | None:
    position = entry.get("position") or athlete.get("position") or {}
    if isinstance(position, dict):
        return position.get("displayName") or position.get("abbreviation") or position.get("name")
    if isinstance(position, str):
        return position
    return None


def _started(entry: dict[str, Any]) -> bool:
    value = entry.get("starter")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "starter", "yes"}
    return False


def _stat_values(labels: list[Any], entry: dict[str, Any]) -> dict[str, Any]:
    raw_stats = entry.get("stats") or entry.get("statistics") or []
    result: dict[str, Any] = {}

    if isinstance(raw_stats, dict):
        items: Iterable[tuple[Any, Any]] = raw_stats.items()
    elif isinstance(raw_stats, list):
        items = zip(labels, raw_stats)
    else:
        return result

    for raw_label, raw_value in items:
        field_name = _field_for_label(str(raw_label))
        if field_name:
            result[field_name] = raw_value
    return result


def _field_for_label(label: str) -> str | None:
    key = "".join(character for character in label.casefold() if character.isalnum())
    return _ALIAS_TO_FIELD.get(key)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("%", "")
        # Some soccer feeds use "24/31" for a paired stat. The columns we care
        # about are usually separate, but treating the first number as a fallback
        # is better than failing the entire player row.
        if "/" in cleaned:
            cleaned = cleaned.split("/", 1)[0]
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None
