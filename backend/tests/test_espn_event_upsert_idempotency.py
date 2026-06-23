from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import InternationalAppearance, Match, Team
from app.repository import upsert_espn_event_appearances
from app.services.espn import EspnEventPlayerLine, merge_event_player_lines


def _session_with_match() -> tuple[Session, Match]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, autoflush=False)
    home = Team(provider_id="espn:team:home", name="Home")
    away = Team(provider_id="espn:team:away", name="Away")
    session.add_all([home, away])
    session.flush()
    match = Match(
        provider_id="espn:fixture:1",
        home_team_id=home.id,
        away_team_id=away.id,
        kickoff_at=datetime(2026, 6, 22, tzinfo=UTC),
        status="FINAL",
        stage="Group Stage",
    )
    session.add(match)
    session.commit()
    return session, match


def test_merge_prefers_athlete_identity_even_when_payloads_disagree_about_team():
    home = EspnEventPlayerLine(
        provider_id="espn:athlete:10",
        name="Example Player",
        team_provider_id="espn:team:home",
        goals=1,
        fields_seen=1,
    )
    conflicting_copy = EspnEventPlayerLine(
        provider_id="espn:athlete:10",
        name="Example Player",
        team_provider_id="espn:team:away",
        assists=1,
        fields_seen=1,
    )

    lines = merge_event_player_lines([home], [conflicting_copy])

    assert len(lines) == 1
    assert lines[0].goals == 1
    assert lines[0].assists == 1
    assert lines[0].team_provider_id == "espn:team:home"


def test_event_upsert_does_not_create_duplicate_player_match_rows_when_feed_repeats_athlete():
    session, match = _session_with_match()
    try:
        lines = [
            EspnEventPlayerLine(
                provider_id="espn:athlete:10",
                name="Example Player",
                team_provider_id="espn:team:home",
                goals=1,
                fields_seen=1,
            ),
            # Same athlete repeated by a conflicting event payload. This is the
            # failure pattern reported by the user log.
            EspnEventPlayerLine(
                provider_id="espn:athlete:10",
                name="Example Player",
                team_provider_id="espn:team:away",
                assists=1,
                fields_seen=1,
            ),
        ]

        upsert_espn_event_appearances(session, match.provider_id, lines)
        upsert_espn_event_appearances(session, match.provider_id, lines)

        rows = session.scalars(select(InternationalAppearance)).all()
        assert len(rows) == 1
        assert rows[0].goals == 1
        assert rows[0].assists == 1
        assert rows[0].opponent_name == "Away"
    finally:
        session.close()
