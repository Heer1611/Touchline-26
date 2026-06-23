"use client";

import { useEffect, useState } from "react";

import { getMatchDetail } from "@/lib/api";
import type { Match, MatchDetail, MatchPlayerStat, TeamMatchStat } from "@/types";

const LIVE_REFRESH_MS = 5_000;

function Scoreline({ match }: { match: Match }) {
  const hasScore = match.home_score !== null && match.away_score !== null;
  const clock = match.status === "LIVE" || match.status === "HT" ? (match.minute ? `${match.minute}'` : match.status) : null;
  return (
    <div className="match-center-scoreline">
      <span>{match.home_team.name}</span>
      <strong>{hasScore ? `${match.home_score} – ${match.away_score}` : "vs"}</strong>
      <span>{match.away_team.name}</span>
      {clock && <em className="live-clock">{clock}</em>}
    </div>
  );
}

function ActualPlayerTable({ players, teamName }: { players: MatchPlayerStat[]; teamName: string }) {
  const eventOnly = players.some((player) => player.data_status === "event");
  const squadRows = players.filter((player) => player.data_status === "squad").length;
  return (
    <section className="team-stats-section">
      <div className="team-stats-heading">
        <h3>{teamName}</h3>
        <span>{players.length} players · {squadRows ? `${squadRows} named squad profiles` : (eventOnly ? "verified 2026 event stats" : "published match data")}</span>
      </div>
      <div className="match-stats-table-wrap">
        <table className="match-stats-table">
          <thead>
            <tr>
              <th>Player</th><th>Min</th><th>G</th><th>A</th><th>YC</th><th>RC</th><th>Sh</th><th>xG</th><th>Pass</th><th>KP</th><th>Def</th><th>Pulse</th>
            </tr>
          </thead>
          <tbody>
            {players.map((player) => {
              const defensive = player.tackles_won + player.interceptions + player.clearances + player.saves;
              const squadOnly = player.data_status === "squad";
              return (
                <tr key={player.player_id} className={squadOnly ? "squad-row" : ""}>
                  <td>
                    <strong>{player.player_name}</strong>
                    <span>{player.position ?? "Position pending"}{squadOnly ? " · 2026 squad" : (player.started ? " · Starter" : " · Match event")}</span>
                  </td>
                  <td>{squadOnly ? "—" : (player.minutes || "—")}</td>
                  <td>{squadOnly ? "—" : player.goals}</td>
                  <td>{squadOnly ? "—" : player.assists}</td>
                  <td>{squadOnly ? "—" : player.yellow_cards}</td>
                  <td>{squadOnly ? "—" : player.red_cards}</td>
                  <td>{squadOnly ? "—" : (player.shots || "—")}</td>
                  <td>{squadOnly ? "—" : (player.xg?.toFixed(2) ?? "—")}</td>
                  <td>{squadOnly ? "—" : `${player.passes_completed}/${player.passes_attempted}`}</td>
                  <td>{squadOnly ? "—" : player.key_passes}</td>
                  <td>{squadOnly ? "—" : defensive}</td>
                  <td><b className={squadOnly ? "rating-chip is-projected" : "rating-chip"}>{player.pulse_rating?.toFixed(1) ?? "—"}</b></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ProjectedPlayerTable({ players, teamName }: { players: MatchPlayerStat[]; teamName: string }) {
  const backed = players.filter((player) => player.data_status === "predicted" && player.expected_minutes !== null && player.pulse_rating !== null);
  return (
    <section className="team-stats-section">
      <div className="team-stats-heading">
        <h3>{teamName}</h3>
        <span>{backed.length ? `${backed.length} history-linked projections · ${players.length - backed.length} squad profiles` : `${players.length} named squad profiles · projections pending`}</span>
      </div>
      <div className="match-stats-table-wrap">
        <table className="match-stats-table projection-table">
          <thead>
            <tr>
              <th>Player</th><th>Expected min</th><th>Score chance</th><th>Assist chance</th><th>Expected rating</th>
            </tr>
          </thead>
          <tbody>
            {players.map((player) => {
              const hasProjection = player.data_status === "predicted" && player.expected_minutes !== null && player.pulse_rating !== null;
              return (
                <tr key={player.player_id} className={hasProjection ? "" : "squad-row"}>
                  <td>
                    <strong>{player.player_name}</strong>
                    <span>{player.position ?? "Position pending"} · {hasProjection ? "history-linked projection" : "2026 squad profile · history link pending"}</span>
                  </td>
                  <td>{hasProjection ? player.expected_minutes?.toFixed(0) : "—"}</td>
                  <td>{hasProjection ? `${player.chance_to_score?.toFixed(0) ?? "—"}%` : "—"}</td>
                  <td>{hasProjection ? `${player.chance_to_assist?.toFixed(0) ?? "—"}%` : "—"}</td>
                  <td><b className="rating-chip is-projected">{hasProjection ? player.pulse_rating?.toFixed(1) : "—"}</b></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PlayerTables({ detail }: { detail: MatchDetail }) {
  const preMatchRoster = !detail.actual_player_stats_available && (
    detail.projected_players_available ||
    detail.home_players.some((player) => player.data_status === "squad" || player.data_status === "predicted") ||
    detail.away_players.some((player) => player.data_status === "squad" || player.data_status === "predicted")
  );
  const Table = preMatchRoster ? ProjectedPlayerTable : ActualPlayerTable;
  return <><Table teamName={detail.match.home_team.name} players={detail.home_players} /><Table teamName={detail.match.away_team.name} players={detail.away_players} /></>;
}

function TeamStatStrip({ teamStats }: { teamStats: TeamMatchStat[] }) {
  if (!teamStats.length) return null;
  const labels = Array.from(new Set(teamStats.flatMap((team) => Object.keys(team.stats))));
  return (
    <section className="live-team-stat-panel" aria-label="Live team statistics">
      <div className="live-section-title"><span className="live-dot" />Live team pulse <small>updates every 5 seconds while this Match Center is open</small></div>
      <div className="live-team-stat-grid">
        {teamStats.map((team) => (
          <div className="live-team-stat-card" key={team.team_name}>
            <h3>{team.team_name}</h3>
            <dl>
              {labels.map((label) => <div key={label}><dt>{label}</dt><dd>{team.stats[label] ?? "—"}</dd></div>)}
            </dl>
          </div>
        ))}
      </div>
    </section>
  );
}

function LiveEventFeed({ detail }: { detail: MatchDetail }) {
  if (!detail.live_events.length) return <section className="live-event-panel live-event-empty" aria-label="Live match events"><div className="live-section-title"><span className="live-dot" />Live event feed <small>Waiting for the provider’s first match incident.</small></div></section>;
  return (
    <section className="live-event-panel" aria-label="Live match events">
      <div className="live-section-title"><span className="live-dot" />Live event feed <small>{detail.live_events.length} published incidents · scoreboard + match summary</small></div>
      <ol className="live-event-list">
        {detail.live_events.map((event) => (
          <li key={event.event_id} className={`event-kind-${event.kind}`}>
            <span className="event-minute">{event.minute ?? "—"}</span>
            <span className="event-icon" aria-hidden="true">{event.icon}</span>
            <span className="event-copy"><strong>{event.description}</strong><small>{[event.team_name, event.period, event.score ? `score ${event.score}` : null, event.source].filter(Boolean).join(" · ")}</small></span>
            <span className="event-type-chip">{event.type}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function MatchCenter({ match, onClose }: { match: Match; onClose: () => void }) {
  const [detail, setDetail] = useState<MatchDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  useEffect(() => {
    let active = true;
    const loadDetail = async (showLoading = false) => {
      if (showLoading) setDetail(null);
      setIsRefreshing(true);
      try {
        const value = await getMatchDetail(match.provider_id);
        if (active) {
          setDetail(value);
          setError(null);
        }
      } catch {
        if (active && !detail) setError("The Match Center could not load this fixture right now.");
      } finally {
        if (active) setIsRefreshing(false);
      }
    };
    void loadDetail(true);
    const interval = window.setInterval(() => void loadDetail(false), LIVE_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
    // `detail` is intentionally excluded: it should not recreate the timer after a successful poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [match.provider_id]);

  const renderedMatch = detail?.match ?? match;
  const refreshLabel = detail?.refreshed_at ? `Last checked ${new Date(detail.refreshed_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}` : "Checking live data";

  return (
    <div className="profile-backdrop" role="presentation" onMouseDown={onClose}>
      <article className="match-center-modal" role="dialog" aria-modal="true" aria-label="Match Center" onMouseDown={(event) => event.stopPropagation()}>
        <button className="profile-close" type="button" onClick={onClose} aria-label="Close Match Center">×</button>
        <p className="eyebrow">MATCH CENTER</p>
        <Scoreline match={renderedMatch} />
        <p className="match-center-stage">{renderedMatch.stage}</p>
        <div className="match-refresh-status"><span className={isRefreshing ? "spinner-dot" : "live-dot"} />{refreshLabel}</div>

        {!detail && !error && <div className="match-center-loading">Loading the latest score, team numbers, and player-linked match events…</div>}
        {error && <p className="match-center-notice is-error">{error}</p>}
        {detail?.notice && <p className="match-center-notice">{detail.notice}</p>}
        {detail && <>
          <TeamStatStrip teamStats={detail.team_stats} />
          <LiveEventFeed detail={detail} />
        </>}
        {detail && !detail.player_stats_available && <div className="match-center-source"><strong>Updating right now:</strong> score, clock, team statistics, and player-linked goals/cards/substitutions. A complete per-player stat table appears only when ESPN publishes its full box score.</div>}
        {detail?.player_stats_available && <>
          <div className="match-center-source">
            <strong>Source:</strong> {detail.stats_source}. <strong>{detail.rating_label}</strong>
            {detail.actual_player_stats_available ? " is calculated by this project from published fields, not an official provider rating." : " is a projection, not a current-match stat line."}
          </div>
          <PlayerTables detail={detail} />
        </>}
      </article>
    </div>
  );
}
