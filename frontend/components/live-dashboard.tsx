"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getMatches, getMeta, liveSocketUrl, refreshLiveFixtures } from "@/lib/api";
import type { DashboardMeta, LiveSocketEvent, Match } from "@/types";

import { MatchCard } from "./match-card";
import { MatchCenter } from "./match-center";
import { PlayerExplorer } from "./player-explorer";

const REFRESH_FALLBACK_MS = 5_000;
const LIVE_STATUSES = ["LIVE", "1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT"];
type DeskTab = "desk" | "players" | "archive" | "method";

function sortMatches(matches: Match[]) {
  const rank: Record<string, number> = { LIVE: 0, "1H": 0, HT: 0, "2H": 0, ET: 0, BT: 0, P: 0, SUSP: 0, INT: 0, NS: 1, SCHEDULED: 1, PST: 2, CANC: 2, FT: 3, AET: 3, PEN: 3 };
  return [...matches].sort((left, right) => {
    const byStatus = (rank[left.status] ?? 1) - (rank[right.status] ?? 1);
    if (byStatus) return byStatus;
    const leftTime = new Date(left.kickoff_at).getTime();
    const rightTime = new Date(right.kickoff_at).getTime();
    return ["FT", "AET", "PEN"].includes(left.status) ? rightTime - leftTime : leftTime - rightTime;
  });
}

function MethodPanel() {
  return <section className="method-page">
    <p className="eyebrow">MODEL NOTES</p>
    <h2>A readable score, not a mystery number.</h2>
    <div className="method-grid">
      <article><span>01</span><h3>Current match layer</h3><p>ESPN supplies the schedule, live clock, score, team pulse, and player-linked events where available.</p></article>
      <article><span>02</span><h3>Player history layer</h3><p>StatsBomb Open Data provides detailed 2018 and 2022 World Cup event histories after you import the free archive.</p></article>
      <article><span>03</span><h3>Squad layer</h3><p>Sync 2026 squads to show named players even before they have scored or received a card in the current tournament.</p></article>
      <article><span>04</span><h3>Prediction layer</h3><p>Predictions are local, explainable estimates. They are never displayed as betting odds or official ratings.</p></article>
    </div>
    <div className="method-note"><strong>Data honesty:</strong> an empty stat means the free feed has not published it. Touchline ’26 leaves it blank instead of guessing.</div>
  </section>;
}

export function LiveDashboard() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [meta, setMeta] = useState<DashboardMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [socketState, setSocketState] = useState<"connecting" | "live" | "reconnecting">("connecting");
  const [selectedMatch, setSelectedMatch] = useState<Match | null>(null);
  const [archive, setArchive] = useState<Match[]>([]);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [archiveLimit, setArchiveLimit] = useState(12);
  const [activeTab, setActiveTab] = useState<DeskTab>("desk");
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  const loadDashboard = useCallback(async () => {
    try {
      const [nextMatches, nextMeta] = await Promise.all([getMatches(), getMeta()]);
      setMatches(sortMatches(nextMatches)); setMeta(nextMeta); setNotice(nextMeta.provider_notice);
    } catch { setNotice("The dashboard could not reach the API. Make sure the FastAPI service is running."); }
    finally { setLoading(false); }
  }, []);

  const loadArchive = useCallback(async () => {
    setArchiveLoading(true);
    try {
      const all = await getMatches(true);
      setArchive(all.filter((match) => match.provider_id.startsWith("statsbomb:")).sort((a, b) => new Date(b.kickoff_at).getTime() - new Date(a.kickoff_at).getTime()));
    } catch { setNotice("The historical library could not load yet. Import the free history first."); }
    finally { setArchiveLoading(false); }
  }, []);

  useEffect(() => { void loadDashboard(); const interval = window.setInterval(() => void loadDashboard(), REFRESH_FALLBACK_MS); return () => window.clearInterval(interval); }, [loadDashboard]);

  useEffect(() => {
    let disposed = false;
    const connect = () => {
      if (disposed) return;
      setSocketState(socketRef.current ? "reconnecting" : "connecting");
      const socket = new WebSocket(liveSocketUrl); socketRef.current = socket;
      socket.onopen = () => setSocketState("live");
      socket.onmessage = (event) => { try { const payload = JSON.parse(event.data) as LiveSocketEvent; if (payload.type === "matches.snapshot" || payload.type === "matches.updated") { setMatches(sortMatches(payload.matches)); setNotice(null); } } catch {} };
      socket.onerror = () => socket.close();
      socket.onclose = () => { if (!disposed) { setSocketState("reconnecting"); reconnectTimer.current = setTimeout(connect, 3000); } };
    };
    connect();
    return () => { disposed = true; socketRef.current?.close(); if (reconnectTimer.current) clearTimeout(reconnectTimer.current); };
  }, []);

  const refresh = async () => { setRefreshing(true); try { setMeta(await refreshLiveFixtures()); await loadDashboard(); } catch { setNotice("The live provider could not refresh right now. Try again in a moment."); } finally { setRefreshing(false); } };
  const onHistoryImported = async () => { await Promise.all([loadDashboard(), loadArchive()]); };
  const switchTab = (tab: DeskTab) => { setActiveTab(tab); if (tab === "archive" && !archive.length) void loadArchive(); };

  const liveCount = matches.filter((match) => LIVE_STATUSES.includes(match.status)).length;
  const visibleArchive = archive.slice(0, archiveLimit);
  const tabs: { id: DeskTab; label: string; kicker: string }[] = [
    { id: "desk", label: "Match desk", kicker: "Live fixtures" },
    { id: "players", label: "Player files", kicker: "Squads + stats" },
    { id: "archive", label: "Archive", kicker: "2018 / 2022" },
    { id: "method", label: "Field notes", kicker: "Data + model" }
  ];

  return <main className="site-shell">
    <nav className="topbar" aria-label="Main navigation"><button className="brand brand-button" onClick={() => switchTab("desk")} type="button" aria-label="Touchline 26 home"><span className="brand-mark">T</span><span>Touchline ’26</span></button><span className="issue-stamp">MATCH LEDGER / ISSUE 01</span><div className="connection-inline"><span className={`connection-dot ${socketState === "live" ? "is-live" : ""}`} />{socketState === "live" ? "Feed connected" : "Reconnecting"}</div></nav>

    <section className="hero" id="top"><div><p className="eyebrow">2026 WORLD CUP · LIVE EDITION</p><h1>Read the game<br />as it changes.</h1><p className="hero-copy">Built for fans who want more than just the result.</p></div><div className="hero-scoreboard"><span>LIVE MATCHES</span><strong>{liveCount.toString().padStart(2, "0")}</strong><small>{matches.length} current fixtures in the desk</small></div></section>

    {meta?.demo_mode && <section className="demo-banner"><strong>Demo mode is on.</strong> Set <code>DEMO_MODE=false</code> in <code>.env</code> to use the live ESPN feed.</section>}
    {notice && <p className="notice" role="status">{notice}</p>}

    <section className="ledger-shell">
      <div className="ledger-tabs" role="tablist" aria-label="Touchline sections">{tabs.map((tab) => <button key={tab.id} type="button" role="tab" aria-selected={activeTab === tab.id} className={activeTab === tab.id ? "tab-button is-active" : "tab-button"} onClick={() => switchTab(tab.id)}><span>{tab.kicker}</span>{tab.label}</button>)}</div>
      <div className="ledger-meta"><span>TOURNAMENT LEDGER: {meta?.live_data_source ?? "Connecting"}</span><span>HISTORY: {meta?.historical_data_source ?? "StatsBomb"}</span><span>{meta?.last_provider_sync_at ? `LAST CHECK: ${new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(meta.last_provider_sync_at))}` : "LAST CHECK: waiting"}</span></div>

      <div className="ledger-panel" role="tabpanel">
        {activeTab === "desk" && <section className="desk-page">
          <div className="section-heading"><div><p className="eyebrow">TODAY’S BOARD</p><h2>Match desk</h2><p className="fixture-scope">Live games refresh every 15 seconds. Delayed games that have already started stay in the live section with their score and clock. The desk also keeps next up and results from the past 24 hours.</p></div><button className="refresh-button" onClick={() => void refresh()} type="button" disabled={refreshing}>{refreshing ? "Checking…" : "Check live score now"}</button></div>
          {loading ? <div className="loading-grid" aria-label="Loading matches"><div /><div /><div /></div> : matches.length ? <div className="match-grid">{matches.map((match) => <MatchCard key={match.provider_id} match={match} onOpen={setSelectedMatch} />)}</div> : <div className="empty-state">No fixtures have been imported yet. Use Check updates to recheck the complete tournament schedule and the latest match data.</div>}
        </section>}

        {activeTab === "players" && <PlayerExplorer onHistoryImported={onHistoryImported} />}

        {activeTab === "archive" && <section className="archive-page"><div className="archive-heading"><div><p className="eyebrow">HISTORICAL MATCH LIBRARY</p><h2>World Cup archive</h2><p>Use it to inspect every player who appeared in free 2018 and 2022 StatsBomb matches.</p></div><button className="refresh-button" onClick={() => void loadArchive()} type="button" disabled={archiveLoading}>{archiveLoading ? "Loading…" : "Reload archive"}</button></div>{archiveLoading ? <div className="loading-grid compact"><div /><div /></div> : archive.length ? <><div className="archive-grid">{visibleArchive.map((match) => <MatchCard key={match.provider_id} match={match} onOpen={setSelectedMatch} />)}</div>{archive.length > archiveLimit && <button className="load-more-button" onClick={() => setArchiveLimit((value) => value + 12)} type="button">Show more historical matches ({archive.length - archiveLimit} remaining)</button>}</> : <div className="empty-state archive-empty"><strong>Archive not loaded yet.</strong><span>Go to Player files and use Add 2018 + 2022 history.</span></div>}</section>}

        {activeTab === "method" && <MethodPanel />}
      </div>
    </section>
    {selectedMatch && <MatchCenter match={selectedMatch} onClose={() => setSelectedMatch(null)} />}
  </main>;
}
