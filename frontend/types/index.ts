export type MatchStatus = "SCHEDULED" | "LIVE" | "1H" | "HT" | "2H" | "FT" | string;

export type Team = {
  id: number;
  name: string;
  code: string | null;
  logo_url: string | null;
};

export type Prediction = {
  home_win: number;
  draw: number;
  away_win: number;
  home_strength: number;
  away_strength: number;
  summary: string;
};

export type Match = {
  provider_id: string;
  kickoff_at: string;
  status: MatchStatus;
  minute: number | null;
  home_score: number | null;
  away_score: number | null;
  stage: string;
  venue: string | null;
  home_team: Team;
  away_team: Team;
  prediction: Prediction;
};

export type MatchPlayerStat = {
  player_id: number;
  player_name: string;
  position: string | null;
  started: boolean;
  minutes: number;
  goals: number;
  assists: number;
  shots: number;
  xg: number | null;
  passes_completed: number;
  passes_attempted: number;
  key_passes: number;
  tackles_won: number;
  interceptions: number;
  clearances: number;
  saves: number;
  yellow_cards: number;
  red_cards: number;
  pulse_rating: number | null;
  data_status: "historical" | "current" | "predicted" | "event" | "squad" | string;
  rating_label: string;
  expected_minutes: number | null;
  chance_to_score: number | null;
  chance_to_assist: number | null;
};

export type TeamMatchStat = {
  team_name: string;
  team_code: string | null;
  stats: Record<string, string>;
};

export type MatchEvent = {
  event_id: string;
  minute: string | null;
  type: string;
  description: string;
  team_name: string | null;
  player_name: string | null;
  assist_name: string | null;
  icon: string;
  kind: string;
  score: string | null;
  period: string | null;
  source: string;
};

export type MatchDetail = {
  match: Match;
  player_stats_available: boolean;
  actual_player_stats_available: boolean;
  projected_players_available: boolean;
  stats_source: string;
  rating_label: string;
  notice: string | null;
  home_players: MatchPlayerStat[];
  away_players: MatchPlayerStat[];
  live_events: MatchEvent[];
  team_stats: TeamMatchStat[];
  live_event_data_available: boolean;
  refreshed_at: string | null;
};

export type DashboardMeta = {
  demo_mode: boolean;
  poll_seconds: number;
  live_data_source: string;
  historical_data_source: string;
  api_requests_used_today: number | null;
  api_requests_remaining_today: number | null;
  last_provider_sync_at: string | null;
  provider_notice: string | null;
};

export type PlayerProjection = {
  player_id: number;
  player_name: string;
  appearances_used: number;
  expected_minutes: number;
  chance_to_score: number;
  chance_to_assist: number;
  expected_rating: number | null;
};

export type TournamentLine = {
  /** Complete match-stat lines only — event-only rows do not count as appearances. */
  appearances: number;
  /** Confirmed games played: an event or full box score proves the player participated. */
  games_played: number;
  full_stat_lines: number;
  event_linked_matches: number;
  minutes: number;
  /** Verified named goal/assist/card totals from the 2026 event feed. */
  goals: number;
  assists: number;
  yellow_cards: number;
  red_cards: number;
};

export type PlayerSummary = {
  player_id: number;
  player_name: string;
  position: string | null;
  national_team: Team;
  appearances: number;
  minutes: number;
  goals: number;
  assists: number;
  xg: number | null;
  last_appearance_at: string | null;
  tournament_2026: TournamentLine;
  projection: PlayerProjection;
};

export type PlayerAppearance = {
  match_date: string;
  opponent_name: string;
  competition: string | null;
  minutes: number;
  goals: number;
  assists: number;
  shots: number;
  xg: number | null;
  xa: number | null;
  rating: number | null;
  yellow_cards: number;
  red_cards: number;
  data_source: string;
  rating_label: string;
};

export type PlayerDetail = PlayerSummary & {
  recent_appearances: PlayerAppearance[];
};

export type HistoryImport = {
  source: string;
  season: string;
  matches_imported: number;
  player_appearances_imported: number;
  message: string;
};

export type LiveSocketEvent = {
  type: "matches.snapshot" | "matches.updated";
  sentAt?: string;
  matches: Match[];
};
