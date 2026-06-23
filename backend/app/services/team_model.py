"""Explainable baseline team model for World Cup match predictions.

This is intentionally not marketed as a sportsbook model. It starts with transparent
team-strength seed values, then updates those values with imported free World Cup
player history and completed matches from the current tournament.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import InternationalAppearance, Match, Player, Team


FINISHED_STATUSES = {"FT", "AET", "PEN"}
LIVE_STATUSES = {"LIVE", "1H", "HT", "2H", "ET", "BT", "P", "INT", "SUSP"}


# These are internal starting points, not official FIFA rankings or betting odds.
# They simply stop a brand-new database from producing identical 33/33/33 cards
# before the free historical import has populated the app.
_SEED_RATINGS = {
    "argentina": 1870,
    "brazil": 1865,
    "spain": 1858,
    "france": 1855,
    "england": 1846,
    "portugal": 1832,
    "germany": 1828,
    "netherlands": 1818,
    "belgium": 1807,
    "italy": 1802,
    "uruguay": 1788,
    "colombia": 1782,
    "croatia": 1776,
    "morocco": 1768,
    "japan": 1762,
    "united states": 1760,
    "usa": 1760,
    "mexico": 1755,
    "switzerland": 1750,
    "senegal": 1748,
    "south korea": 1738,
    "korea republic": 1738,
    "iran": 1735,
    "ecuador": 1732,
    "austria": 1728,
    "norway": 1727,
    "turkey": 1724,
    "turkiye": 1724,
    "denmark": 1722,
    "serbia": 1718,
    "australia": 1714,
    "canada": 1708,
    "egypt": 1704,
    "paraguay": 1701,
    "algeria": 1699,
    "scotland": 1698,
    "ivory coast": 1695,
    "cote d ivoire": 1695,
    "ghana": 1692,
    "nigeria": 1690,
    "saudi arabia": 1688,
    "uzbekistan": 1685,
    "panama": 1678,
    "south africa": 1672,
    "qatar": 1668,
    "jordan": 1664,
    "iraq": 1660,
    "new zealand": 1655,
    "bosnia and herzegovina": 1650,
    "czechia": 1648,
    "haiti": 1605,
    "curacao": 1600,
    "cape verde": 1598,
    "democratic republic of the congo": 1595,
    "dr congo": 1595,
    "tunisia": 1590,
}


@dataclass(frozen=True)
class TeamPower:
    team_id: int
    seed_rating: float
    history_adjustment: float
    current_form_adjustment: float

    @property
    def rating(self) -> float:
        return self.seed_rating + self.history_adjustment + self.current_form_adjustment


def _team_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _seed_rating(name: str) -> float:
    return float(_SEED_RATINGS.get(_team_key(name), 1650))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def build_team_powers(session: Session) -> dict[int, TeamPower]:
    """Build a strength record for every stored national team.

    History only changes a team once the importer has at least five full-match
    equivalents of player minutes. That makes one small sample unable to dominate
    the prediction.
    """
    teams = session.scalars(select(Team)).all()

    history_rows = session.execute(
        select(
            Player.national_team_id,
            func.coalesce(func.sum(InternationalAppearance.minutes), 0),
            func.coalesce(func.sum(InternationalAppearance.goals), 0),
            func.coalesce(func.sum(InternationalAppearance.xg), 0.0),
        )
        .join(InternationalAppearance, InternationalAppearance.player_id == Player.id)
        .group_by(Player.national_team_id)
    ).all()
    history = {
        int(team_id): {
            "minutes": float(minutes or 0),
            "goals": float(goals or 0),
            "xg": float(xg or 0),
        }
        for team_id, minutes, goals, xg in history_rows
    }

    current_form: dict[int, float] = {}
    current_matches = session.scalars(
        select(Match).where(
            Match.provider_id.like("espn:%"),
            Match.status.in_(FINISHED_STATUSES),
            Match.home_score.is_not(None),
            Match.away_score.is_not(None),
        )
    ).all()
    for match in current_matches:
        goal_difference = int(match.home_score or 0) - int(match.away_score or 0)
        if goal_difference > 0:
            home_result, away_result = 10.0, -10.0
        elif goal_difference < 0:
            home_result, away_result = -10.0, 10.0
        else:
            home_result = away_result = 0.0
        current_form[match.home_team_id] = current_form.get(match.home_team_id, 0.0) + home_result + goal_difference * 4.0
        current_form[match.away_team_id] = current_form.get(match.away_team_id, 0.0) + away_result - goal_difference * 4.0

    powers: dict[int, TeamPower] = {}
    for team in teams:
        historical = history.get(team.id, {"minutes": 0.0, "goals": 0.0, "xg": 0.0})
        minutes = historical["minutes"]
        history_adjustment = 0.0
        if minutes >= 450:
            goals_per_90 = (historical["goals"] / minutes) * 90
            xg_per_90 = (historical["xg"] / minutes) * 90 if historical["xg"] else goals_per_90
            attack_signal = (goals_per_90 - 1.15) * 22 + (xg_per_90 - 1.10) * 17
            experience_signal = min(7.0, math.log1p(minutes / 90) * 1.45)
            history_adjustment = _clamp(attack_signal + experience_signal, -28.0, 28.0)

        powers[team.id] = TeamPower(
            team_id=team.id,
            seed_rating=_seed_rating(team.name),
            history_adjustment=round(history_adjustment, 1),
            current_form_adjustment=round(_clamp(current_form.get(team.id, 0.0), -36.0, 36.0), 1),
        )
    return powers


def predict_match(match: Match, powers: dict[int, TeamPower]) -> dict[str, float | str]:
    """Return home/draw/away probabilities that add to exactly 100.0."""
    home_power = powers.get(match.home_team_id)
    away_power = powers.get(match.away_team_id)
    home_rating = home_power.rating if home_power else 1650.0
    away_rating = away_power.rating if away_power else 1650.0

    rating_difference = home_rating - away_rating

    # A current score should matter during a live game. The effect grows as time runs
    # out, but it remains bounded so an early one-goal lead does not look final.
    if match.status in LIVE_STATUSES and match.home_score is not None and match.away_score is not None:
        minute = _clamp(float(match.minute or 1), 1.0, 120.0)
        score_difference = float(match.home_score - match.away_score)
        rating_difference += score_difference * (95.0 + minute * 1.45)

    draw_probability = _clamp(27.0 - min(abs(rating_difference), 420.0) * 0.014, 19.0, 28.0)
    home_share_without_draw = 1.0 / (1.0 + 10 ** (-rating_difference / 355.0))
    home_win = (100.0 - draw_probability) * home_share_without_draw
    draw = round(draw_probability, 1)
    home = round(home_win, 1)
    away = round(100.0 - home - draw, 1)

    stronger_name = match.home_team.name if rating_difference >= 0 else match.away_team.name
    gap = abs(round(home_rating - away_rating))
    summary = (
        f"{stronger_name} is favored by the baseline model ({gap} strength-point gap). "
        "Imported World Cup player history and completed tournament results adjust this estimate."
    )

    return {
        "home_win": home,
        "draw": draw,
        "away_win": away,
        "home_strength": round(home_rating, 1),
        "away_strength": round(away_rating, 1),
        "summary": summary,
    }
