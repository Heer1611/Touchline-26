from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_session
from app.repository import (
    get_match,
    get_match_detail,
    list_matches,
    upsert_espn_event_appearances,
    upsert_espn_match_appearances,
    upsert_matches,
)
from app.schemas import MatchDetailOut, MatchOut, MetaOut
from app.services.espn import extract_2026_event_player_lines, extract_live_event_feed, merge_event_player_lines
from app.services.espn_match_summary import extract_player_lines

router = APIRouter(prefix="/api/v1", tags=["matches"])
logger = logging.getLogger(__name__)


@router.get("/matches", response_model=list[MatchOut])
def read_matches(
    history: bool = Query(False, description="Include every stored historical fixture."),
    session: Session = Depends(get_session),
) -> list[MatchOut]:
    return list_matches(session, include_history=history)


@router.get("/matches/{provider_id}/detail", response_model=MatchDetailOut)
async def read_match_detail(
    provider_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> MatchDetailOut:
    """Open a Match Center and refresh 2026 game data on demand.

    ESPN's scoreboard publishes a live soccer event stream and compact team stats
    before it exposes a complete player table. We refresh that event snapshot on
    every Match Center poll, then use the separate summary endpoint for a full
    player box score whenever ESPN supplies it.
    """
    live_events: list[dict] = []
    team_stats: list[dict] = []
    refreshed_at: datetime | None = None
    scoreboard_event_lines = []
    summary: dict | None = None
    event_snapshot: dict | None = None

    if provider_id.startswith("espn:"):
        event_id = provider_id.split(":", 1)[1]
        stored = get_match(session, provider_id)
        if not stored:
            raise HTTPException(status_code=404, detail="Match not found")

        try:
            event_snapshot = await request.app.state.sync_service.provider.fetch_event_snapshot(
                event_id, stored.kickoff_at
            )
            if event_snapshot:
                # A Match Center poll should show the current score/status right
                # away instead of waiting for the background fixture job.
                upsert_matches(
                    session,
                    [request.app.state.sync_service.provider.normalize_event(event_snapshot)],
                )
                scoreboard_event_lines = extract_2026_event_player_lines(event_snapshot)
                if scoreboard_event_lines:
                    upsert_espn_event_appearances(session, provider_id, scoreboard_event_lines)
                refreshed_at = datetime.now(UTC)
        except Exception:
            logger.info("ESPN scoreboard event snapshot was unavailable for %s", provider_id, exc_info=True)

        try:
            summary = await request.app.state.sync_service.provider.fetch_match_summary(event_id, max_age_seconds=8)
            player_lines = extract_player_lines(summary)
            if player_lines:
                # This is a small local upsert. Keep it in the request session so
                # SQLAlchemy does not cross threads with an active transaction.
                upsert_espn_match_appearances(session, provider_id, player_lines)
            summary_event_lines = extract_2026_event_player_lines(summary)
            merged_event_lines = merge_event_player_lines(scoreboard_event_lines, summary_event_lines)
            if merged_event_lines:
                upsert_espn_event_appearances(session, provider_id, merged_event_lines)
        except Exception:
            # A missing or temporarily changed ESPN summary endpoint must not stop
            # the real-time event feed from appearing in Match Center.
            logger.info("ESPN player summary was unavailable for %s", provider_id, exc_info=True)

        if event_snapshot:
            # Combine the quick scoreboard incidents with richer summary-only plays
            # (subs, VAR, penalties, delay notes, and any extra team stats).
            live_events, team_stats = extract_live_event_feed(event_snapshot, summary)

    detail = get_match_detail(
        session,
        provider_id,
        live_events=live_events,
        team_stats=team_stats,
        refreshed_at=refreshed_at,
    )
    if not detail:
        raise HTTPException(status_code=404, detail="Match not found")

    if provider_id.startswith("espn:") and detail.live_event_data_available and not detail.actual_player_stats_available:
        detail.notice = (
            "Live score, team numbers, and player-linked match events below refresh automatically. "
            "ESPN has not published a complete player box score for this match yet, so full per-player "
            "ratings are not shown or guessed."
        )
    return detail


@router.get("/matches/{provider_id}", response_model=MatchOut)
def read_match(provider_id: str, session: Session = Depends(get_session)) -> MatchOut:
    match = get_match(session, provider_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


@router.post("/refresh", response_model=MetaOut)
async def refresh_fixtures(request: Request) -> MetaOut:
    # Match Desk is a fast live-score action. It refreshes yesterday/today/tomorrow
    # immediately instead of waiting for the slower tournament-wide archive audit.
    await request.app.state.sync_service.sync_live_window()
    await request.app.state.sync_service.publish_snapshot()
    return _meta(request)


@router.get("/meta", response_model=MetaOut)
def read_meta(request: Request) -> MetaOut:
    return _meta(request)


def _meta(request: Request) -> MetaOut:
    settings = get_settings()
    sync_service = request.app.state.sync_service
    return MetaOut(
        demo_mode=settings.demo_mode,
        poll_seconds=sync_service.next_poll_seconds(),
        live_data_source=(
            "Demo fixtures" if settings.demo_mode else "ESPN World Cup scoreboard + live event feed"
        ),
        historical_data_source="StatsBomb Open Data · men’s 2018 + 2022 World Cups",
        last_provider_sync_at=sync_service.last_provider_sync_at,
        provider_notice=sync_service.last_provider_error,
    )
