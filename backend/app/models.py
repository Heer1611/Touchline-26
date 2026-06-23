from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[str | None] = mapped_column(String(80), unique=True, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fifa_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    home_matches: Mapped[list[Match]] = relationship(
        back_populates="home_team", foreign_keys="Match.home_team_id"
    )
    away_matches: Mapped[list[Match]] = relationship(
        back_populates="away_team", foreign_keys="Match.away_team_id"
    )
    players: Mapped[list[Player]] = relationship(back_populates="national_team")


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="SCHEDULED", index=True)
    minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str] = mapped_column(String(120), default="Group Stage")
    venue: Mapped[str | None] = mapped_column(String(180), nullable=True)
    home_win_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    draw_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_win_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    home_team: Mapped[Team] = relationship(back_populates="home_matches", foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(back_populates="away_matches", foreign_keys=[away_team_id])
    appearances: Mapped[list[InternationalAppearance]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[str | None] = mapped_column(String(80), unique=True, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    position: Mapped[str | None] = mapped_column(String(60), nullable=True)
    national_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)

    national_team: Mapped[Team] = relationship(back_populates="players")
    appearances: Mapped[list[InternationalAppearance]] = relationship(back_populates="player")


class InternationalAppearance(Base):
    """One row per player per imported national-team match.

    The match-level metrics below are derived from the free StatsBomb event stream.
    They are deliberately separate from any commercial/offical player-rating product.
    """

    __tablename__ = "international_appearances"
    __table_args__ = (UniqueConstraint("player_id", "match_id", name="uq_player_match_appearance"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"), nullable=True, index=True)
    match_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    opponent_name: Mapped[str] = mapped_column(String(120))
    competition: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started: Mapped[bool] = mapped_column(Boolean, default=False)
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    goals: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    shots: Mapped[int] = mapped_column(Integer, default=0)
    xg: Mapped[float | None] = mapped_column(Float, nullable=True)
    xa: Mapped[float | None] = mapped_column(Float, nullable=True)
    passes_completed: Mapped[int] = mapped_column(Integer, default=0)
    passes_attempted: Mapped[int] = mapped_column(Integer, default=0)
    key_passes: Mapped[int] = mapped_column(Integer, default=0)
    tackles_won: Mapped[int] = mapped_column(Integer, default=0)
    interceptions: Mapped[int] = mapped_column(Integer, default=0)
    clearances: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    yellow_cards: Mapped[int] = mapped_column(Integer, default=0)
    red_cards: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_source: Mapped[str] = mapped_column(String(80), default="StatsBomb Open Data")
    rating_kind: Mapped[str] = mapped_column(String(40), default="historical_pulse")

    player: Mapped[Player] = relationship(back_populates="appearances")
    match: Mapped[Match | None] = relationship(back_populates="appearances")


class ProviderUsage(Base):
    """Reserved for future providers that enforce a request budget."""

    __tablename__ = "provider_usage"
    __table_args__ = (UniqueConstraint("provider", "usage_date", name="uq_provider_usage_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(60), index=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
