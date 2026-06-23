from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "World Cup Pulse API"
    database_url: str = "postgresql+psycopg://worldcup:worldcup@localhost:5432/worldcup"
    cors_origins: str = "http://touchline26.localhost:3026"

    # Demo mode is optional. When false, the app uses ESPN's public scoreboard feed
    # without an API key. The feed is suitable for personal/portfolio use only.
    demo_mode: bool = False

    # ESPN public scoreboard feed. This endpoint is undocumented and may change,
    # so the app deliberately keeps the provider isolated in its own adapter.
    espn_scoreboard_url: str = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
    espn_summary_url: str = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"
    espn_tournament_start_date: str = "2026-06-11"
    espn_tournament_end_date: str = "2026-07-19"
    # Fast live cadence for Match Desk while a match is active or near kickoff.
    espn_live_poll_seconds: int = 5
    # Keep the local Match Desk fresh during the tournament. The backend only
    # asks ESPN for a small rolling date window, not the entire schedule, on
    # this cadence.
    # Keep the quiet dashboard light, but refresh fixtures often enough to catch a changed kickoff.
    espn_idle_poll_seconds: int = 45
    espn_schedule_refresh_seconds: int = 7200
    # Tournament-to-date player-event backfill. A single scoreboard range request
    # catches earlier completed matches after the app starts, rather than only today.
    espn_event_backfill_refresh_seconds: int = 900
    espn_request_timeout_seconds: int = 15
    # Match Center can poll the scoreboard every five seconds. Summary responses are
    # cached briefly so ESPN is not hit twice for the same static box-score payload.
    espn_summary_cache_seconds: int = 8
    # Keep manual tournament backfills friendly to an undocumented public feed.
    # Lower concurrency plus retries is more reliable than opening dozens of
    # parallel short-lived connections.
    espn_scoreboard_concurrency: int = 3
    espn_summary_concurrency: int = 2
    espn_http_retries: int = 3
    espn_retry_delay_seconds: float = 0.8

    # StatsBomb Open Data is public historical tournament data. It does not claim to
    # cover every senior international match ever played.
    statsbomb_open_data_base_url: str = (
        "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
    )
    statsbomb_request_timeout_seconds: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
