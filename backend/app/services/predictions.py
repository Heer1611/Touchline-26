from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import exp
from typing import Iterable

from app.models import InternationalAppearance


@dataclass(frozen=True)
class PlayerProjection:
    appearances_used: int
    expected_minutes: float
    chance_to_score: float
    chance_to_assist: float
    expected_rating: float | None


def _time_weight(match_date: datetime, half_life_days: int = 365) -> float:
    """Older matches still count, but their influence fades smoothly over time."""
    now = datetime.now(UTC)
    if match_date.tzinfo is None:
        match_date = match_date.replace(tzinfo=UTC)
    days_old = max((now - match_date).days, 0)
    return exp(-0.69314718056 * days_old / half_life_days)


def _weighted_average(values: Iterable[tuple[float, float]]) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for value, weight in values:
        numerator += value * weight
        denominator += weight
    return numerator / denominator if denominator else None


MIN_COMPLETE_APPEARANCES = 2
MIN_COMPLETE_MINUTES = 90


def project_player_from_international_history(
    appearances: list[InternationalAppearance],
) -> PlayerProjection:
    """Create a conservative, explainable international-history baseline.

    A named squad spot or a player-linked goal/card event does *not* provide enough
    information to estimate minutes or a match rating. This function returns an
    unavailable projection until a player has at least two complete imported match
    records and 90 verified minutes. The interface then renders em dashes instead
    of misleading 0% / 0-minute forecasts.
    """
    if not appearances:
        return PlayerProjection(0, 0.0, 0.0, 0.0, None)

    # ESPN event-only rows verify goals/cards but do not establish a complete
    # player appearance. Do not let partial rows dilute or manufacture a forecast.
    complete_appearances = [
        item
        for item in appearances
        if getattr(item, "rating_kind", None) != "event_pulse" and int(getattr(item, "minutes", 0) or 0) > 0
    ]
    complete_minutes = sum(int(item.minutes or 0) for item in complete_appearances)
    if len(complete_appearances) < MIN_COMPLETE_APPEARANCES or complete_minutes < MIN_COMPLETE_MINUTES:
        return PlayerProjection(len(complete_appearances), 0.0, 0.0, 0.0, None)

    weighted_minutes = _weighted_average(
        (appearance.minutes, _time_weight(appearance.match_date)) for appearance in complete_appearances
    ) or 0.0
    weighted_goals_per_90 = _weighted_average(
        (
            (appearance.goals / max(appearance.minutes, 1)) * 90,
            _time_weight(appearance.match_date),
        )
        for appearance in complete_appearances
    ) or 0.0
    weighted_assists_per_90 = _weighted_average(
        (
            (appearance.assists / max(appearance.minutes, 1)) * 90,
            _time_weight(appearance.match_date),
        )
        for appearance in complete_appearances
    ) or 0.0
    expected_rating = _weighted_average(
        (appearance.rating, _time_weight(appearance.match_date))
        for appearance in complete_appearances
        if appearance.rating is not None
    )

    expected_goals = weighted_goals_per_90 * (weighted_minutes / 90)
    expected_assists = weighted_assists_per_90 * (weighted_minutes / 90)

    # Poisson probability of at least one event: 1 - e^-lambda.
    chance_to_score = min(1 - exp(-expected_goals), 0.95)
    chance_to_assist = min(1 - exp(-expected_assists), 0.90)

    return PlayerProjection(
        appearances_used=len(complete_appearances),
        expected_minutes=round(weighted_minutes, 1),
        chance_to_score=round(chance_to_score * 100, 1),
        chance_to_assist=round(chance_to_assist * 100, 1),
        expected_rating=round(expected_rating, 2) if expected_rating is not None else None,
    )
