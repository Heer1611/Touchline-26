from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

from app.config import Settings
from app.database import SessionLocal
from app.repository import (
    delete_live_provider_fixtures,
    list_matches,
    upsert_espn_event_appearances,
    upsert_espn_match_appearances,
    upsert_matches,
    seconds_until_espn_poll,
)
from app.services.demo_data import demo_fixtures
from app.services.espn import (
    EspnFetchAudit,
    EspnScoreboardClient,
    extract_2026_event_player_lines,
    merge_event_player_lines,
)
from app.services.espn_match_summary import extract_player_lines
from app.websocket_manager import ConnectionManager

logger = logging.getLogger(__name__)

LIVE_OR_FINAL_STATUSES = {"LIVE", "HT", "P", "SUSP", "FT", "AET", "PEN"}


@dataclass(frozen=True)
class TournamentSyncReport:
    """Transparent result of a full 2026 World Cup sync.

    The report distinguishes a full provider outage from a partial sync.  A partial
    sync still saves successful dates and player events, which is safer than
    discarding data simply because one public ESPN response timed out.
    """

    fixtures_seen: int = 0
    completed_seen: int = 0
    summaries_checked: int = 0
    summaries_with_player_boxscore: int = 0
    verified_event_rows_written: int = 0
    full_player_rows_written: int = 0
    schedule_days_attempted: int = 0
    schedule_days_succeeded: int = 0
    schedule_days_failed: int = 0
    player_days_attempted: int = 0
    player_days_succeeded: int = 0
    player_days_failed: int = 0
    summary_failures: int = 0
    write_failures: int = 0
    provider_error: str | None = None

    @property
    def is_partial(self) -> bool:
        return bool(
            self.provider_error
            or self.schedule_days_failed
            or self.player_days_failed
            or self.summary_failures
            or self.write_failures
        )

    @property
    def warning(self) -> str | None:
        if self.provider_error:
            return self.provider_error
        fragments: list[str] = []
        if self.schedule_days_failed:
            fragments.append(f"{self.schedule_days_failed} schedule date feed(s)")
        if self.player_days_failed:
            fragments.append(f"{self.player_days_failed} player-event date feed(s)")
        if self.summary_failures:
            fragments.append(f"{self.summary_failures} match summary feed(s)")
        if self.write_failures:
            fragments.append(f"{self.write_failures} local write(s)")
        if not fragments:
            return None
        return "Partial ESPN refresh: " + ", ".join(fragments) + " could not be completed; successful data was saved."


class LiveSyncService:
    """Keeps the Match Ledger current using ESPN's public World Cup feed.

    The free source is undocumented, so the service intentionally favors integrity:
    retries for temporary failures, a single sync queue to avoid conflicting writes,
    partial-result persistence, and clear audit reporting instead of fabricated data.
    """

    def __init__(self, settings: Settings, connections: ConnectionManager) -> None:
        self.settings = settings
        self.connections = connections
        self.provider = EspnScoreboardClient(settings)
        self.last_provider_sync_at: datetime | None = None
        self.last_schedule_sync_at: datetime | None = None
        self.last_provider_error: str | None = None
        self.last_event_backfill_at: datetime | None = None
        self.last_report = TournamentSyncReport()
        self._old_provider_records_cleaned = False
        # Startup, background polling, Match Desk refresh, and the Player Files
        # button can all trigger syncs. Serializing them prevents duplicate rows and
        # database race conditions while one full tournament pass is running.
        self._sync_lock = asyncio.Lock()

    async def sync_once(self, force_full_fixture_refresh: bool = False) -> bool:
        async with self._sync_lock:
            return await self._sync(
                force_schedule=force_full_fixture_refresh,
                force_completed_backfill=False,
            )

    async def sync_entire_tournament(self) -> TournamentSyncReport:
        """Refresh the complete fixture ledger and all eligible player events.

        It returns an audit even if ESPN is partially unavailable.  The UI can then
        explain exactly what happened instead of showing a generic failure banner.
        """
        async with self._sync_lock:
            await self._sync(force_schedule=True, force_completed_backfill=True)
            return self.last_report

    async def sync_live_window(self) -> bool:
        """Refresh only the rolling live-score window around *now*.

        This is intentionally separate from the complete tournament audit. A live
        match must reach the dashboard in seconds even while an optional archive
        sweep is slow or a historical ESPN date temporarily fails.
        """
        async with self._sync_lock:
            if self.settings.demo_mode:
                return await self._sync(force_schedule=False, force_completed_backfill=False)

            now = datetime.now(UTC)
            try:
                raw_events = await self.provider.fetch_live_window_events(now)
                rows = self._normalizable(raw_events)
                fixtures = [normalized for _, normalized in rows]
                fixture_changed = await asyncio.to_thread(self._write_fixtures, fixtures)

                # Store only verified goal/assist/card event rows here. Complete
                # player box scores remain the responsibility of the on-demand
                # Match Center and the full tournament audit.
                eligible = [
                    (raw, normalized, None)
                    for raw, normalized in rows
                    if str(normalized.get("status") or "") in LIVE_OR_FINAL_STATUSES
                    and isinstance(normalized.get("kickoff_at"), datetime)
                    and normalized["kickoff_at"] <= now
                ]
                event_report, player_changed = await asyncio.to_thread(
                    self._write_player_data,
                    eligible,
                    len(fixtures),
                    len(eligible),
                    0,
                )
                self.last_provider_sync_at = now
                self.last_provider_error = None
                self.last_report = TournamentSyncReport(
                    fixtures_seen=len(fixtures),
                    completed_seen=len(eligible),
                    verified_event_rows_written=event_report.verified_event_rows_written,
                    full_player_rows_written=0,
                )
                return fixture_changed or player_changed
            except Exception as exc:
                logger.info("ESPN live-window refresh failed", exc_info=True)
                self.last_provider_error = (
                    f"Live window could not refresh ({type(exc).__name__}). Existing verified data was kept."
                )
                self.last_report = TournamentSyncReport(provider_error=self.last_provider_error)
                return False

    def _full_sync_due(self) -> bool:
        """Whether the slower schedule/event audit is due in the background."""
        now = datetime.now(UTC)
        return (
            self.last_schedule_sync_at is None
            or self.last_event_backfill_at is None
            or (now - self.last_schedule_sync_at).total_seconds() >= self.settings.espn_schedule_refresh_seconds
            or (now - self.last_event_backfill_at).total_seconds() >= self.settings.espn_event_backfill_refresh_seconds
        )

    async def _sync(self, *, force_schedule: bool, force_completed_backfill: bool) -> bool:
        if self.settings.demo_mode:
            fixtures = demo_fixtures()
            changed = await asyncio.to_thread(self._write_demo_fixtures, fixtures)
            self.last_provider_sync_at = datetime.now(UTC)
            self.last_provider_error = None
            self.last_report = TournamentSyncReport(fixtures_seen=len(fixtures))
            return changed

        if not self._old_provider_records_cleaned:
            removed = await asyncio.to_thread(self._delete_old_provider_fixtures)
            if removed:
                logger.info("Removed %s stale demo/API-Football fixture(s).", removed)
            self._old_provider_records_cleaned = True

        now = datetime.now(UTC)
        tournament_start = date.fromisoformat(self.settings.espn_tournament_start_date)
        tournament_end = date.fromisoformat(self.settings.espn_tournament_end_date)
        through_date = min(now.date(), tournament_end)
        schedule_due = (
            force_schedule
            or self.last_schedule_sync_at is None
            or (now - self.last_schedule_sync_at).total_seconds()
            >= self.settings.espn_schedule_refresh_seconds
        )
        backfill_due = (
            force_completed_backfill
            or self.last_event_backfill_at is None
            or (now - self.last_event_backfill_at).total_seconds()
            >= self.settings.espn_event_backfill_refresh_seconds
        )

        try:
            if schedule_due:
                schedule_raw, schedule_audit = await self.provider.fetch_tournament_events_with_audit(
                    tournament_start, tournament_end
                )
                self.last_schedule_sync_at = now
            else:
                schedule_raw, schedule_audit = await self.provider.fetch_tournament_events_with_audit(
                    now.date(), now.date()
                )

            if backfill_due:
                player_raw, player_audit = await self.provider.fetch_tournament_events_with_audit(
                    tournament_start, through_date
                )
                self.last_event_backfill_at = now
            else:
                player_raw, player_audit = await self.provider.fetch_tournament_events_with_audit(
                    now.date(), now.date()
                )

            schedule = self._normalizable(schedule_raw)
            player_matches = self._normalizable(player_raw)
            report, changed = await self._write_full_sync(
                schedule,
                player_matches,
                now,
                schedule_audit,
                player_audit,
            )
            self.last_report = report
            self.last_provider_sync_at = now
            self.last_provider_error = report.warning
            return changed
        except Exception as exc:
            # Keep previously synchronized records visible. The action returns a
            # detailed audit instead of raising a 502 after a temporary provider
            # outage, which is particularly important for a free public endpoint.
            detail = f"ESPN could not complete this refresh ({type(exc).__name__}). Existing verified data was kept."
            logger.exception("ESPN tournament sync failed")
            self.last_provider_error = detail
            self.last_report = TournamentSyncReport(provider_error=detail)
            return False

    def _normalizable(self, raw_events: list[dict]) -> list[tuple[dict, dict]]:
        rows: list[tuple[dict, dict]] = []
        seen: set[str] = set()
        for raw in raw_events:
            try:
                normalized = self.provider.normalize_event(raw)
            except (KeyError, TypeError, ValueError):
                continue
            provider_id = str(normalized["provider_id"])
            if provider_id in seen:
                continue
            seen.add(provider_id)
            rows.append((raw, normalized))
        return rows

    async def _write_full_sync(
        self,
        schedule: list[tuple[dict, dict]],
        player_matches: list[tuple[dict, dict]],
        now: datetime,
        schedule_audit: EspnFetchAudit,
        player_audit: EspnFetchAudit,
    ) -> tuple[TournamentSyncReport, bool]:
        fixtures = [normalized for _, normalized in schedule]
        try:
            fixture_changed = await asyncio.to_thread(self._write_fixtures, fixtures)
        except Exception as exc:
            logger.exception("Could not save ESPN fixtures")
            report = TournamentSyncReport(
                fixtures_seen=len(schedule),
                schedule_days_attempted=schedule_audit.days_attempted,
                schedule_days_succeeded=schedule_audit.days_succeeded,
                schedule_days_failed=schedule_audit.days_failed,
                player_days_attempted=player_audit.days_attempted,
                player_days_succeeded=player_audit.days_succeeded,
                player_days_failed=player_audit.days_failed,
                provider_error=f"Fixtures were received but could not be saved ({type(exc).__name__}). Existing verified data was kept.",
            )
            return report, False

        eligible: list[tuple[dict, dict]] = []
        for raw, normalized in player_matches:
            status = str(normalized.get("status") or "")
            kickoff = normalized.get("kickoff_at")
            if status in LIVE_OR_FINAL_STATUSES and isinstance(kickoff, datetime) and kickoff <= now:
                eligible.append((raw, normalized))

        bundles, summary_failures = await self._fetch_match_summaries(eligible)
        report, player_changed = await asyncio.to_thread(
            self._write_player_data,
            bundles,
            len(schedule),
            len(eligible),
            summary_failures,
        )
        report = replace(
            report,
            schedule_days_attempted=schedule_audit.days_attempted,
            schedule_days_succeeded=schedule_audit.days_succeeded,
            schedule_days_failed=schedule_audit.days_failed,
            player_days_attempted=player_audit.days_attempted,
            player_days_succeeded=player_audit.days_succeeded,
            player_days_failed=player_audit.days_failed,
        )
        return report, fixture_changed or player_changed

    async def _fetch_match_summaries(
        self, rows: list[tuple[dict, dict]]
    ) -> tuple[list[tuple[dict, dict, dict | None]], int]:
        semaphore = asyncio.Semaphore(max(1, self.settings.espn_summary_concurrency))

        async def one(raw: dict, normalized: dict) -> tuple[dict, dict, dict | None, bool]:
            event_id = raw.get("id")
            if event_id is None:
                return raw, normalized, None, False
            async with semaphore:
                try:
                    return raw, normalized, await self.provider.fetch_match_summary(str(event_id)), False
                except Exception:
                    # The scoreboard event remains valid evidence even if the
                    # optional summary endpoint is temporarily unavailable.
                    logger.info("ESPN summary unavailable for %s", event_id, exc_info=True)
                    return raw, normalized, None, True

        results = await asyncio.gather(*(one(raw, normalized) for raw, normalized in rows))
        bundles = [(raw, normalized, summary) for raw, normalized, summary, _ in results]
        failures = sum(1 for *_, failed in results if failed)
        return bundles, failures

    @staticmethod
    def _write_demo_fixtures(fixtures: list[dict]) -> bool:
        with SessionLocal() as session:
            return upsert_matches(session, fixtures)

    @staticmethod
    def _write_fixtures(fixtures: list[dict]) -> bool:
        with SessionLocal() as session:
            return upsert_matches(session, fixtures)

    @staticmethod
    def _write_player_data(
        bundles: list[tuple[dict, dict, dict | None]],
        fixtures_seen: int,
        completed_seen: int,
        summary_failures: int,
    ) -> tuple[TournamentSyncReport, bool]:
        event_rows_written = 0
        full_rows_written = 0
        summary_count = 0
        summaries_with_boxscore = 0
        write_failures = 0
        with SessionLocal() as session:
            for raw, normalized, summary in bundles:
                try:
                    provider_id = str(normalized["provider_id"])
                    score_lines = extract_2026_event_player_lines(raw)
                    summary_lines = extract_2026_event_player_lines(summary) if summary else []
                    event_rows_written += upsert_espn_event_appearances(
                        session,
                        provider_id,
                        merge_event_player_lines(score_lines, summary_lines),
                    )
                    if summary is not None:
                        summary_count += 1
                        full_lines = extract_player_lines(summary)
                        if full_lines:
                            summaries_with_boxscore += 1
                            full_rows_written += upsert_espn_match_appearances(session, provider_id, full_lines)
                except Exception:
                    # One malformed ESPN player payload should not prevent every
                    # other completed tournament game from being saved.
                    session.rollback()
                    write_failures += 1
                    logger.exception("Could not save player data for %s", normalized.get("provider_id"))

        report = TournamentSyncReport(
            fixtures_seen=fixtures_seen,
            completed_seen=completed_seen,
            summaries_checked=summary_count,
            summaries_with_player_boxscore=summaries_with_boxscore,
            verified_event_rows_written=event_rows_written,
            full_player_rows_written=full_rows_written,
            summary_failures=summary_failures,
            write_failures=write_failures,
        )
        return report, bool(event_rows_written or full_rows_written)

    @staticmethod
    def _delete_old_provider_fixtures() -> int:
        with SessionLocal() as session:
            return delete_live_provider_fixtures(session)

    @staticmethod
    def snapshot() -> list[dict]:
        with SessionLocal() as session:
            return [match.model_dump(mode="json") for match in list_matches(session)]

    def next_poll_seconds(self) -> int:
        if self.settings.demo_mode:
            return 30
        with SessionLocal() as session:
            return seconds_until_espn_poll(
                session,
                live_poll_seconds=self.settings.espn_live_poll_seconds,
                idle_poll_seconds=self.settings.espn_idle_poll_seconds,
            )

    async def publish_snapshot(self, event_type: str = "matches.updated") -> None:
        await self.connections.broadcast(
            {
                "type": event_type,
                "sentAt": datetime.now(UTC).isoformat(),
                "matches": await asyncio.to_thread(self.snapshot),
            }
        )

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                # Always update the compact current-date window first. This is the
                # path that drives the live label, score, and minute in Match Desk.
                changed = await self.sync_live_window()
                if self._full_sync_due():
                    changed = (await self.sync_once()) or changed
                if changed:
                    await self.publish_snapshot()
            except Exception:
                # The normal sync path already captures provider errors. This final
                # guard only protects the background task from an unexpected bug.
                logger.exception("Unexpected background sync failure")

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.next_poll_seconds())
            except TimeoutError:
                continue
