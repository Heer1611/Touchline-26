from app.services.statsbomb_open_data import StatsBombNormalizer


def test_normalizer_creates_event_stats_and_a_transparent_rating() -> None:
    raw_match = {
        "match_id": 100,
        "match_date": "2022-12-18",
        "kick_off": "16:00:00.000",
        "home_team": {"home_team_id": 1, "home_team_name": "Argentina"},
        "away_team": {"away_team_id": 2, "away_team_name": "France"},
        "home_score": 3,
        "away_score": 3,
        "competition": {"competition_name": "FIFA World Cup"},
        "season": {"season_name": "2022"},
        "competition_stage": {"name": "Final"},
    }
    events = [
        {
            "type": {"name": "Starting XI"}, "team": {"name": "Argentina"},
            "tactics": {"lineup": [
                {"player": {"id": 10, "name": "Lionel Messi"}, "position": {"name": "Center Forward"}},
                {"player": {"id": 11, "name": "Julian Alvarez"}, "position": {"name": "Center Forward"}},
            ]},
        },
        {
            "type": {"name": "Starting XI"}, "team": {"name": "France"},
            "tactics": {"lineup": [
                {"player": {"id": 7, "name": "Kylian Mbappe"}, "position": {"name": "Left Wing"}},
            ]},
        },
        {
            "type": {"name": "Pass"}, "team": {"name": "Argentina"},
            "player": {"id": 10, "name": "Lionel Messi"}, "minute": 22,
            "pass": {"goal_assist": True, "shot_assist": True},
        },
        {
            "type": {"name": "Shot"}, "team": {"name": "Argentina"},
            "player": {"id": 11, "name": "Julian Alvarez"}, "minute": 23,
            "shot": {"outcome": {"name": "Goal"}, "statsbomb_xg": 0.42},
        },
        {
            "type": {"name": "Interception"}, "team": {"name": "Argentina"},
            "player": {"id": 10, "name": "Lionel Messi"}, "minute": 31,
        },
        {
            "type": {"name": "Substitution"}, "team": {"name": "France"},
            "player": {"id": 7, "name": "Kylian Mbappe"}, "minute": 70,
            "substitution": {"replacement": {"id": 17, "name": "Substitute Player"}},
        },
        {
            "type": {"name": "Shot"}, "team": {"name": "France"},
            "player": {"id": 17, "name": "Substitute Player"}, "minute": 90,
            "shot": {"outcome": {"name": "Goal"}, "statsbomb_xg": 0.18},
        },
    ]

    appearances = StatsBombNormalizer.appearances(raw_match, events)
    by_name = {appearance["name"]: appearance for appearance in appearances}

    assert by_name["Lionel Messi"]["minutes"] == 90
    assert by_name["Lionel Messi"]["assists"] == 1
    assert by_name["Lionel Messi"]["key_passes"] == 1
    assert by_name["Lionel Messi"]["passes_completed"] == 1
    assert by_name["Lionel Messi"]["interceptions"] == 1
    assert by_name["Julian Alvarez"]["goals"] == 1
    assert by_name["Julian Alvarez"]["shots"] == 1
    assert by_name["Julian Alvarez"]["xg"] == 0.42
    assert by_name["Kylian Mbappe"]["minutes"] == 70
    assert by_name["Substitute Player"]["minutes"] == 20
    assert by_name["Substitute Player"]["opponent_name"] == "Argentina"
    assert 0 <= by_name["Julian Alvarez"]["rating"] <= 10
