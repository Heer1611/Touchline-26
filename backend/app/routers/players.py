from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_session
from app.models import Team
from app.repository import (
    get_player_detail,
    list_player_summaries,
    upsert_espn_roster_players,
    upsert_statsbomb_match_with_appearances,
)
from app.schemas import HistoryImportOut, PlayerDetailOut, PlayerProjectionOut, PlayerSummaryOut, TeamOut
from app.services.espn import extract_roster_players
from app.services.statsbomb_open_data import StatsBombOpenDataImporter

router = APIRouter(prefix="/api/v1", tags=["players"])




@router.get("/teams", response_model=list[TeamOut])
def read_teams(session: Session = Depends(get_session)) -> list[TeamOut]:
    """Return the national teams currently seen in the 2026 schedule."""
    teams = session.scalars(
        select(Team)
        .where(Team.provider_id.like("espn:team:%"))
        .order_by(Team.name.asc())
    ).all()
    return [TeamOut.model_validate(team) for team in teams]


@router.post("/players/2026/sync-squads", response_model=HistoryImportOut)
async def sync_current_2026_squads(request: Request) -> HistoryImportOut:
    """Fetch named World Cup squads so Player Explorer is not event-only.

    ESPN's roster endpoint is unofficial and may occasionally omit a team. The
    operation preserves any existing player history; it only creates/updates squad
    profiles and never manufactures match appearances.
    """
    provider = request.app.state.sync_service.provider
    with SessionLocal() as session:
        teams = session.scalars(
            select(Team).where(Team.provider_id.like("espn:team:%")).order_by(Team.name.asc())
        ).all()
        targets = [(team.provider_id, team.name) for team in teams if team.provider_id]

    if not targets:
        raise HTTPException(status_code=409, detail="Load the 2026 fixture schedule before syncing national-team squads.")

    semaphore = asyncio.Semaphore(5)

    async def fetch_one(team_provider_id: str, team_name: str):
        team_id = team_provider_id.rsplit(":", 1)[-1]
        async with semaphore:
            try:
                payload = await provider.fetch_team_roster(team_id)
                return team_provider_id, team_name, extract_roster_players(payload, team_provider_id)
            except Exception:
                return team_provider_id, team_name, []

    fetched = await asyncio.gather(*(fetch_one(provider_id, name) for provider_id, name in targets))

    def write_rosters() -> tuple[int, int, int]:
        squads = 0
        players = 0
        failed = 0
        with SessionLocal() as session:
            for team_provider_id, _team_name, lines in fetched:
                if not lines:
                    failed += 1
                    continue
                squads += 1
                players += upsert_espn_roster_players(session, team_provider_id, lines)
        return squads, players, failed

    squads, players, failed = await asyncio.to_thread(write_rosters)
    await request.app.state.sync_service.publish_snapshot()
    unavailable_note = f" {failed} team roster feed(s) did not return players yet." if failed else ""
    return HistoryImportOut(
        source="ESPN public team roster feed",
        season="2026 FIFA World Cup squads",
        matches_imported=squads,
        player_appearances_imported=players,
        message=(
            f"Loaded {players} named player profiles across {squads} 2026 squads. "
            "Roster members with no verified event yet are labeled as squad profiles, not match-stat rows."
            + unavailable_note
        ),
    )


@router.get("/players", response_model=list[PlayerSummaryOut])
def read_players(
    q: str | None = Query(None, max_length=80, description="Player-name search"),
    team: str | None = Query(None, max_length=80, description="National-team filter"),
    limit: int = Query(120, ge=1, le=250),
    session: Session = Depends(get_session),
) -> list[PlayerSummaryOut]:
    return list_player_summaries(session, query=q, team=team, limit=limit)


@router.get("/players/{player_id}", response_model=PlayerDetailOut)
def read_player(player_id: int, session: Session = Depends(get_session)) -> PlayerDetailOut:
    player = get_player_detail(session, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found or has no imported match history")
    return player


@router.get("/players/{player_id}/projection", response_model=PlayerProjectionOut)
def read_player_projection(player_id: int, session: Session = Depends(get_session)) -> PlayerProjectionOut:
    player = get_player_detail(session, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found or has no imported match history")
    return player.projection




@router.post("/players/2026/sync-events", response_model=HistoryImportOut)
async def sync_current_2026_player_events(request: Request) -> HistoryImportOut:
    """Reconcile every completed/live 2026 match and return an honest audit.

    The route intentionally returns a useful audit for a partial ESPN outage rather
    than a generic 502. Successful dates, named events, and published box scores
    are saved; the message tells the user what still needs a later retry.
    """
    report = await request.app.state.sync_service.sync_entire_tournament()
    await request.app.state.sync_service.publish_snapshot()

    coverage = (
        f"Tournament coverage checked: {report.completed_seen} completed/live match(es) out of "
        f"{report.fixtures_seen} scheduled fixture(s); {report.summaries_checked} summary feed(s) were checked. "
        f"Saved {report.verified_event_rows_written} verified event-player row(s) and "
        f"{report.full_player_rows_written} full player-stat row(s)."
    )
    if report.warning:
        coverage += (
            f" {report.warning} Run Sync all 2026 data again later; the app will retry only through the same "
            "tournament-wide process and will keep all verified records already saved."
        )
    else:
        coverage += " Every successful provider date was processed. Missing box scores remain pending instead of guessed."

    return HistoryImportOut(
        source="ESPN public World Cup scoreboard + match summary",
        season="2026 FIFA World Cup",
        matches_imported=report.fixtures_seen,
        player_appearances_imported=report.verified_event_rows_written + report.full_player_rows_written,
        message=coverage,
    )


@router.post("/history/statsbomb/recent-world-cups", response_model=HistoryImportOut)
async def import_recent_world_cups(request: Request) -> HistoryImportOut:
    """One-click import for the free 2018 and 2022 men's World Cup match archive."""
    importer = StatsBombOpenDataImporter(get_settings())

    def write_match(match_data: dict, appearances: list[dict]) -> int:
        with SessionLocal() as session:
            return upsert_statsbomb_match_with_appearances(session, match_data, appearances)

    try:
        summary = await asyncio.to_thread(importer.import_recent_world_cups, write_match)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="StatsBomb Open Data could not be imported right now. Please try again.",
        ) from exc

    await request.app.state.sync_service.publish_snapshot()
    return HistoryImportOut(
        source="StatsBomb Open Data",
        season="2018 + 2022 FIFA World Cups",
        matches_imported=summary.matches,
        player_appearances_imported=summary.appearances,
        message=(
            "Free 2018 and 2022 World Cup player history is ready. Open a historical match card "
            "to see event stats and the transparent Pulse Rating for every player who appeared."
        ),
    )


@router.post("/history/statsbomb/2022", response_model=HistoryImportOut)
async def import_statsbomb_2022(request: Request) -> HistoryImportOut:
    """Compatibility endpoint retained for existing local installs."""
    importer = StatsBombOpenDataImporter(get_settings())

    def write_match(match_data: dict, appearances: list[dict]) -> int:
        with SessionLocal() as session:
            return upsert_statsbomb_match_with_appearances(session, match_data, appearances)

    try:
        summary = await asyncio.to_thread(importer.import_world_cup_season, "2022", write_match)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="StatsBomb Open Data could not be imported right now.") from exc

    await request.app.state.sync_service.publish_snapshot()
    return HistoryImportOut(
        source="StatsBomb Open Data",
        season="2022 FIFA World Cup",
        matches_imported=summary.matches,
        player_appearances_imported=summary.appearances,
        message="2022 World Cup player history is ready.",
    )
