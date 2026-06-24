"use client";

import { useEffect, useState } from "react";

import {
  getPlayer,
  getPlayers,
  getTeams,
  importRecentWorldCups,
  syncCurrent2026PlayerEvents,
  syncCurrent2026Squads
} from "@/lib/api";
import type { PlayerDetail, PlayerSummary, Team } from "@/types";

function Stat({ label, value }: { label: string; value: string | number }) {
  return <div className="player-stat"><span>{label}</span><strong>{value}</strong></div>;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

function CurrentLine({ player }: { player: PlayerSummary }) {
  const line = player.tournament_2026;
  const hasConfirmedAppearance = line.games_played > 0;
  return (
    <div className={`player-year-line ${hasConfirmedAppearance ? "has-event" : ""}`}>
      <span>2026 file</span>
      {hasConfirmedAppearance ? (
        <strong>{line.games_played} game{line.games_played === 1 ? "" : "s"} played · {line.goals} verified G · {line.assists} A</strong>
      ) : <strong>Named squad profile</strong>}
    </div>
  );
}

export function PlayerExplorer({ onHistoryImported }: { onHistoryImported: () => Promise<void> | void }) {
  const [players, setPlayers] = useState<PlayerSummary[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [selected, setSelected] = useState<PlayerDetail | null>(null);
  const [query, setQuery] = useState("");
  const [team, setTeam] = useState("");
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [syncing2026, setSyncing2026] = useState(false);
  const [syncingSquads, setSyncingSquads] = useState(false);
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadPlayers = async (nextQuery = query, nextTeam = team) => {
    setLoading(true);
    try {
      setPlayers(await getPlayers(nextQuery, nextTeam));
    } catch {
      setMessage("The player index could not load right now.");
    } finally {
      setLoading(false);
    }
  };

  const loadTeams = async () => {
    try { setTeams(await getTeams()); } catch { /* teams will be available after first fixture sync */ }
  };

  useEffect(() => { void Promise.all([loadPlayers("", ""), loadTeams()]); }, []);

  const loadFreeHistory = async () => {
    setImporting(true);
    setMessage("Building the free 2018 + 2022 World Cup archive. Keep this tab open while it imports.");
    try {
      const result = await importRecentWorldCups();
      setMessage(result.message);
      await Promise.all([loadPlayers(), onHistoryImported()]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The historical data could not be imported right now.");
    } finally { setImporting(false); }
  };

  const syncSquads = async () => {
    setSyncingSquads(true);
    setMessage("Loading named 2026 national-team squads. This can take a moment because each team is checked separately.");
    try {
      const result = await syncCurrent2026Squads();
      setMessage(result.message);
      await Promise.all([loadTeams(), loadPlayers(), onHistoryImported()]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The 2026 squad sync could not run right now.");
    } finally { setSyncingSquads(false); }
  };

  const sync2026 = async () => {
    setSyncing2026(true);
    setMessage("Checking every completed or live 2026 World Cup match, including match summaries for named assists and any published player box scores…");
    try {
      const result = await syncCurrent2026PlayerEvents();
      setMessage(result.message);
      await Promise.all([loadPlayers(), onHistoryImported()]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The 2026 player-event refresh could not run right now.");
    } finally { setSyncing2026(false); }
  };

  const openPlayer = async (playerId: number) => {
    setOpeningId(playerId);
    try { setSelected(await getPlayer(playerId)); }
    catch { setMessage("That player file could not be opened right now."); }
    finally { setOpeningId(null); }
  };

  const applySearch = () => { void loadPlayers(); };
  const selectTeam = (nextTeam: string) => { setTeam(nextTeam); void loadPlayers(query, nextTeam); };
  const current = selected?.tournament_2026;
  const selectedRecords = selected?.recent_appearances ?? [];
  const currentYearRecords = selectedRecords.filter((appearance) => new Date(appearance.match_date).getUTCFullYear() === 2026);
  const isPartial2026Record = (appearance: PlayerDetail["recent_appearances"][number]) =>
    appearance.data_source.includes("partial") || appearance.data_source.includes("event");
  const eventOnlyRecords = currentYearRecords.filter(isPartial2026Record);
  const full2026Records = currentYearRecords.filter((appearance) => !isPartial2026Record(appearance));
  const hasOnlyPartial2026Data = eventOnlyRecords.length > 0 && full2026Records.length === 0;

  return (
    <section className="players-section" aria-label="Player explorer">
      <div className="players-heading">
        <div>
          <p className="eyebrow">PLAYER FILES</p>
          <h2>Every squad, not only the scorers.</h2>
          <div className="player-source-note"><strong>How to read this:</strong> a named 2026 goal, assist, or card — or an ESPN-confirmed starting XI spot — counts toward <strong>Games played</strong>. Minutes, shots, xG, passing, and ratings remain pending until ESPN publishes a full player box score.</div>        </div>
        <div className="player-action-row">
          <button className="primary-button" type="button" onClick={() => void syncSquads()} disabled={syncingSquads}>{syncingSquads ? "Loading squads…" : "Load 2026 squads"}</button>
          <button className="secondary-button" type="button" onClick={() => void sync2026()} disabled={syncing2026}>{syncing2026 ? "Syncing tournament…" : "Sync all 2026 data"}</button>
          <button className="quiet-button" type="button" onClick={() => void loadFreeHistory()} disabled={importing}>{importing ? "Building archive…" : "Add 2018 + 2022 history"}</button>
        </div>
      </div>

      <div className="player-controls">
        <label>Find a player<input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") applySearch(); }} placeholder="Search any player" /></label>
        <label>Team roster<select value={team} onChange={(event) => selectTeam(event.target.value)}><option value="">All teams</option>{teams.map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}</select></label>
        <button className="refresh-button player-search-button" type="button" onClick={applySearch} disabled={loading}>{loading ? "Searching…" : "Search"}</button>
      </div>

      {message && <p className="player-message" role="status">{message}</p>}
      {loading ? <div className="player-loading" aria-label="Loading player profiles"><div /><div /><div /></div> : players.length ? <>
        <div className="player-index-head"><span>{team ? `${team} squad` : "Player index"}</span><strong>{players.length} player{players.length === 1 ? "" : "s"} shown</strong></div>
        <div className="player-grid">{players.map((player) => <button className="player-card" type="button" key={player.player_id} onClick={() => void openPlayer(player.player_id)}>
          <div className="player-card-topline"><span>{player.national_team.code ?? player.national_team.name}</span><span>{openingId === player.player_id ? "Opening…" : "Open file ↗"}</span></div>
          <h3>{player.player_name}</h3><p>{player.position ?? "Position pending"}</p>
          <CurrentLine player={player} />
          <div className="player-card-stats">
            <Stat label="2026 games played" value={player.tournament_2026.games_played} />
            <Stat label="Verified 2026 goals" value={player.tournament_2026.goals} />
            <Stat label="Verified assists" value={player.tournament_2026.assists} />
          </div>
        </button>)}</div>
      </> : <div className="empty-state player-empty"><strong>No player files are loaded for that filter yet.</strong><span>Click “Load 2026 squads,” then choose a country to see the full roster.</span></div>}

      {selected && <div className="profile-backdrop" role="presentation" onMouseDown={() => setSelected(null)}><article className="player-profile" role="dialog" aria-modal="true" aria-label={`${selected.player_name} player profile`} onMouseDown={(event) => event.stopPropagation()}>
        <button className="profile-close" type="button" onClick={() => setSelected(null)} aria-label="Close player profile">×</button>
        <p className="eyebrow">{selected.national_team.name.toUpperCase()} · PLAYER FILE</p><h2>{selected.player_name}</h2><p className="player-position">{selected.position ?? "Position pending"}</p>
        <section className="season-file"><div><span>2026 verified events</span><strong>{current?.goals ?? 0}G · {current?.assists ?? 0}A</strong></div><div><span>Games played</span><strong>{current?.games_played ?? currentYearRecords.length}</strong></div><div><span>Complete stat lines</span><strong>{current?.full_stat_lines ?? full2026Records.length}</strong></div></section>
        {hasOnlyPartial2026Data && <div className="verification-note"><strong>What this means:</strong> the 2026 feed has verified the goal/card events for this player, but has not published a full player box score. Minutes, shots, xG, and match rating are intentionally left as pending instead of being guessed.</div>}
        <div className="profile-stat-grid"><Stat label="2026 games played" value={current?.games_played ?? currentYearRecords.length} /><Stat label="Minutes" value={hasOnlyPartial2026Data ? "Pending" : selected.minutes} /><Stat label="Verified 2026 goals" value={current?.goals ?? 0} /><Stat label="Verified 2026 assists" value={current?.assists ?? 0} /><Stat label="xG" value={hasOnlyPartial2026Data ? "Pending" : (selected.xg?.toFixed(2) ?? "—")} /></div>
        <section className="projection-panel"><div><span>Projected minutes</span><strong>{selected.projection.expected_minutes ? selected.projection.expected_minutes.toFixed(0) : "—"}</strong></div><div><span>Score chance</span><strong>{selected.projection.appearances_used ? `${selected.projection.chance_to_score.toFixed(1)}%` : "—"}</strong></div><div><span>Expected Pulse</span><strong>{selected.projection.expected_rating?.toFixed(1) ?? "—"}</strong></div></section>
        <section className="appearance-history"><div className="profile-subheading"><h3>Game record</h3><span>{selected.recent_appearances.length ? "Most recent 12 · event-only rows include verified event data" : "No verified game record yet"}</span></div>
          {selected.recent_appearances.length ? <div className="appearance-table-wrap"><table><thead><tr><th>Date</th><th>Opponent</th><th>Min</th><th>G</th><th>A</th><th>YC</th><th>RC</th><th>Sh</th><th>xG</th><th>Rating</th><th>Source</th></tr></thead><tbody>{selected.recent_appearances.map((appearance, index) => {
      const lineupOnly = appearance.data_source.includes("starting lineup");
      const partial =
        lineupOnly ||
        appearance.data_source.includes("partial") ||
        appearance.data_source.includes("event");
            return <tr key={`${appearance.match_date}-${appearance.opponent_name}-${index}`} className={partial ? "partial-record-row" : ""}><td>{formatDate(appearance.match_date)}</td><td>{appearance.opponent_name}</td><td>{partial ? "Pending" : (appearance.minutes || "—")}</td><td>{appearance.goals}</td><td>{appearance.assists}</td><td>{appearance.yellow_cards}</td><td>{appearance.red_cards}</td><td>{partial ? "Pending" : (appearance.shots || "—")}</td><td>{partial ? "Pending" : (appearance.xg?.toFixed(2) ?? "—")}</td><td>{partial ? "Not published" : (appearance.rating?.toFixed(1) ?? "—")}</td><td><span className="appearance-source">{lineupOnly   ? "2026 lineup"   : partial     ? "2026 event log"     : appearance.data_source.includes("ESPN")       ? "2026 box score"       : "StatsBomb"}</span></td></tr>;
          })}</tbody></table></div> : <div className="profile-empty">This is a synced 2026 squad member. Current player events and full box-score data will appear here once the free feed publishes them.</div>}
        </section>
      </article></div>}
    </section>
  );
}
