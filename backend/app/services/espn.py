from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.config import Settings


LIVE_STATE = "in"
CLOCK_PATTERN = re.compile(r"(\d+)")


@dataclass(frozen=True)
class EspnFetchAudit:
    """Outcome of one date-by-date tournament scoreboard pass.

    ESPN's public feed can intermittently time out on individual dates.  Keeping
    this audit separate lets the app save data from successful dates and tell the
    user precisely that a retry is needed, rather than failing the entire sync.
    """

    days_attempted: int
    days_succeeded: int
    failed_days: tuple[str, ...] = ()

    @property
    def days_failed(self) -> int:
        return len(self.failed_days)


class EspnScoreboardClient:
    """Small adapter around ESPN's public World Cup scoreboard JSON feed.

    ESPN does not publish this endpoint as a supported developer API. Keeping this
    integration in one adapter makes it easy to replace later with a licensed provider.
    """

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.espn_scoreboard_url
        self.summary_url = settings.espn_summary_url
        self.teams_url = self.base_url.rsplit("/", 1)[0] + "/teams"
        self.timeout = settings.espn_request_timeout_seconds
        self.scoreboard_concurrency = settings.espn_scoreboard_concurrency
        self.http_retries = settings.espn_http_retries
        self.retry_delay_seconds = settings.espn_retry_delay_seconds
        self.summary_cache_seconds = settings.espn_summary_cache_seconds
        self._summary_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._client: httpx.AsyncClient | None = None

    async def fetch_tournament_schedule(self, start: date, end: date) -> list[dict[str, Any]]:
        """Fetch and normalize every date in the requested tournament window."""
        events, _audit = await self.fetch_tournament_events_with_audit(start, end)
        return self._normalize_events(events)

    async def fetch_tournament_events(self, start: date, end: date) -> list[dict[str, Any]]:
        """Compatibility wrapper returning only raw tournament events."""
        events, _audit = await self.fetch_tournament_events_with_audit(start, end)
        return events

    async def fetch_tournament_events_with_audit(
        self, start: date, end: date
    ) -> tuple[list[dict[str, Any]], EspnFetchAudit]:
        """Fetch every calendar date with retries and a partial-result audit.

        The previous implementation opened many short-lived connections at once.
        That was fast when ESPN responded perfectly, but it made a manual
        tournament sync fragile: a temporary network failure or a competing
        background refresh could cause the whole action to fail.  This version
        intentionally uses gentler concurrency, retries transient request errors,
        and preserves any successful dates.
        """
        if end < start:
            return [], EspnFetchAudit(days_attempted=0, days_succeeded=0)

        days: list[date] = []
        cursor = start
        while cursor <= end:
            days.append(cursor)
            cursor += timedelta(days=1)

        semaphore = asyncio.Semaphore(max(1, self.scoreboard_concurrency))

        async def fetch_day(target: date) -> tuple[date, list[dict[str, Any]], str | None]:
            async with semaphore:
                try:
                    payload = await self._get({"dates": target.strftime("%Y%m%d"), "limit": 200})
                    rows = [item for item in (payload.get("events") or []) if isinstance(item, dict)]
                    return target, rows, None
                except Exception as exc:  # partial coverage is still useful
                    return target, [], f"{type(exc).__name__}: {exc}"

        fetched = await asyncio.gather(*(fetch_day(day) for day in days))
        successful_days = sum(1 for _, _, error in fetched if error is None)
        failed_days = tuple(target.isoformat() for target, _, error in fetched if error is not None)
        audit = EspnFetchAudit(
            days_attempted=len(days),
            days_succeeded=successful_days,
            failed_days=failed_days,
        )
        if not successful_days:
            # No data at all is different from a partial result.  The caller will
            # keep the existing local data and return an explanatory message.
            errors = [error for _, _, error in fetched if error]
            detail = errors[0] if errors else "ESPN did not return any scoreboard dates"
            raise RuntimeError(detail)

        by_id: dict[str, dict[str, Any]] = {}
        fallback_index = 0
        for _, rows, _ in fetched:
            for event in rows:
                raw_id = event.get("id")
                key = str(raw_id) if raw_id not in (None, "") else f"fallback:{fallback_index}"
                fallback_index += 1
                by_id[key] = event
        return list(by_id.values()), audit

    async def fetch_today(self, today: date | None = None) -> list[dict[str, Any]]:
        target = today or datetime.now(UTC).date()
        events = await self.fetch_raw_events(target.isoformat(), target.isoformat())
        return self._normalize_events(events)

    async def fetch_live_window_events(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch the exact current UTC scoreboard date for the fast live path.

        ESPN's range form (``dates=YYYYMMDD-YYYYMMDD``) is useful for a schedule
        audit, but during live soccer it can lag behind the single-day endpoint.
        Asking for the exact provider day keeps the active score, period, and
        delay/suspension state current without repeatedly scanning the whole draw.
        Future fixtures remain available from the separately persisted schedule.
        """
        current = (now or datetime.now(UTC)).astimezone(UTC)
        payload = await self._get({"dates": current.strftime("%Y%m%d"), "limit": 200})
        events = payload.get("events") or []
        return [event for event in events if isinstance(event, dict)]

    async def fetch_raw_events(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Return raw scoreboard events for a bounded YYYY-MM-DD window."""
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        payload = await self._get({"dates": f"{start:%Y%m%d}-{end:%Y%m%d}", "limit": 200})
        events = payload.get("events") or []
        return [event for event in events if isinstance(event, dict)]

    async def fetch_event_snapshot(self, event_id: str, kickoff_at: datetime) -> dict[str, Any] | None:
        """Return the freshest raw scoreboard event for one match.

        The fast path asks ESPN for one exact date instead of a wide range. That keeps
        a live Match Center responsive on a five-second cadence. We only fall back to
        neighbouring provider dates if the event is absent from the first response.
        """
        now_day = datetime.now(UTC).date()
        kickoff_day = kickoff_at.astimezone(UTC).date()
        candidate_days: list[date] = []
        for candidate in (now_day, kickoff_day, kickoff_day - timedelta(days=1), kickoff_day + timedelta(days=1)):
            if candidate not in candidate_days:
                candidate_days.append(candidate)
        for target in candidate_days:
            payload = await self._get({"dates": target.strftime("%Y%m%d"), "limit": 200})
            for event in payload.get("events") or []:
                if str(event.get("id")) == str(event_id):
                    return event
        return None

    def normalize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Public, narrow wrapper used by the Match Center refresh path."""
        return self._normalize_event(event)

    async def fetch_team_roster(self, team_id: str) -> dict[str, Any]:
        """Fetch one national team's current roster from ESPN's public team feed."""
        return await self._get_from(f"{self.teams_url}/{team_id}/roster", {})

    async def fetch_match_summary(self, event_id: str, *, max_age_seconds: int | None = None) -> dict[str, Any]:
        """Fetch a match summary with a small cache for rapid Match Center polling."""
        cached = self._summary_cache.get(event_id)
        now = datetime.now(UTC)
        ttl = self.summary_cache_seconds if max_age_seconds is None else max_age_seconds
        if cached and (now - cached[0]).total_seconds() < max(0, ttl):
            return cached[1]
        payload = await self._get_from(self.summary_url, {"event": event_id})
        self._summary_cache[event_id] = (now, payload)
        return payload

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, params: dict[str, str | int]) -> dict[str, Any]:
        return await self._get_from(self.base_url, params)

    async def _get_from(self, url: str, params: dict[str, str | int]) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Touchline26/1.1 (personal portfolio project)",
        }
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, headers=headers, limits=httpx.Limits(max_keepalive_connections=8, max_connections=12))
        last_error: Exception | None = None
        attempts = max(1, self.http_retries)
        for attempt in range(attempts):
            try:
                response = await self._client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("ESPN returned a non-object JSON payload")
                return payload
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                # Do not retry ordinary client-side errors except temporary rate limits.
                if status_code != 429 and status_code < 500:
                    raise
            except (httpx.RequestError, ValueError) as exc:
                last_error = exc

            if attempt < attempts - 1:
                await asyncio.sleep(self.retry_delay_seconds * (2**attempt))

        assert last_error is not None
        raise last_error

    def _normalize_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fixtures: list[dict[str, Any]] = []
        for event in events:
            try:
                fixtures.append(self._normalize_event(event))
            except (KeyError, TypeError, ValueError):
                # One malformed event should not stop all other valid fixtures.
                continue
        return fixtures

    def _normalize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        competition = (event.get("competitions") or [{}])[0]
        status = competition.get("status") or event.get("status") or {}
        status_type = status.get("type") or {}
        kickoff_at = _parse_datetime(event.get("date") or competition.get("date"))
        normalized_status = _normalize_status(status_type)
        minute = _extract_minute(status)

        competitors = competition.get("competitors") or []
        home = _find_competitor(competitors, "home")
        away = _find_competitor(competitors, "away")
        if not home or not away:
            raise ValueError("ESPN event did not include both home and away competitors")

        home_score = _parse_score(home.get("score"))
        away_score = _parse_score(away.get("score"))
        if normalized_status in {"NS", "PST", "CANC"}:
            home_score = None
            away_score = None

        # ESPN's live state is trusted, but stale provider values should never make a
        # future kickoff appear live on the dashboard.
        if normalized_status in {"LIVE", "HT", "P", "SUSP"} and kickoff_at > datetime.now(UTC) + timedelta(minutes=2):
            normalized_status = "NS"
            minute = None
            home_score = None
            away_score = None

        venue = competition.get("venue") or event.get("venue") or {}
        stage = _stage_for(event, competition)

        return {
            "provider_id": f"espn:{event['id']}",
            "kickoff_at": kickoff_at,
            "status": normalized_status,
            "minute": minute,
            "home_score": home_score,
            "away_score": away_score,
            "stage": stage,
            "venue": venue.get("fullName") or venue.get("displayName"),
            "home_team": _normalize_team(home),
            "away_team": _normalize_team(away),
        }


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        raise ValueError("ESPN event is missing a kickoff time")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _find_competitor(competitors: list[dict[str, Any]], home_away: str) -> dict[str, Any] | None:
    return next((item for item in competitors if item.get("homeAway") == home_away), None)


def _normalize_team(competitor: dict[str, Any]) -> dict[str, Any]:
    team = competitor.get("team") or {}
    if not team.get("id") or not team.get("displayName"):
        raise ValueError("ESPN competitor is missing team identity")
    return {
        "provider_id": f"espn:team:{team['id']}",
        "name": team["displayName"],
        "code": team.get("abbreviation"),
        "logo_url": team.get("logo"),
    }


def _normalize_status(status_type: dict[str, Any]) -> str:
    """Map ESPN's state machine without hiding a paused in-progress match.

    ESPN can label a started match ``STATUS_DELAYED`` while keeping
    ``state == 'in'`` and a real match clock.  Treating every delayed value as a
    pre-match postponement incorrectly buries the game below future fixtures. An
    in-progress delay is represented locally as ``SUSP`` so it remains in the
    live section with its current score; a true pre-kickoff delay remains ``PST``.
    """
    name = str(status_type.get("name") or "").upper()
    state = str(status_type.get("state") or "").lower()
    detail = " ".join(
        str(status_type.get(key) or "") for key in ("description", "detail", "shortDetail")
    ).upper()

    if "CANCEL" in name or "CANCEL" in detail:
        return "CANC"
    if bool(status_type.get("completed")) or state == "post" or "FINAL" in name:
        return "FT"

    # Prioritize ESPN's in-progress state. A delayed or suspended match with a
    # live clock has started and must stay in the live board.
    if state == LIVE_STATE:
        if "DELAY" in name or "DELAY" in detail or "SUSPEND" in name or "SUSPEND" in detail:
            return "SUSP"
        if "HALFTIME" in name or "HALFTIME" in detail:
            return "HT"
        if "PENALTY" in name or "SHOOTOUT" in detail:
            return "P"
        return "LIVE"

    if "POSTPON" in name or "POSTPON" in detail or "DELAY" in name or "DELAY" in detail:
        return "PST"
    if "HALFTIME" in name or "HALFTIME" in detail:
        return "HT"
    if "PENALTY" in name or "SHOOTOUT" in detail:
        return "P"
    if "SUSPEND" in name or "SUSPEND" in detail:
        return "SUSP"
    return "NS"


def _extract_minute(status: dict[str, Any]) -> int | None:
    display_clock = str(status.get("displayClock") or "")
    match = CLOCK_PATTERN.search(display_clock)
    if match:
        return int(match.group(1))
    return None


def _parse_score(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stage_for(event: dict[str, Any], competition: dict[str, Any]) -> str:
    notes = competition.get("notes") or []
    if notes and isinstance(notes[0], dict):
        headline = notes[0].get("headline")
        if headline:
            return str(headline).replace("FIFA World Cup, ", "")

    alternate = competition.get("altGameNote") or event.get("season", {}).get("type", {}).get("name")
    if alternate:
        return str(alternate).replace("FIFA World Cup, ", "")
    return "World Cup"


# Live event and team-stat normalizers -------------------------------------------------
# The feed's `details` array is available even when ESPN has not yet exposed a full
# player box score. Showing this separately prevents the site from looking frozen
# while keeping the distinction between verified events and a full stat line honest.

_STAT_LABELS = {
    "possessionPct": "Possession", "possession": "Possession",
    "totalShots": "Shots", "shots": "Shots",
    "shotsOnTarget": "On target", "shotsOnGoal": "On target",
    "shotsOffTarget": "Off target", "blockedShots": "Blocked shots",
    "wonCorners": "Corners", "corners": "Corners",
    "foulsCommitted": "Fouls", "fouls": "Fouls",
    "offsides": "Offsides", "totalGoals": "Goals",
    "goalAssists": "Assists", "shotAssists": "Key passes",
    "expectedGoals": "xG", "xg": "xG", "expectedGoalsOnTarget": "xGOT",
    "totalPasses": "Passes", "passes": "Passes",
    "accuratePasses": "Accurate passes", "passesCompleted": "Accurate passes",
    "passPct": "Pass accuracy", "passAccuracy": "Pass accuracy",
    "saves": "Saves", "tackles": "Tackles", "interceptions": "Interceptions",
    "clearances": "Clearances", "yellowCards": "Yellow cards", "redCards": "Red cards",
    "bigChances": "Big chances", "bigChancesCreated": "Big chances created",
    "duelsWon": "Duels won", "dribbles": "Dribbles",
}


def extract_live_event_feed(
    event: dict[str, Any], summary: dict[str, Any] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize a richer live event stream from scoreboard *and* match summary.

    ESPN can publish useful live information in more than one place. The scoreboard
    usually updates quickest; the summary can add substitutions, VAR decisions,
    penalties, injury/delay notes, longer play text, and extra team statistics. The
    two streams are deduplicated by ESPN event identity so the feed is fuller, not
    repetitive. Every entry remains provider-published text or a transparent label.
    """
    competition = (event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    teams: dict[str, dict[str, Any]] = {}
    team_stats_by_key: dict[str, dict[str, Any]] = {}

    def add_team_stat(team_name: str | None, team_code: str | None, values: dict[str, str]) -> None:
        if not team_name or not values:
            return
        key = str(team_name).casefold()
        target = team_stats_by_key.setdefault(key, {"team_name": str(team_name), "team_code": team_code, "stats": {}})
        target["stats"].update(values)

    for competitor in competitors:
        team = competitor.get("team") or {}
        team_id = str(team.get("id")) if team.get("id") is not None else None
        team_name = team.get("displayName") or team.get("name")
        team_code = team.get("abbreviation")
        if team_id and team_name:
            teams[team_id] = {"team_name": str(team_name), "team_code": team_code}
        add_team_stat(team_name, team_code, _stat_values_from_items(competitor.get("statistics") or []))

    if summary:
        for row in _summary_team_stat_rows(summary):
            team = row.get("team") or row.get("competitor") or {}
            if not isinstance(team, dict):
                team = {}
            team_id = str(team.get("id")) if team.get("id") is not None else None
            team_name = team.get("displayName") or team.get("name") or row.get("teamName")
            team_code = team.get("abbreviation") or row.get("teamCode")
            if team_id and team_name:
                teams.setdefault(team_id, {"team_name": str(team_name), "team_code": team_code})
            add_team_stat(team_name, team_code, _stat_values_from_items(row.get("statistics") or row.get("stats") or []))

    event_rows: list[tuple[dict[str, Any], str]] = []
    event_rows.extend((detail, "scoreboard") for detail in _event_details_from_payload(event))
    if summary:
        event_rows.extend((detail, "match summary") for detail in _event_details_from_payload(summary))

    feed_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    for index, (detail, source) in enumerate(event_rows):
        identity = _event_identity(detail)
        item = _live_event_out(detail, event_id=str(event.get("id") or "event"), index=index, teams=teams, source=source)
        existing = feed_by_key.get(identity)
        if existing is None:
            feed_by_key[identity] = item
        else:
            # Summary prose commonly contains more context than the compact scoreboard row.
            if len(item["description"]) > len(existing["description"]):
                feed_by_key[identity] = item
            elif existing.get("score") is None and item.get("score") is not None:
                existing.update({key: value for key, value in item.items() if value is not None})

    events = list(feed_by_key.values())
    events.sort(key=_live_event_order, reverse=True)
    return events[:60], list(team_stats_by_key.values())


def _stat_values_from_items(items: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    if isinstance(items, dict):
        iterable = [{"name": key, "displayValue": value} for key, value in items.items()]
    elif isinstance(items, list):
        iterable = items
    else:
        return values
    for item in iterable:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or item.get("label") or item.get("displayName") or item.get("abbreviation") or "")
        label = _STAT_LABELS.get(raw_name) or _STAT_LABELS.get(raw_name.casefold())
        value = item.get("displayValue")
        if value in (None, ""):
            value = item.get("value")
        if not label or value in (None, ""):
            continue
        values[label] = str(value)
    return values


def _summary_team_stat_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    roots: list[dict[str, Any]] = [summary]
    boxscore = summary.get("boxscore")
    if isinstance(boxscore, dict):
        roots.append(boxscore)
    for root in roots:
        for key in ("teams", "teamStats", "competitors"):
            value = root.get(key)
            if isinstance(value, list):
                rows.extend(row for row in value if isinstance(row, dict))
    return rows


def _detail_type_text(detail: dict[str, Any]) -> str:
    type_info = detail.get("type") or detail.get("eventType") or {}
    if isinstance(type_info, dict):
        for key in ("text", "displayName", "name", "description"):
            value = type_info.get(key)
            if value:
                return str(value)
    elif type_info:
        return str(type_info)
    for key in ("shortText", "text", "description", "headline"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Match event"


def _detail_text(detail: dict[str, Any]) -> str | None:
    for key in ("shortText", "text", "description", "headline", "commentary", "summary"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _event_kind(lower: str, detail: dict[str, Any]) -> tuple[str, str]:
    if bool(detail.get("scoringPlay")) or "goal" in lower:
        return "goal", "⚽"
    if "yellow" in lower:
        return "yellow-card", "■"
    if "red" in lower:
        return "red-card", "■"
    if "sub" in lower or "replacement" in lower:
        return "substitution", "⇄"
    if "penalty" in lower or "pen" in lower:
        return "penalty", "●"
    if "var" in lower or "review" in lower:
        return "var", "VAR"
    if "injur" in lower or "medical" in lower:
        return "injury", "+"
    if "delay" in lower or "suspend" in lower:
        return "delay", "⏸"
    if "save" in lower:
        return "save", "🧤"
    if "shot" in lower or "miss" in lower:
        return "shot", "◌"
    if "offside" in lower:
        return "offside", "⚑"
    if "half" in lower or "period" in lower or "final" in lower:
        return "period", "⌁"
    return "other", "•"


def _event_team_name(detail: dict[str, Any], teams: dict[str, dict[str, Any]]) -> str | None:
    raw_team = detail.get("team") or detail.get("competitor") or {}
    if isinstance(raw_team, dict):
        team_id = str(raw_team.get("id")) if raw_team.get("id") is not None else None
        if team_id and team_id in teams:
            return teams[team_id]["team_name"]
        return raw_team.get("displayName") or raw_team.get("name")
    return None


def _event_score(detail: dict[str, Any]) -> str | None:
    home = detail.get("homeScore") or detail.get("homeTeamScore")
    away = detail.get("awayScore") or detail.get("awayTeamScore")
    if home not in (None, "") and away not in (None, ""):
        return f"{home}–{away}"
    raw = detail.get("score") or detail.get("scoreDisplay")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _event_period(detail: dict[str, Any]) -> str | None:
    raw = detail.get("period") or detail.get("periodName")
    if isinstance(raw, dict):
        value = raw.get("displayName") or raw.get("name") or raw.get("number")
    else:
        value = raw
    if value in (None, ""):
        return None
    return str(value)


def _live_event_out(detail: dict[str, Any], *, event_id: str, index: int, teams: dict[str, dict[str, Any]], source: str) -> dict[str, Any]:
    event_type = _detail_type_text(detail)
    lower = event_type.casefold()
    clock = detail.get("clock") or {}
    minute = clock.get("displayValue") or detail.get("displayClock") or detail.get("minute")
    people = _event_people(detail)
    is_goal = bool(detail.get("scoringPlay")) or "goal" in lower
    primary = _event_primary_person(people, is_goal=is_goal) if people else None
    player_name = _person_name(primary)
    assists = _event_assist_people(detail, people) if is_goal else []
    assist_name = _person_name(assists[0]) if assists else None
    kind, icon = _event_kind(lower, detail)
    description = _detail_text(detail) or event_type
    if player_name and player_name.casefold() not in description.casefold():
        description = f"{player_name} — {description}"
    if assist_name and assist_name.casefold() not in description.casefold():
        description += f" (assist: {assist_name})"
    return {
        "event_id": ":".join((event_id, *(_event_identity(detail)), str(index))),
        "minute": str(minute) if minute not in (None, "") else None,
        "type": event_type,
        "description": description,
        "team_name": _event_team_name(detail, teams),
        "player_name": str(player_name) if player_name else None,
        "assist_name": str(assist_name) if assist_name else None,
        "icon": icon,
        "kind": kind,
        "score": _event_score(detail),
        "period": _event_period(detail),
        "source": source,
    }


def _live_event_order(item: dict[str, Any]) -> tuple[int, int]:
    value = item.get("minute") or ""
    number = CLOCK_PATTERN.search(str(value))
    # Keep named/live incidents above generic period notices at the same minute.
    kind_rank = 1 if item.get("kind") not in {"period", "other"} else 0
    return (int(number.group(1)) if number else -1, kind_rank)


# Player-event stat normalizer --------------------------------------------------------
# The scoreboard includes player-linked goals and cards even when it does not expose a
# complete player box score. We store these as partial, verified event stats so 2026
# World Cup player profiles do not look empty. Missing metrics remain missing/zero;
# they are never estimated as real match data.


@dataclass
class EspnEventPlayerLine:
    provider_id: str | None
    name: str
    team_provider_id: str | None
    position: str | None = None
    goals: int = 0
    assists: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    last_event_minute: int | None = None
    fields_seen: int = 0
    # Optional provenance used only by auditable reconciliation entries.
    source_label: str | None = None


def extract_2026_event_player_lines(event: dict[str, Any]) -> list[EspnEventPlayerLine]:
    """Build partial player rows from verified ESPN goal/assist/card events.

    ESPN uses more than one event shape across soccer scoreboards. A goal's assist
    can arrive as the second ``athletesInvolved`` item, as a participant whose role
    is ``assist``, as a dedicated ``assistAthlete`` field, or in a clearly labelled
    text field. This parser accepts those explicit shapes while refusing to infer an
    assist from a generic second participant.

    This intentionally excludes minutes, shots, passing, xG, and defensive actions
    unless a separate ESPN box score provides them. A player appears here only when
    the current match feed explicitly identifies them in an event.
    """
    details = _event_details_from_payload(event)
    by_key: dict[tuple[str | None, str | None, str], EspnEventPlayerLine] = {}
    seen_events: set[tuple[str, ...]] = set()

    for detail in details:
        event_key = _event_identity(detail)
        if event_key in seen_events:
            continue
        seen_events.add(event_key)
        type_info = detail.get("type") or {}
        event_type = (
            str(type_info.get("text") or type_info.get("displayName") or type_info.get("name") or "")
            if isinstance(type_info, dict)
            else str(type_info)
        ).casefold()
        is_goal = bool(detail.get("scoringPlay")) or event_type == "goal" or " goal" in event_type
        is_yellow = bool(detail.get("yellowCard")) or "yellow" in event_type
        is_red = bool(detail.get("redCard")) or "red" in event_type
        if not (is_goal or is_yellow or is_red):
            continue

        team = detail.get("team") or {}
        team_id = team.get("id")
        team_provider_id = f"espn:team:{team_id}" if team_id is not None else None
        people = _event_people(detail)
        if not people:
            continue

        minute = _event_minute(detail)
        primary = _event_primary_person(people, is_goal=is_goal)
        if primary:
            _apply_event_person(
                by_key,
                primary,
                team_provider_id=team_provider_id,
                minute=minute,
                goals=1 if is_goal else 0,
                yellow_cards=1 if is_yellow else 0,
                red_cards=1 if is_red else 0,
            )

        if is_goal:
            primary_name = _person_name(primary).casefold() if primary and _person_name(primary) else None
            for assistant in _event_assist_people(detail, people):
                assistant_name = _person_name(assistant)
                if not assistant_name or assistant_name.casefold() == primary_name:
                    continue
                _apply_event_person(
                    by_key,
                    assistant,
                    team_provider_id=team_provider_id,
                    minute=minute,
                    assists=1,
                )

    return list(by_key.values())


def merge_event_player_lines(*groups: list[EspnEventPlayerLine]) -> list[EspnEventPlayerLine]:
    """Combine event payload variants without double-counting one athlete.

    ESPN's scoreboard and match-summary feeds occasionally disagree about the team
    object attached to a duplicate athlete entry.  A real ESPN athlete ID is the
    strongest identity, so it is used before a team/name fallback.  This prevents
    two lines for the same athlete/match from reaching the database.
    """
    merged: dict[tuple[str, ...], EspnEventPlayerLine] = {}
    for group in groups:
        for incoming in group:
            if incoming.provider_id:
                key = ("provider", incoming.provider_id)
            else:
                key = (
                    "fallback",
                    incoming.team_provider_id or "",
                    incoming.name.casefold(),
                )
            existing = merged.get(key)
            if existing is None:
                merged[key] = EspnEventPlayerLine(
                    provider_id=incoming.provider_id,
                    name=incoming.name,
                    team_provider_id=incoming.team_provider_id,
                    position=incoming.position,
                    goals=incoming.goals,
                    assists=incoming.assists,
                    yellow_cards=incoming.yellow_cards,
                    red_cards=incoming.red_cards,
                    last_event_minute=incoming.last_event_minute,
                    fields_seen=incoming.fields_seen,
                    source_label=incoming.source_label,
                )
                continue
            existing.goals = max(existing.goals, incoming.goals)
            existing.assists = max(existing.assists, incoming.assists)
            existing.yellow_cards = max(existing.yellow_cards, incoming.yellow_cards)
            existing.red_cards = max(existing.red_cards, incoming.red_cards)
            existing.fields_seen = max(existing.fields_seen, incoming.fields_seen)
            existing.last_event_minute = max(
                existing.last_event_minute or 0, incoming.last_event_minute or 0
            ) or None
            existing.position = existing.position or incoming.position
            # Preserve the first valid team association.  Repository-level roster
            # validation corrects it when a known player profile says otherwise.
            existing.team_provider_id = existing.team_provider_id or incoming.team_provider_id
            existing.source_label = incoming.source_label or existing.source_label
    return list(merged.values())

def _event_details_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Find soccer event rows in scoreboard and match-summary payload variants."""
    roots: list[dict[str, Any]] = [payload]
    header = payload.get("header")
    if isinstance(header, dict):
        roots.append(header)
    game_info = payload.get("gameInfo")
    if isinstance(game_info, dict):
        roots.append(game_info)

    details: list[dict[str, Any]] = []
    seen_object_ids: set[int] = set()
    for root in roots:
        for key in ("details", "plays", "scoringPlays", "commentary", "events"):
            value = root.get(key)
            if isinstance(value, list):
                details.extend(item for item in value if isinstance(item, dict))
        competitions = root.get("competitions") or []
        if isinstance(competitions, list):
            for competition in competitions:
                if not isinstance(competition, dict):
                    continue
                for key in ("details", "plays", "scoringPlays", "commentary", "events"):
                    value = competition.get(key)
                    if isinstance(value, list):
                        details.extend(item for item in value if isinstance(item, dict))

    # A few summary payloads nest one extra event list under a play container.
    expanded: list[dict[str, Any]] = []
    for detail in details:
        if id(detail) in seen_object_ids:
            continue
        seen_object_ids.add(id(detail))
        expanded.append(detail)
        for key in ("details", "plays", "events"):
            nested = detail.get(key)
            if isinstance(nested, list):
                expanded.extend(item for item in nested if isinstance(item, dict))
    return expanded


def _event_identity(detail: dict[str, Any]) -> tuple[str, ...]:
    """Stable event identity used to ignore the same event repeated in a payload."""
    for key in ("id", "eventId", "guid", "sequenceNumber", "sequence"):
        value = detail.get(key)
        if value not in (None, ""):
            return (key, str(value))
    team = detail.get("team") or {}
    type_info = detail.get("type") or {}
    event_type = (
        str(type_info.get("text") or type_info.get("displayName") or type_info.get("name") or "")
        if isinstance(type_info, dict)
        else str(type_info)
    ).casefold()
    clock = str((detail.get("clock") or {}).get("displayValue") or detail.get("displayClock") or "")
    people = ",".join(
        person.casefold() for person in (_person_name(value) for value in _event_people(detail)) if person
    )
    text = str(detail.get("shortText") or detail.get("text") or detail.get("description") or "").casefold()
    return (
        str(team.get("id") or ""), event_type, clock, people, text
    )


def _event_people(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Return named athlete dictionaries from common ESPN event payload shapes."""
    people: list[dict[str, Any]] = []
    for key in ("athletesInvolved", "participants", "athletes", "players", "scorers", "assistAthletes", "assists"):
        people.extend(_people_from_value(detail.get(key)))
    for key in ("athlete", "player", "scorer", "scoringAthlete", "secondaryAthlete", "assistAthlete", "assistedBy", "assistPlayer", "assistingAthlete"):

        people.extend(_people_from_value(detail.get(key)))

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str]] = set()
    for person in people:
        name = _person_name(person)
        if not name:
            continue
        athlete_id = str(person.get("id")) if person.get("id") is not None else None
        marker = (athlete_id, name.casefold())
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(person)
    return deduped


def _people_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str) and value.strip():
        return [{"displayName": value.strip()}]
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for item in value:
            result.extend(_people_from_value(item))
        return result
    if not isinstance(value, dict):
        return []

    # Participant entries often wrap the actual athlete under one of these keys.
    for key in ("athlete", "player"):
        nested = value.get(key)
        if isinstance(nested, dict):
            merged = dict(nested)
            for role_key in ("role", "type", "description", "label"):
                if role_key in value and role_key not in merged:
                    merged[role_key] = value[role_key]
            return [merged]

    if _person_name(value):
        return [value]
    return []


def _person_name(person: dict[str, Any] | None) -> str | None:
    if not isinstance(person, dict):
        return None
    value = person.get("displayName") or person.get("fullName") or person.get("shortName") or person.get("name")
    return str(value).strip() if isinstance(value, str) and value.strip() else None


def _role_text(person: dict[str, Any]) -> str:
    bits: list[str] = []
    for key in ("role", "type", "description", "label"):
        value = person.get(key)
        if isinstance(value, dict):
            bits.extend(str(item) for item in value.values() if isinstance(item, (str, int)))
        elif value is not None:
            bits.append(str(value))
    return " ".join(bits).casefold()


def _event_primary_person(people: list[dict[str, Any]], *, is_goal: bool) -> dict[str, Any] | None:
    if is_goal:
        for person in people:
            role = _role_text(person)
            if any(token in role for token in ("scorer", "goal scorer", "scoring")):
                return person
    for person in people:
        if "assist" not in _role_text(person):
            return person
    return people[0] if people else None


def _event_assist_people(detail: dict[str, Any], people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find explicitly identified assists without treating arbitrary participants as assists."""
    candidates: list[dict[str, Any]] = []
    for person in people:
        if "assist" in _role_text(person):
            candidates.append(person)

    # ESPN has used several direct keys over time. Accept them only when named.
    for key in (
        "assist", "assistedBy", "assistAthlete", "assistPlayer", "assistingAthlete",
        "secondaryAthlete", "secondaryPlayer", "helper", "helpers", "assistAthletes",
    ):
        candidates.extend(_people_from_value(detail.get(key)))

    # The most common soccer event form is scorer first, named assister second.
    # Keep this backwards-compatible fallback only when the second person's role is
    # absent; ESPN's soccer feed uses this ordering for a scored goal.
    if not candidates and len(people) >= 2 and not _role_text(people[1]):
        candidates.append(people[1])

    # Some payloads publish a plain-English assist phrase but omit a second athlete.
    # Accept only unmistakable text such as "Assisted by Jane Doe" or "Assist: Jane Doe".
    if not candidates:
        for key in ("shortText", "text", "description", "headline", "displayValue", "summary", "commentary"):

            raw = detail.get(key)
            if not isinstance(raw, str):
                continue
            match = re.search(
                r"(?:assisted\s+by|assist(?:ed)?\s*[:\-])\s*([A-Za-zÀ-ÖØ-öø-ÿ.'’\- ]{2,80}?)(?=$|[.;,)])",
                raw,
                flags=re.IGNORECASE,
            )
            if match:
                name = match.group(1).strip(" .;,)\u201d\u201c")
                if name:
                    candidates.append({"displayName": name})
                    break
            # Some event summaries use parenthetical notation, e.g.
            # "Matheus Cunha goal (Vinicius Junior assist)".
            parenthetical = re.search(
                r"[,(]\s*([A-Za-zÀ-ÖØ-öø-ÿ.'’\- ]{2,80}?)\s+assist(?:\)|,|$)",
                raw,
                flags=re.IGNORECASE,
            )
            if parenthetical:
                name = parenthetical.group(1).strip(" .;,)\u201d\u201c")
                if name:
                    candidates.append({"displayName": name})
                    break

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str]] = set()
    for person in candidates:
        name = _person_name(person)
        if not name:
            continue
        athlete_id = str(person.get("id")) if person.get("id") is not None else None
        marker = (athlete_id, name.casefold())
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(person)
    return deduped

def event_pulse_rating(line: EspnEventPlayerLine) -> float | None:
    """Small transparent rating for event-only rows, not an official player rating."""
    if not line.fields_seen:
        return None
    rating = 5.8 + line.goals * 1.45 + line.assists * 0.75 - line.yellow_cards * 0.20 - line.red_cards * 2.20
    return round(max(0.0, min(10.0, rating)), 1)


def _apply_event_person(
    by_key: dict[tuple[str | None, str | None, str], EspnEventPlayerLine],
    person: dict[str, Any],
    *,
    team_provider_id: str | None,
    minute: int | None,
    goals: int = 0,
    assists: int = 0,
    yellow_cards: int = 0,
    red_cards: int = 0,
    source_label: str | None = None,
) -> None:
    if not isinstance(person, dict):
        return
    name = person.get("displayName") or person.get("fullName") or person.get("shortName")
    if not name:
        return
    person_team = person.get("team") or {}
    resolved_team_id = person_team.get("id") if isinstance(person_team, dict) else None
    resolved_team = f"espn:team:{resolved_team_id}" if resolved_team_id is not None else team_provider_id
    athlete_id = person.get("id")
    provider_id = f"espn:athlete:{athlete_id}" if athlete_id is not None else None
    key = (provider_id, resolved_team, str(name).casefold())
    line = by_key.setdefault(
        key,
        EspnEventPlayerLine(
            provider_id=provider_id,
            name=str(name),
            team_provider_id=resolved_team,
            position=person.get("position") if isinstance(person.get("position"), str) else None,
            source_label=source_label,
        ),
    )
    line.goals += goals
    line.assists += assists
    line.yellow_cards += yellow_cards
    line.red_cards += red_cards
    line.last_event_minute = max(line.last_event_minute or 0, minute or 0) or None
    line.fields_seen += int(bool(goals or assists or yellow_cards or red_cards))
    if source_label:
        line.source_label = source_label


def _event_minute(detail: dict[str, Any]) -> int | None:
    clock = detail.get("clock") or {}
    raw = clock.get("displayValue") or detail.get("displayClock") or ""
    match = CLOCK_PATTERN.search(str(raw))
    return int(match.group(1)) if match else None


# Team roster normalizer -------------------------------------------------------------
# A roster is useful even before ESPN publishes a live box score: it lets the Player
# Explorer and Match Center list the actual tournament squad rather than only the two
# people who happened to score or receive a card. These are squad records, not proof
# that a player appeared in a match.

@dataclass
class EspnRosterPlayer:
    provider_id: str | None
    name: str
    team_provider_id: str
    position: str | None = None


def extract_roster_players(payload: dict[str, Any], team_provider_id: str) -> list[EspnRosterPlayer]:
    """Extract athletes from several ESPN roster payload shapes.

    ESPN has used both a flat ``athletes`` array and position-grouped athlete
    collections. We only accept objects that look like a named athlete, and we
    deduplicate by ESPN athlete id/name. Coaches and team metadata are excluded.
    """
    candidates: list[dict[str, Any]] = []

    def walk(value: Any, *, athlete_context: bool = False) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item, athlete_context=athlete_context)
            return
        if not isinstance(value, dict):
            return

        keys = {str(key).casefold() for key in value}
        likely_athlete = athlete_context or "athlete" in keys or ("displayname" in keys and ("position" in keys or "jersey" in keys))
        if likely_athlete:
            nested = value.get("athlete")
            if isinstance(nested, dict):
                merged = {**value, **nested}
                candidates.append(merged)
            elif value.get("displayName") or value.get("fullName") or value.get("shortName"):
                candidates.append(value)

        for key in ("athletes", "roster", "items", "groups", "categories", "positions"):
            child = value.get(key)
            if child is not None:
                walk(child, athlete_context=(key == "athletes" or athlete_context))

    walk(payload)
    by_key: dict[tuple[str | None, str], EspnRosterPlayer] = {}
    for item in candidates:
        name = item.get("displayName") or item.get("fullName") or item.get("shortName")
        if not name:
            continue
        raw_id = item.get("id")
        provider_id = f"espn:athlete:{raw_id}" if raw_id is not None else None
        position = item.get("position")
        if isinstance(position, dict):
            position = position.get("displayName") or position.get("abbreviation") or position.get("name")
        if position is not None and not isinstance(position, str):
            position = None
        key = (provider_id, str(name).casefold())
        by_key[key] = EspnRosterPlayer(
            provider_id=provider_id,
            name=str(name),
            team_provider_id=team_provider_id,
            position=position,
        )
    return list(by_key.values())
