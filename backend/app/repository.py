from __future__ import annotations

from collections import defaultdict
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import InternationalAppearance, Match, Player, Team
from app.schemas import (
    MatchDetailOut,
    MatchOut,
    MatchPlayerStatOut,
    PlayerAppearanceOut,
    PlayerDetailOut,
    PlayerProjectionOut,
    PlayerSummaryOut,
    TeamOut,
    TournamentLineOut,
)
from app.services.espn import EspnEventPlayerLine, EspnRosterPlayer, event_pulse_rating
from app.services.espn_match_summary import EspnPlayerLine, pulse_rating_from_available_stats
from app.services.predictions import project_player_from_international_history
from app.services.team_model import LIVE_STATUSES, build_team_powers, predict_match


DASHBOARD_SCHEDULED_STATUSES = {"NS", "TBD", "PST", "SCHEDULED"}


def serialize_match(match: Match, powers: dict[int, Any]) -> MatchOut:
    return MatchOut(
        provider_id=match.provider_id,
        kickoff_at=match.kickoff_at,
        status=match.status,
        minute=match.minute,
        home_score=match.home_score,
        away_score=match.away_score,
        stage=match.stage,
        venue=match.venue,
        home_team=TeamOut.model_validate(match.home_team),
        away_team=TeamOut.model_validate(match.away_team),
        prediction=predict_match(match, powers),
    )


def _dashboard_sort_key(match: Match) -> tuple[int, float]:
    timestamp = match.kickoff_at.timestamp()
    if match.status in LIVE_STATUSES:
        return (0, timestamp)
    if match.status in DASHBOARD_SCHEDULED_STATUSES:
        return (1, timestamp)
    return (2, -timestamp)


def list_matches(session: Session, *, include_history: bool = False) -> list[MatchOut]:
    """Return current cards or the full stored archive.

    The archive includes StatsBomb 2018/2022 matches after the user imports them.
    The regular dashboard stays focused on live, upcoming, and recent matches.
    """
    statement = select(Match).options(selectinload(Match.home_team), selectinload(Match.away_team))
    if not include_history:
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        statement = statement.where(Match.kickoff_at >= cutoff)

    matches = session.scalars(statement).all()
    if include_history:
        matches.sort(key=lambda match: match.kickoff_at, reverse=True)
    else:
        matches.sort(key=_dashboard_sort_key)
    powers = build_team_powers(session)
    return [serialize_match(match, powers) for match in matches]


def _match_entity(session: Session, provider_id: str) -> Match | None:
    return session.scalar(
        select(Match)
        .where(Match.provider_id == provider_id)
        .options(selectinload(Match.home_team), selectinload(Match.away_team))
    )


def get_match(session: Session, provider_id: str) -> MatchOut | None:
    match = _match_entity(session, provider_id)
    return serialize_match(match, build_team_powers(session)) if match else None


def _match_player_out(
    appearance: InternationalAppearance,
    *,
    data_status: str = "historical",
    rating_label: str | None = None,
) -> MatchPlayerStatOut:
    label = rating_label
    if label is None:
        if appearance.rating_kind == "live_pulse":
            label = "Live Pulse Rating"
        elif appearance.rating_kind == "event_pulse":
            label = "Event Pulse (limited — verified goals, assists, and cards)"
        else:
            label = "Pulse Rating"
    return MatchPlayerStatOut(
        player_id=appearance.player.id,
        player_name=appearance.player.name,
        position=appearance.player.position,
        started=appearance.started,
        minutes=appearance.minutes,
        goals=appearance.goals,
        assists=appearance.assists,
        shots=appearance.shots,
        xg=appearance.xg,
        passes_completed=appearance.passes_completed,
        passes_attempted=appearance.passes_attempted,
        key_passes=appearance.key_passes,
        tackles_won=appearance.tackles_won,
        interceptions=appearance.interceptions,
        clearances=appearance.clearances,
        saves=appearance.saves,
        yellow_cards=appearance.yellow_cards,
        red_cards=appearance.red_cards,
        pulse_rating=appearance.rating,
        data_status=data_status,
        rating_label=label,
    )


def _has_usable_projection(projection: Any) -> bool:
    """Require enough complete history before displaying a forecast as data-backed."""
    return bool(
        projection.appearances_used >= 2
        and projection.expected_minutes >= 30
        and projection.expected_rating is not None
    )


def _complete_appearance_rows(appearances: list[InternationalAppearance]) -> list[InternationalAppearance]:
    """Return only full match records suitable for totals and predictions.

    ESPN event rows verify a goal/card, but do not tell us minutes, shots, or whether
    the player completed a match. They must never be counted as appearances or be
    used to inflate a forecast.
    """
    return [appearance for appearance in appearances if appearance.rating_kind != "event_pulse"]


def _projected_player_out(player: Player, appearances: list[InternationalAppearance]) -> MatchPlayerStatOut:
    projection = project_player_from_international_history(_complete_appearance_rows(appearances))
    usable = _has_usable_projection(projection)
    return MatchPlayerStatOut(
        player_id=player.id,
        player_name=player.name,
        position=player.position,
        started=False,
        minutes=0,
        goals=0,
        assists=0,
        shots=0,
        xg=None,
        passes_completed=0,
        passes_attempted=0,
        key_passes=0,
        tackles_won=0,
        interceptions=0,
        clearances=0,
        saves=0,
        yellow_cards=0,
        red_cards=0,
        pulse_rating=projection.expected_rating if usable else None,
        data_status="predicted" if usable else "squad",
        rating_label="Expected Pulse Rating" if usable else "Projection unavailable — no linked history",
        expected_minutes=projection.expected_minutes if usable else None,
        chance_to_score=projection.chance_to_score if usable else None,
        chance_to_assist=projection.chance_to_assist if usable else None,
    )


def _team_projection_rows(
    session: Session,
    *,
    team_id: int,
    limit: int = 30,
) -> list[MatchPlayerStatOut]:
    """Build a pre-match view from the saved 2026 squad plus any history.

    Roster-only players are intentionally kept in this list. They have blank/zero
    projections until historical data is imported; that is more honest than hiding
    most of a country's actual tournament squad.
    """
    players = session.scalars(
        select(Player).where(Player.national_team_id == team_id).options(selectinload(Player.national_team))
    ).all()
    if not players:
        return []

    player_ids = [player.id for player in players]
    all_appearances = session.scalars(
        select(InternationalAppearance)
        .where(InternationalAppearance.player_id.in_(player_ids))
        .order_by(InternationalAppearance.match_date.desc())
    ).all()
    by_player: dict[int, list[InternationalAppearance]] = defaultdict(list)
    for appearance in all_appearances:
        by_player[appearance.player_id].append(appearance)

    rows = [_projected_player_out(player, by_player.get(player.id, [])) for player in players]
    rows.sort(
        key=lambda item: (
            item.pulse_rating or 0.0,
            item.chance_to_score or 0.0,
            item.chance_to_assist or 0.0,
            item.expected_minutes or 0.0,
            item.player_name.casefold(),
        ),
        reverse=True,
    )
    return rows[:limit]


def _squad_player_out(player: Player, appearances: list[InternationalAppearance]) -> MatchPlayerStatOut:
    """Represent a named 2026 squad member without claiming they played."""
    projection = project_player_from_international_history(appearances)
    usable = _has_usable_projection(projection)
    return MatchPlayerStatOut(
        player_id=player.id,
        player_name=player.name,
        position=player.position,
        started=False,
        minutes=0,
        goals=0,
        assists=0,
        shots=0,
        xg=None,
        passes_completed=0,
        passes_attempted=0,
        key_passes=0,
        tackles_won=0,
        interceptions=0,
        clearances=0,
        saves=0,
        yellow_cards=0,
        red_cards=0,
        pulse_rating=projection.expected_rating if usable else None,
        data_status="squad",
        rating_label="2026 squad profile" if not usable else "Expected Pulse Rating",
        expected_minutes=projection.expected_minutes if usable else None,
        chance_to_score=projection.chance_to_score if usable else None,
        chance_to_assist=projection.chance_to_assist if usable else None,
    )


def _merge_event_rows_with_roster(
    session: Session,
    *,
    team_id: int,
    actual_rows: list[MatchPlayerStatOut],
) -> list[MatchPlayerStatOut]:
    """Show every synced squad member beside verified event rows.

    A goal/card event provides only one or two people. The roster makes it clear
    who is available without turning unknown minutes or shots into fake zeros.
    """
    players = session.scalars(select(Player).where(Player.national_team_id == team_id)).all()
    if not players:
        return actual_rows
    player_ids = [player.id for player in players]
    appearances = session.scalars(
        select(InternationalAppearance).where(InternationalAppearance.player_id.in_(player_ids))
    ).all()
    by_player: dict[int, list[InternationalAppearance]] = defaultdict(list)
    for appearance in appearances:
        by_player[appearance.player_id].append(appearance)

    by_id = {row.player_id: row for row in actual_rows}
    merged = list(actual_rows)
    for player in players:
        if player.id not in by_id:
            merged.append(_squad_player_out(player, by_player.get(player.id, [])))
    return merged


def get_match_detail(
    session: Session,
    provider_id: str,
    *,
    live_events: list[dict[str, Any]] | None = None,
    team_stats: list[dict[str, Any]] | None = None,
    refreshed_at: datetime | None = None,
) -> MatchDetailOut | None:
    """Return actual data when it has been imported, otherwise honest projections.

    For a 2026 ESPN fixture, the router first asks ESPN's match-summary endpoint for
    a player box score. When a box score is published it is stored locally and this
    function returns those actual rows. Before lineups/stats exist, it returns a
    clearly labeled projection based on the player's imported World Cup history.
    """
    match = _match_entity(session, provider_id)
    if not match:
        return None

    actual_appearances = session.scalars(
        select(InternationalAppearance)
        .join(Player)
        .where(InternationalAppearance.match_id == match.id)
        .options(selectinload(InternationalAppearance.player))
    ).all()
    home: list[MatchPlayerStatOut] = []
    away: list[MatchPlayerStatOut] = []
    for appearance in actual_appearances:
        if appearance.player.national_team_id == match.home_team_id:
            status = "event" if appearance.rating_kind == "event_pulse" else ("current" if match.provider_id.startswith("espn:") else "historical")
            home.append(_match_player_out(appearance, data_status=status))
        elif appearance.player.national_team_id == match.away_team_id:
            status = "event" if appearance.rating_kind == "event_pulse" else ("current" if match.provider_id.startswith("espn:") else "historical")
            away.append(_match_player_out(appearance, data_status=status))

    has_full_box_score = any(appearance.rating_kind == "live_pulse" for appearance in actual_appearances)
    has_event_rows = any(appearance.rating_kind == "event_pulse" for appearance in actual_appearances)
    if match.provider_id.startswith("espn:") and has_event_rows and not has_full_box_score:
        home = _merge_event_rows_with_roster(session, team_id=match.home_team_id, actual_rows=home)
        away = _merge_event_rows_with_roster(session, team_id=match.away_team_id, actual_rows=away)

    actual_available = bool(home or away)
    projected_available = False
    roster_available = False
    notice: str | None = None

    if match.provider_id.startswith("espn:") and not actual_available:
        home = _team_projection_rows(session, team_id=match.home_team_id)
        away = _team_projection_rows(session, team_id=match.away_team_id)
        roster_available = bool(home or away)
        projected_available = any(item.data_status == "predicted" for item in [*home, *away])
        if projected_available:
            notice = (
                "ESPN has not published a full player box score for this 2026 match yet. "
                "Only players with enough linked 2018/2022 World Cup history show a data-backed projection. "
                "Other named squad members are shown without made-up zero values."
            )
        elif roster_available:
            notice = (
                "ESPN has not published a full player box score for this 2026 match yet. "
                "The squad is available, but no player has enough linked historical match data for a responsible projection."
            )
        else:
            notice = (
                "Individual 2026 player statistics have not been published for this match yet. "
                "Load the 2026 squads and the free 2018 + 2022 archive to build the pre-match view."
            )

    sort_key = lambda item: (
        item.pulse_rating or 0.0,
        item.goals,
        item.assists,
        item.minutes,
    )
    home.sort(key=sort_key, reverse=True)
    away.sort(key=sort_key, reverse=True)

    if match.provider_id.startswith("espn:") and has_full_box_score:
        stats_source = "ESPN public match summary"
        rating_label = "Live Pulse Rating (0–10, locally calculated from published box-score fields)"
    elif match.provider_id.startswith("espn:") and has_event_rows:
        stats_source = "ESPN live event feed"
        rating_label = "Event Pulse (0–10, limited local estimate from verified goals, assists, and cards)"
        notice = (
            "These are verified 2026 player event stats from ESPN: goals, assists when listed, and yellow/red cards. "
            "Touchline shows an Event Pulse only for players with a named event; it is not an official rating and does not use "
            "minutes, shots, xG, passing, or defensive actions until ESPN publishes a complete box score."
        )
    elif match.provider_id.startswith("espn:") and projected_available:
        stats_source = "StatsBomb Open Data player history"
        rating_label = "Expected Pulse Rating (0–10, project prediction)"
    elif match.provider_id.startswith("espn:") and roster_available:
        stats_source = "2026 named squad profiles"
        rating_label = "Projection unavailable until history is linked"
    elif actual_available:
        stats_source = "StatsBomb Open Data"
        rating_label = "Pulse Rating (0–10, calculated from imported match events)"
    else:
        stats_source = "No player data available"
        rating_label = "Pulse Rating"

    return MatchDetailOut(
        match=serialize_match(match, build_team_powers(session)),
        player_stats_available=actual_available or roster_available,
        actual_player_stats_available=actual_available,
        projected_players_available=projected_available,
        stats_source=stats_source,
        rating_label=rating_label,
        notice=notice,
        home_players=home,
        away_players=away,
        live_events=live_events or [],
        team_stats=team_stats or [],
        live_event_data_available=bool((live_events or []) or (team_stats or [])),
        refreshed_at=refreshed_at,
    )


def _appearance_cache_for_match(session: Session, match_id: int) -> dict[int, InternationalAppearance]:
    """Return one mutable appearance row per player for a single match.

    The ESPN scoreboard and match-summary feeds can describe the same athlete more
    than once.  Keeping a session-local cache means repeated event variants update
    one row instead of queuing duplicate INSERTs that violate the player/match
    unique constraint.
    """
    rows = session.scalars(
        select(InternationalAppearance).where(InternationalAppearance.match_id == match_id)
    ).all()
    return {row.player_id: row for row in rows}


def _team_for_existing_player(match: Match, incoming_team: Team, player: Player) -> Team:
    """Prefer an already-known national team if ESPN sends conflicting side IDs.

    A provider athlete ID belongs to one national team in this tournament.  Some
    public ESPN payload variants occasionally attach a duplicate person object to
    the opposite event side.  We never move a player across teams based on that
    duplicate; we retain the roster/team identity already stored locally.
    """
    if player.national_team_id == match.home_team_id:
        return match.home_team
    if player.national_team_id == match.away_team_id:
        return match.away_team
    return incoming_team


def upsert_espn_match_appearances(
    session: Session,
    provider_id: str,
    player_lines: list[EspnPlayerLine],
) -> int:
    """Persist actual 2026 box-score rows so player profiles include this year.

    This function is intentionally idempotent: syncing the same ESPN match twice
    updates the existing player/match row rather than inserting another one.
    """
    match = _match_entity(session, provider_id)
    if not match:
        return 0

    teams_by_provider = {
        match.home_team.provider_id: match.home_team,
        match.away_team.provider_id: match.away_team,
    }
    appearance_cache = _appearance_cache_for_match(session, match.id)
    imported = 0
    for line in player_lines:
        incoming_team = teams_by_provider.get(line.team_provider_id)
        if not incoming_team:
            # ESPN sometimes leaves the team ID off a player group. Do not guess.
            continue
        player = _find_or_create_player(
            session,
            {
                "provider_id": line.provider_id,
                "name": line.name,
                "position": line.position,
            },
            incoming_team,
        )
        national_team = _team_for_existing_player(match, incoming_team, player)
        opponent = match.away_team if national_team.id == match.home_team_id else match.home_team
        appearance = appearance_cache.get(player.id)
        if not appearance:
            appearance = InternationalAppearance(
                player_id=player.id,
                match_id=match.id,
                match_date=match.kickoff_at,
                opponent_name=opponent.name,
            )
            session.add(appearance)
            appearance_cache[player.id] = appearance

        appearance.match_date = match.kickoff_at
        appearance.opponent_name = opponent.name
        appearance.competition = "2026 FIFA World Cup"
        appearance.started = line.started
        appearance.minutes = line.minutes
        # Keep any independently verified event fields if the public box-score table
        # is incomplete or lags behind the match report.
        appearance.goals = max(appearance.goals or 0, line.goals)
        appearance.assists = max(appearance.assists or 0, line.assists)
        appearance.shots = line.shots
        appearance.xg = line.xg
        appearance.xa = None
        appearance.passes_completed = line.passes_completed
        appearance.passes_attempted = line.passes_attempted
        appearance.key_passes = line.key_passes
        appearance.tackles_won = line.tackles_won
        appearance.interceptions = line.interceptions
        appearance.clearances = line.clearances
        appearance.saves = line.saves
        # Card events can arrive before the fuller player box score. Preserve them.
        appearance.yellow_cards = appearance.yellow_cards or 0
        appearance.red_cards = appearance.red_cards or 0
        appearance.rating = pulse_rating_from_available_stats(line)
        appearance.data_source = "ESPN public match summary"
        appearance.rating_kind = "live_pulse"
        imported += 1

    session.commit()
    return imported


def upsert_espn_event_appearances(
    session: Session,
    provider_id: str,
    player_lines: list[EspnEventPlayerLine],
) -> int:
    """Persist verified 2026 player-linked goal/assist/card events safely.

    ESPN can repeat the same athlete in the scoreboard and summary payloads.  It
    can also attach conflicting side metadata to one repeated athlete object.  A
    player is therefore resolved once per local match, then all duplicate event
    fragments update one existing ``player_id + match_id`` row.  This is
    deliberately conservative: a duplicate never creates a second appearance or
    turns an ambiguous feed fragment into a new player record.
    """
    match = _match_entity(session, provider_id)
    if not match:
        return 0

    teams_by_provider = {
        match.home_team.provider_id: match.home_team,
        match.away_team.provider_id: match.away_team,
    }
    appearance_cache = _appearance_cache_for_match(session, match.id)

    # Resolve incoming feed fragments to real local players first.  Aggregating by
    # local player ID is the final safety net even if ESPN repeats an athlete under
    # two payload shapes or inconsistent team metadata.
    resolved: dict[int, tuple[Player, Team, EspnEventPlayerLine]] = {}
    for line in player_lines:
        incoming_team = teams_by_provider.get(line.team_provider_id)
        if not incoming_team:
            continue
        player = _find_or_create_player(
            session,
            {"provider_id": line.provider_id, "name": line.name, "position": line.position},
            incoming_team,
        )
        national_team = _team_for_existing_player(match, incoming_team, player)
        current = resolved.get(player.id)
        if current is None:
            resolved[player.id] = (player, national_team, line)
            continue

        existing_player, existing_team, existing_line = current
        # Keep the existing team when ESPN's duplicate fragment points to the
        # opposite side.  A player cannot play for both teams in one fixture.
        chosen_team = existing_team
        if player.national_team_id in {match.home_team_id, match.away_team_id}:
            chosen_team = match.home_team if player.national_team_id == match.home_team_id else match.away_team

        # Event parsers return totals per payload, so max() avoids double-counting
        # the same goal/card when it appears in both ESPN feeds.
        existing_line.goals = max(existing_line.goals, line.goals)
        existing_line.assists = max(existing_line.assists, line.assists)
        existing_line.yellow_cards = max(existing_line.yellow_cards, line.yellow_cards)
        existing_line.red_cards = max(existing_line.red_cards, line.red_cards)
        existing_line.fields_seen = max(existing_line.fields_seen, line.fields_seen)
        existing_line.last_event_minute = max(
            existing_line.last_event_minute or 0, line.last_event_minute or 0
        ) or None
        existing_line.position = existing_line.position or line.position
        existing_line.source_label = existing_line.source_label or line.source_label
        resolved[player.id] = (existing_player, chosen_team, existing_line)

    imported = 0
    for player_id, (player, national_team, line) in resolved.items():
        opponent = match.away_team if national_team.id == match.home_team_id else match.home_team
        appearance = appearance_cache.get(player_id)
        if appearance is None:
            # Re-check the database as well as the session-local cache.  This
            # makes repeated sync attempts idempotent even after partial writes.
            appearance = session.scalar(
                select(InternationalAppearance).where(
                    InternationalAppearance.player_id == player_id,
                    InternationalAppearance.match_id == match.id,
                )
            )
        if appearance is None:
            appearance = InternationalAppearance(
                player_id=player_id,
                match_id=match.id,
                match_date=match.kickoff_at,
                opponent_name=opponent.name,
            )
            session.add(appearance)
        appearance_cache[player_id] = appearance

        before = (
            appearance.goals or 0,
            appearance.assists or 0,
            appearance.yellow_cards or 0,
            appearance.red_cards or 0,
            appearance.data_source,
            appearance.rating_kind,
        )
        appearance.match_date = match.kickoff_at
        appearance.opponent_name = opponent.name
        appearance.competition = "2026 FIFA World Cup"
        appearance.goals = max(appearance.goals or 0, line.goals)
        appearance.assists = max(appearance.assists or 0, line.assists)
        appearance.yellow_cards = max(appearance.yellow_cards or 0, line.yellow_cards)
        appearance.red_cards = max(appearance.red_cards or 0, line.red_cards)
        if appearance.rating_kind != "live_pulse":
            # Event Pulse intentionally uses only verified goals, assists, and cards.
            # It is kept separate from a full box-score rating.
            appearance.rating = event_pulse_rating(line)
            appearance.data_source = line.source_label or "ESPN scoreboard + match summary (partial)"
            appearance.rating_kind = "event_pulse"
        after = (
            appearance.goals or 0,
            appearance.assists or 0,
            appearance.yellow_cards or 0,
            appearance.red_cards or 0,
            appearance.data_source,
            appearance.rating_kind,
        )
        if after != before:
            imported += 1

    session.commit()
    return imported

def upsert_espn_roster_players(
    session: Session,
    team_provider_id: str,
    player_lines: list[EspnRosterPlayer],
) -> int:
    """Persist named tournament squad members without fabricating appearances."""
    team = session.scalar(select(Team).where(Team.provider_id == team_provider_id))
    if not team:
        return 0
    imported = 0
    for line in player_lines:
        _find_or_create_player(
            session,
            {"provider_id": line.provider_id, "name": line.name, "position": line.position},
            team,
        )
        imported += 1
    session.commit()
    return imported


def get_player(session: Session, player_id: int) -> Player | None:
    return session.scalar(
        select(Player).where(Player.id == player_id).options(selectinload(Player.national_team))
    )


def _projection_out(player: Player, appearances: list[InternationalAppearance]) -> PlayerProjectionOut:
    # Event-only 2026 rows are intentionally excluded; they are not full match data.
    projection = project_player_from_international_history(_complete_appearance_rows(appearances))
    return PlayerProjectionOut(
        player_id=player.id,
        player_name=player.name,
        appearances_used=projection.appearances_used,
        expected_minutes=projection.expected_minutes,
        chance_to_score=projection.chance_to_score,
        chance_to_assist=projection.chance_to_assist,
        expected_rating=projection.expected_rating,
    )


def _tournament_line(appearances: list[InternationalAppearance]) -> TournamentLineOut:
    rows = [appearance for appearance in appearances if appearance.match_date.year == 2026]
    full_rows = _complete_appearance_rows(rows)
    event_rows = [appearance for appearance in rows if appearance.rating_kind == "event_pulse"]
    return TournamentLineOut(
        # A named goal, assist, or card proves the player took part in that match,
        # so it belongs in games played. It still does *not* become a full stat line
        # until ESPN publishes minutes and a real player box score.
        appearances=len(full_rows),
        games_played=len(rows),
        full_stat_lines=len(full_rows),
        event_linked_matches=len(event_rows),
        minutes=sum(appearance.minutes or 0 for appearance in full_rows),
        # A named ESPN goal/assist/card remains useful and verified even without a box score.
        goals=sum(appearance.goals or 0 for appearance in rows),
        assists=sum(appearance.assists or 0 for appearance in rows),
        yellow_cards=sum(appearance.yellow_cards or 0 for appearance in rows),
        red_cards=sum(appearance.red_cards or 0 for appearance in rows),
    )


def _player_summary(player: Player, appearances: list[InternationalAppearance]) -> PlayerSummaryOut:
    full_rows = _complete_appearance_rows(appearances)
    # Keep event goals visible in the player file, but never count them as complete
    # match records. This distinction is surfaced in the Player Explorer labels.
    minutes = sum(appearance.minutes or 0 for appearance in full_rows)
    goals = sum(appearance.goals or 0 for appearance in appearances)
    assists = sum(appearance.assists or 0 for appearance in appearances)
    xg_total = sum(appearance.xg or 0.0 for appearance in full_rows)
    last_appearance = max((appearance.match_date for appearance in appearances), default=None)
    return PlayerSummaryOut(
        player_id=player.id,
        player_name=player.name,
        position=player.position,
        national_team=TeamOut.model_validate(player.national_team),
        appearances=len(full_rows),
        minutes=minutes,
        goals=goals,
        assists=assists,
        xg=round(xg_total, 2) if xg_total else None,
        last_appearance_at=last_appearance,
        tournament_2026=_tournament_line(appearances),
        projection=_projection_out(player, appearances),
    )


def list_player_summaries(
    session: Session,
    *,
    query: str | None = None,
    team: str | None = None,
    limit: int = 120,
) -> list[PlayerSummaryOut]:
    statement = select(Player).join(Team).options(selectinload(Player.national_team))
    if query:
        statement = statement.where(Player.name.ilike(f"%{query.strip()}%"))
    if team:
        statement = statement.where(Team.name.ilike(f"%{team.strip()}%"))

    players = session.scalars(statement).all()
    if not players:
        return []

    player_ids = [player.id for player in players]
    all_appearances = session.scalars(
        select(InternationalAppearance)
        .where(InternationalAppearance.player_id.in_(player_ids))
        .order_by(InternationalAppearance.match_date.desc())
    ).all()
    by_player: dict[int, list[InternationalAppearance]] = defaultdict(list)
    for appearance in all_appearances:
        by_player[appearance.player_id].append(appearance)

    summaries = [_player_summary(player, by_player.get(player.id, [])) for player in players]
    summaries.sort(
        key=lambda item: (
            item.tournament_2026.goals,
            item.tournament_2026.assists,
            item.goals,
            item.assists,
            item.appearances,
            item.player_name.casefold(),
        ),
        reverse=True,
    )
    return summaries[: max(1, min(limit, 250))]


def get_player_detail(session: Session, player_id: int) -> PlayerDetailOut | None:
    player = get_player(session, player_id)
    if not player:
        return None
    appearances = session.scalars(
        select(InternationalAppearance)
        .where(InternationalAppearance.player_id == player_id)
        .order_by(InternationalAppearance.match_date.desc())
    ).all()
    summary = _player_summary(player, appearances)
    recent = [
        PlayerAppearanceOut(
            match_date=appearance.match_date,
            opponent_name=appearance.opponent_name,
            competition=appearance.competition,
            minutes=appearance.minutes,
            goals=appearance.goals,
            assists=appearance.assists,
            shots=appearance.shots,
            xg=appearance.xg,
            xa=appearance.xa,
            rating=appearance.rating,
            yellow_cards=appearance.yellow_cards,
            red_cards=appearance.red_cards,
            data_source=appearance.data_source,
            rating_label=("Live Pulse Rating" if appearance.rating_kind == "live_pulse" else ("Event Pulse (limited — verified goals, assists, and cards)" if appearance.rating_kind == "event_pulse" else "Pulse Rating")),
        )
        for appearance in appearances[:12]
    ]
    return PlayerDetailOut(**summary.model_dump(), recent_appearances=recent)


def _find_or_create_team(session: Session, incoming: dict[str, Any]) -> Team:
    provider_id = incoming.get("provider_id")
    team = session.scalar(select(Team).where(Team.provider_id == provider_id)) if provider_id else None
    if not team:
        team = session.scalar(select(Team).where(Team.name == incoming["name"]))
    if not team:
        team = Team(provider_id=provider_id, name=incoming["name"])
        session.add(team)
        session.flush()

    if team.provider_id is None and provider_id:
        team.provider_id = provider_id
    team.name = incoming["name"]
    team.code = incoming.get("code") or team.code
    team.logo_url = incoming.get("logo_url") or team.logo_url
    return team


def _canonical_player_name(value: str) -> str:
    """Match provider names despite accents, punctuation, and formatting differences."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    compact = re.sub(r"[^a-z0-9]+", " ", without_marks.casefold())
    return " ".join(compact.split())


def _find_or_create_player(session: Session, incoming: dict[str, Any], national_team: Team) -> Player:
    provider_id = incoming.get("provider_id")
    player = session.scalar(select(Player).where(Player.provider_id == provider_id)) if provider_id else None
    if not player:
        player = session.scalar(
            select(Player).where(Player.name == incoming["name"], Player.national_team_id == national_team.id)
        )
    if not player:
        incoming_key = _canonical_player_name(incoming["name"])
        # StatsBomb and ESPN sometimes differ only by accents or punctuation
        # (for example Mbappé vs Mbappe).  Resolve that to one local profile.
        same_team_players = session.scalars(
            select(Player).where(Player.national_team_id == national_team.id)
        ).all()
        player = next(
            (candidate for candidate in same_team_players if _canonical_player_name(candidate.name) == incoming_key),
            None,
        )
    if not player:
        player = Player(
            provider_id=provider_id,
            name=incoming["name"],
            position=incoming.get("position"),
            national_team_id=national_team.id,
        )
        session.add(player)
        session.flush()

    if player.provider_id is None and provider_id:
        player.provider_id = provider_id
    player.position = incoming.get("position") or player.position
    return player


def repair_equivalent_player_profiles(session: Session) -> int:
    """Merge legacy duplicate profiles created by provider name-format differences.

    This is deliberately conservative: only names with the same normalized spelling
    and the same national team are merged. Existing match rows are preserved.
    """
    players = session.scalars(select(Player).order_by(Player.national_team_id, Player.id)).all()
    grouped: dict[tuple[int, str], list[Player]] = defaultdict(list)
    for player in players:
        grouped[(player.national_team_id, _canonical_player_name(player.name))].append(player)

    merged_profiles = 0
    for group in grouped.values():
        if len(group) < 2:
            continue
        player_ids = [player.id for player in group]
        appearances = session.scalars(
            select(InternationalAppearance).where(InternationalAppearance.player_id.in_(player_ids))
        ).all()
        appearances_by_player: dict[int, list[InternationalAppearance]] = defaultdict(list)
        for appearance in appearances:
            appearances_by_player[appearance.player_id].append(appearance)

        primary = max(
            group,
            key=lambda item: (len(appearances_by_player.get(item.id, [])), bool(item.provider_id), -item.id),
        )
        for duplicate in group:
            if duplicate.id == primary.id:
                continue
            for appearance in list(appearances_by_player.get(duplicate.id, [])):
                existing = session.scalar(
                    select(InternationalAppearance).where(
                        InternationalAppearance.player_id == primary.id,
                        InternationalAppearance.match_id == appearance.match_id,
                    )
                )
                if existing:
                    existing.started = existing.started or appearance.started
                    existing.minutes = max(existing.minutes or 0, appearance.minutes or 0)
                    existing.goals = max(existing.goals or 0, appearance.goals or 0)
                    existing.assists = max(existing.assists or 0, appearance.assists or 0)
                    existing.shots = max(existing.shots or 0, appearance.shots or 0)
                    existing.xg = max(existing.xg or 0.0, appearance.xg or 0.0) or None
                    existing.yellow_cards = max(existing.yellow_cards or 0, appearance.yellow_cards or 0)
                    existing.red_cards = max(existing.red_cards or 0, appearance.red_cards or 0)
                    existing.rating = existing.rating if existing.rating is not None else appearance.rating
                    session.delete(appearance)
                else:
                    appearance.player_id = primary.id
            if not primary.position and duplicate.position:
                primary.position = duplicate.position
            session.delete(duplicate)
            merged_profiles += 1
    if merged_profiles:
        session.commit()
    return merged_profiles


def upsert_matches(session: Session, fixtures: list[dict[str, Any]]) -> bool:
    changed = False
    for incoming in fixtures:
        home_team = _find_or_create_team(session, incoming["home_team"])
        away_team = _find_or_create_team(session, incoming["away_team"])
        match = session.scalar(select(Match).where(Match.provider_id == incoming["provider_id"]))
        if not match:
            session.add(
                Match(
                    provider_id=incoming["provider_id"],
                    home_team_id=home_team.id,
                    away_team_id=away_team.id,
                    kickoff_at=incoming["kickoff_at"],
                    status=incoming["status"],
                    minute=incoming.get("minute"),
                    home_score=incoming.get("home_score"),
                    away_score=incoming.get("away_score"),
                    stage=incoming.get("stage") or "World Cup",
                    venue=incoming.get("venue"),
                    last_synced_at=datetime.now(UTC),
                )
            )
            changed = True
            continue

        tracked = ("kickoff_at", "status", "minute", "home_score", "away_score", "stage", "venue")
        before = tuple(getattr(match, field) for field in tracked)
        for field in tracked:
            setattr(match, field, incoming.get(field))
        match.home_team_id = home_team.id
        match.away_team_id = away_team.id
        match.last_synced_at = datetime.now(UTC)
        changed = changed or before != tuple(getattr(match, field) for field in tracked)
    session.commit()
    return changed


def delete_live_provider_fixtures(session: Session) -> int:
    result = session.execute(
        delete(Match).where(or_(Match.provider_id.like("demo-%"), Match.provider_id.like("api-football:%")))
    )
    session.commit()
    return int(result.rowcount or 0)


def seconds_until_espn_poll(
    session: Session, *, live_poll_seconds: int, idle_poll_seconds: int
) -> int:
    now = datetime.now(UTC)
    # Keep a short live cadence for the full probable match window, not only the
    # ten minutes before kickoff. If a public scoreboard briefly lags on a status
    # update, this still rechecks the game rather than waiting fifteen minutes.
    window_start = now - timedelta(hours=3)
    window_end = now + timedelta(hours=4)
    active_or_near = session.scalar(
        select(Match.id)
        .where(
            Match.provider_id.like("espn:%"),
            (Match.status.in_(LIVE_STATUSES) | ((Match.kickoff_at >= window_start) & (Match.kickoff_at <= window_end))),
        )
        .limit(1)
    )
    return live_poll_seconds if active_or_near is not None else idle_poll_seconds


def upsert_statsbomb_match_with_appearances(
    session: Session, match_data: dict[str, Any], appearances: list[dict[str, Any]]
) -> int:
    home_team = _find_or_create_team(session, match_data["home_team"])
    away_team = _find_or_create_team(session, match_data["away_team"])
    match = session.scalar(select(Match).where(Match.provider_id == match_data["provider_id"]))
    if not match:
        match = Match(
            provider_id=match_data["provider_id"],
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            kickoff_at=match_data["kickoff_at"],
            status="FT",
            minute=match_data.get("minute", 90),
            home_score=match_data.get("home_score"),
            away_score=match_data.get("away_score"),
            stage=match_data.get("stage") or "Historical World Cup",
            venue=match_data.get("venue"),
            last_synced_at=datetime.now(UTC),
        )
        session.add(match)
        session.flush()
    else:
        match.home_team_id = home_team.id
        match.away_team_id = away_team.id
        match.kickoff_at = match_data["kickoff_at"]
        match.status = "FT"
        match.minute = match_data.get("minute", 90)
        match.home_score = match_data.get("home_score")
        match.away_score = match_data.get("away_score")
        match.stage = match_data.get("stage") or match.stage
        match.venue = match_data.get("venue") or match.venue
        match.last_synced_at = datetime.now(UTC)
        session.flush()

    imported = 0
    team_by_name = {home_team.name: home_team, away_team.name: away_team}
    for incoming in appearances:
        national_team = team_by_name.get(incoming["national_team_name"])
        if not national_team:
            continue
        player = _find_or_create_player(session, incoming, national_team)
        appearance = session.scalar(
            select(InternationalAppearance).where(
                InternationalAppearance.player_id == player.id,
                InternationalAppearance.match_id == match.id,
            )
        )
        if not appearance:
            appearance = InternationalAppearance(
                player_id=player.id,
                match_id=match.id,
                match_date=match.kickoff_at,
                opponent_name=incoming["opponent_name"],
            )
            session.add(appearance)

        appearance.match_date = match.kickoff_at
        appearance.opponent_name = incoming["opponent_name"]
        appearance.competition = incoming.get("competition")
        appearance.started = bool(incoming.get("started", False))
        appearance.minutes = int(incoming.get("minutes", 0))
        appearance.goals = int(incoming.get("goals", 0))
        appearance.assists = int(incoming.get("assists", 0))
        appearance.shots = int(incoming.get("shots", 0))
        appearance.xg = incoming.get("xg")
        appearance.xa = incoming.get("xa")
        appearance.passes_completed = int(incoming.get("passes_completed", 0))
        appearance.passes_attempted = int(incoming.get("passes_attempted", 0))
        appearance.key_passes = int(incoming.get("key_passes", 0))
        appearance.tackles_won = int(incoming.get("tackles_won", 0))
        appearance.interceptions = int(incoming.get("interceptions", 0))
        appearance.clearances = int(incoming.get("clearances", 0))
        appearance.saves = int(incoming.get("saves", 0))
        appearance.rating = incoming.get("rating")
        appearance.data_source = "StatsBomb Open Data"
        appearance.rating_kind = "historical_pulse"
        imported += 1
    session.commit()
    return imported
