from app.services.espn_match_summary import extract_player_lines, pulse_rating_from_available_stats


def test_extracts_boxscore_player_rows_and_derives_local_rating():
    payload = {
        "boxscore": {
            "players": [
                {
                    "team": {"id": "101"},
                    "statistics": [
                        {
                            "names": ["MIN", "G", "A", "Shots", "Passes Completed", "Passes Attempted", "Key Passes"],
                            "athletes": [
                                {
                                    "athlete": {"id": "7", "displayName": "Example Forward", "position": {"abbreviation": "FW"}},
                                    "starter": True,
                                    "stats": [90, 1, 1, 4, 31, 38, 2],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }

    rows = extract_player_lines(payload)

    assert len(rows) == 1
    row = rows[0]
    assert row.provider_id == "espn:athlete:7"
    assert row.team_provider_id == "espn:team:101"
    assert row.minutes == 90
    assert row.goals == 1
    assert row.assists == 1
    assert row.passes_completed == 31
    assert row.passes_attempted == 38
    assert pulse_rating_from_available_stats(row) is not None
