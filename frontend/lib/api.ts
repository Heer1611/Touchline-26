import type {
  DashboardMeta,
  HistoryImport,
  Match,
  MatchDetail,
  PlayerDetail,
  PlayerSummary
} from "@/types";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
export const liveSocketUrl = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/live";

async function readJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getMatches(includeHistory = false): Promise<Match[]> {
  return readJson<Match[]>(includeHistory ? "/matches?history=true" : "/matches");
}

export function getMatchDetail(providerId: string): Promise<MatchDetail> {
  return readJson<MatchDetail>(`/matches/${encodeURIComponent(providerId)}/detail`);
}

export function getMeta(): Promise<DashboardMeta> {
  return readJson<DashboardMeta>("/meta");
}

export async function refreshLiveFixtures(): Promise<DashboardMeta> {
  const response = await fetch(`${apiBaseUrl}/refresh`, { method: "POST" });
  if (!response.ok) throw new Error(`Refresh failed with status ${response.status}`);
  return response.json() as Promise<DashboardMeta>;
}

export function getPlayers(search = "", team = ""): Promise<PlayerSummary[]> {
  const params = new URLSearchParams({ limit: team ? "80" : "160" });
  if (search.trim()) params.set("q", search.trim());
  if (team.trim()) params.set("team", team.trim());
  return readJson<PlayerSummary[]>(`/players?${params.toString()}`);
}

export function getPlayer(playerId: number): Promise<PlayerDetail> {
  return readJson<PlayerDetail>(`/players/${playerId}`);
}

export function getTeams(): Promise<import("@/types").Team[]> {
  return readJson<import("@/types").Team[]>("/teams");
}

export async function importRecentWorldCups(): Promise<HistoryImport> {
  const response = await fetch(`${apiBaseUrl}/history/statsbomb/recent-world-cups`, { method: "POST" });
  if (!response.ok) {
    let detail = "The historical data could not be imported right now.";
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = payload.detail || detail;
    } catch {
      // Preserve the clear fallback when a provider returns non-JSON output.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<HistoryImport>;
}


export async function syncCurrent2026PlayerEvents(): Promise<HistoryImport> {
  const response = await fetch(`${apiBaseUrl}/players/2026/sync-events`, { method: "POST" });
  if (!response.ok) {
    let detail = "The 2026 player-event refresh could not run right now.";
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = payload.detail || detail;
    } catch {
      // Preserve the clear fallback if the provider returns non-JSON output.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<HistoryImport>;
}

export async function syncCurrent2026Squads(): Promise<HistoryImport> {
  const response = await fetch(`${apiBaseUrl}/players/2026/sync-squads`, { method: "POST" });
  if (!response.ok) {
    let detail = "The 2026 squad sync could not run right now.";
    try { detail = ((await response.json()) as { detail?: string }).detail || detail; } catch {}
    throw new Error(detail);
  }
  return response.json() as Promise<HistoryImport>;
}
