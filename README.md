# Touchline ’26 — Tournament Ledger

A local, portfolio-focused 2026 World Cup tracker built with **Next.js**, **FastAPI**, and **PostgreSQL**. The interface is a compact tabbed match ledger rather than a long dashboard page.

## What this build fixes

- **Live-window priority:** on startup and during a match, the backend checks the exact current provider date first, with a narrow fallback date window only when needed. That makes a live game appear without waiting for the slower whole-tournament audit.
- **5-second live updates:** while a game is live or near kickoff, the backend refreshes status, score, clock, published incidents, and available team statistics every 5 seconds, then broadcasts the update through WebSockets. The Match Desk rereads the local snapshot every 5 seconds as a fallback.
- **Fast live-score button:** **Check live score now** refreshes the current window immediately; it does not wait for the full schedule/player audit.

- **Complete schedule sync:** the app walks every calendar date from the tournament start through the final date, deduplicates ESPN event IDs, and saves every available fixture locally.
- **Tournament-wide 2026 player backfill:** the **Sync all 2026 data** action checks every completed or live match, not just the match you last opened or today’s fixtures.
- **Two-source event check:** each eligible match is read from both the ESPN scoreboard and its match-summary JSON. Named goals, assists, yellow cards, and red cards are merged before they are saved.
- **No player-specific overrides:** there are no hard-coded Messi, Vinícius, or Jonathan David corrections in this version. Every 2026 total must come from the live provider payload.
- **Honest player records:**
  - **Games played** means there is a verified player event or an actual ESPN box-score row.
  - **Complete stat lines** require a real player box score.
  - Missing minutes, shots, xG, passing, and ratings stay **Pending** instead of being invented.
- **Automatic upgrades:** if ESPN later publishes a fuller player table, the app upgrades the partial player event record with minutes and available stat fields.
- **Tabs and squads:** Match Desk, Player Files, Archive, and Field Notes keep the app compact. Load 2026 squads to see team rosters rather than only scorers.
- **Historical context:** the optional StatsBomb import adds free detailed men’s 2018 and 2022 World Cup match history for player analysis and transparent projections.

## Run locally

1. Extract the ZIP.
2. Open the extracted `touchline26-fast-live-event-stream` folder in VS Code.
3. Run in the VS Code PowerShell terminal:

   ```powershell
   Copy-Item .env.example .env
   docker compose up --build
   ```

4. Open the site:

   ```text
   http://touchline26.localhost:3026
   ```

No payment or API key is required for this version.

## Recommended first actions in the site

1. Go to **Player Files**.
2. Click **Load 2026 squads** to add named national-team roster profiles.
3. Click **Sync all 2026 data** to audit every completed/live tournament match and update verified player event totals.
4. Optionally click **Add 2018 + 2022 history** to build player history and enable data-backed projections where sufficient history exists.

The sync message reports how many tournament fixtures, completed/live matches, summaries, event rows, and full player rows were processed. A missing player box score is a provider limitation, not a zero-stat performance.

## Data boundaries

- ESPN’s public scoreboard and summary JSON are undocumented public endpoints, so they can change and do not guarantee a full player box score for every match. This project uses them for local learning/portfolio work only.
- StatsBomb Open Data covers selected historical tournaments; it is not a database of every senior international match a player has played.
- Touchline’s **Event Pulse** is shown only for verified goal/assist/card events and uses only those event fields. A fuller **Live Pulse** is shown only when a player box score has enough published data. Neither is an official FIFA, Opta, ESPN, or SofaScore rating.

## Project structure

```text
frontend/  Next.js tabbed Match Ledger, Match Center, Player Files
backend/   FastAPI, ESPN adapter, StatsBomb importer, sync/audit logic
postgres/  Fixtures, teams, roster profiles, player events, complete stat lines
```

## Live-game troubleshooting

If a game is already underway but does not appear as **LIVE**, click **Check live score now** on Match Desk. The backend now checks the current rolling date window first and records the provider status exactly as ESPN reports it. The current score/status route is intentionally separate from **Sync all 2026 data**, which is a slower tournament-wide audit used for historical fixtures and player events.

## Reliable sync behavior

The ESPN source can occasionally time out on individual dates or match summaries. The sync is designed to be safe in that case:

- only one schedule/player sync can run at a time, so the background refresh and a button click cannot race each other;
- date requests use lower concurrency and retry temporary network or rate-limit errors;
- successful dates and match summaries are saved even when another request fails;
- the **Sync all 2026 data** button returns an audit message instead of a generic failure banner. It tells you whether any schedule dates, player-event dates, summaries, or local writes need a later retry;
- previously verified fixtures and player events are never cleared because a refresh temporarily fails.

## Sync integrity patch (June 2026)

This release fixes the database error `duplicate key value violates unique constraint uq_player_match_appearance`.

- Every incoming ESPN event fragment is resolved to one local player before any appearance row is written.
- Duplicate scoreboard/summary payloads update the same `player + match` record instead of inserting a second row.
- If ESPN gives the same athlete conflicting team metadata in one match, the app preserves the already-known national-team side and does not create a second appearance.
- A single bad duplicate can no longer prevent later tournament matches from syncing.


## Fast Live Feed

- Match Desk checks the live ESPN scoreboard every **5 seconds** while a fixture is live or near kickoff.
- An open Match Center combines ESPN scoreboard incidents with the match-summary feed, so it can surface goals, named assists, cards, substitutions, penalties, VAR decisions, injuries/delays, period notices, and extra team statistics when ESPN publishes them.
- The summary response is cached for 8 seconds, and connections are reused, so the faster display does not blindly multiply provider requests.
- The feed is still limited to provider-published data; unavailable player box-score fields remain pending.
