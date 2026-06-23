from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str | None = None
    logo_url: str | None = None


class PredictionOut(BaseModel):
    home_win: float = Field(ge=0, le=100)
    draw: float = Field(ge=0, le=100)
    away_win: float = Field(ge=0, le=100)
    home_strength: float
    away_strength: float
    summary: str


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider_id: str
    kickoff_at: datetime
    status: str
    minute: int | None = None
    home_score: int | None = None
    away_score: int | None = None
    stage: str
    venue: str | None = None
    home_team: TeamOut
    away_team: TeamOut
    prediction: PredictionOut


class MatchPlayerStatOut(BaseModel):
    player_id: int
    player_name: str
    position: str | None = None
    started: bool
    minutes: int
    goals: int
    assists: int
    shots: int
    xg: float | None = None
    passes_completed: int
    passes_attempted: int
    key_passes: int
    tackles_won: int
    interceptions: int
    clearances: int
    saves: int
    yellow_cards: int = 0
    red_cards: int = 0
    pulse_rating: float | None = Field(default=None, ge=0, le=10)
    data_status: str = "historical"
    rating_label: str = "Pulse Rating"
    expected_minutes: float | None = None
    chance_to_score: float | None = Field(default=None, ge=0, le=100)
    chance_to_assist: float | None = Field(default=None, ge=0, le=100)


class TeamMatchStatOut(BaseModel):
    team_name: str
    team_code: str | None = None
    stats: dict[str, str]


class MatchEventOut(BaseModel):
    event_id: str
    minute: str | None = None
    type: str
    description: str
    team_name: str | None = None
    player_name: str | None = None
    assist_name: str | None = None
    icon: str = "•"
    # Extra context is shown only when ESPN publishes it.
    kind: str = "other"
    score: str | None = None
    period: str | None = None
    source: str = "scoreboard"


class MatchDetailOut(BaseModel):
    match: MatchOut
    player_stats_available: bool
    actual_player_stats_available: bool = False
    projected_players_available: bool = False
    stats_source: str
    rating_label: str
    notice: str | None = None
    home_players: list[MatchPlayerStatOut]
    away_players: list[MatchPlayerStatOut]
    live_events: list[MatchEventOut] = []
    team_stats: list[TeamMatchStatOut] = []
    live_event_data_available: bool = False
    refreshed_at: datetime | None = None


class MetaOut(BaseModel):
    demo_mode: bool
    poll_seconds: int
    live_data_source: str
    historical_data_source: str
    api_requests_used_today: int | None = None
    api_requests_remaining_today: int | None = None
    last_provider_sync_at: datetime | None = None
    provider_notice: str | None = None


class PlayerProjectionOut(BaseModel):
    player_id: int
    player_name: str
    appearances_used: int
    expected_minutes: float
    chance_to_score: float
    chance_to_assist: float
    expected_rating: float | None


class TournamentLineOut(BaseModel):
    """2026 tournament line with partial-event data kept separate from full box scores."""

    # ``appearances`` means a complete match-stat line, never merely a goal/card event.
    appearances: int = 0
    # Confirmed 2026 appearances: full box-score rows plus event-linked rows.
    games_played: int = 0
    full_stat_lines: int = 0
    event_linked_matches: int = 0
    minutes: int = 0
    # Goals/assists/cards are verified event totals when ESPN names the player.
    goals: int = 0
    assists: int = 0
    yellow_cards: int = 0
    red_cards: int = 0


class PlayerSummaryOut(BaseModel):
    player_id: int
    player_name: str
    position: str | None = None
    national_team: TeamOut
    appearances: int
    minutes: int
    goals: int
    assists: int
    xg: float | None = None
    last_appearance_at: datetime | None = None
    tournament_2026: TournamentLineOut
    projection: PlayerProjectionOut


class PlayerAppearanceOut(BaseModel):
    match_date: datetime
    opponent_name: str
    competition: str | None = None
    minutes: int
    goals: int
    assists: int
    shots: int
    xg: float | None = None
    xa: float | None = None
    rating: float | None = None
    yellow_cards: int = 0
    red_cards: int = 0
    data_source: str = "StatsBomb Open Data"
    rating_label: str = "Pulse Rating"


class PlayerDetailOut(PlayerSummaryOut):
    recent_appearances: list[PlayerAppearanceOut]


class HistoryImportOut(BaseModel):
    source: str
    season: str
    matches_imported: int
    player_appearances_imported: int
    message: str
