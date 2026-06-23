from app.services.espn import event_pulse_rating, extract_2026_event_player_lines


def test_extracts_verified_goal_and_card_events_into_player_stats():
    event = {
        "id": "760456",
        "competitions": [
            {
                "details": [
                    {
                        "type": {"text": "Goal"},
                        "scoringPlay": True,
                        "team": {"id": "202"},
                        "clock": {"displayValue": "38'"},
                        "athletesInvolved": [
                            {"id": "45843", "displayName": "Lionel Messi", "team": {"id": "202"}}
                        ],
                    },
                    {
                        "type": {"text": "Yellow Card"},
                        "yellowCard": True,
                        "team": {"id": "474"},
                        "clock": {"displayValue": "40'"},
                        "athletesInvolved": [
                            {"id": "238906", "displayName": "Stefan Posch", "team": {"id": "474"}}
                        ],
                    },
                ]
            }
        ],
    }

    lines = {line.name: line for line in extract_2026_event_player_lines(event)}

    assert lines["Lionel Messi"].goals == 1
    assert lines["Lionel Messi"].team_provider_id == "espn:team:202"
    assert lines["Stefan Posch"].yellow_cards == 1
    assert event_pulse_rating(lines["Lionel Messi"]) == 7.2



def test_extracts_assist_from_explicit_participant_role():
    event = {
        "id": "760457",
        "competitions": [{"details": [{
            "type": {"text": "Goal"},
            "scoringPlay": True,
            "team": {"id": "202"},
            "clock": {"displayValue": "61'"},
            "participants": [
                {"athlete": {"id": "10", "displayName": "Goal Scorer", "team": {"id": "202"}}, "role": "scorer"},
                {"athlete": {"id": "11", "displayName": "Assist Provider", "team": {"id": "202"}}, "role": "assist"},
            ],
        }]}],
    }

    lines = {line.name: line for line in extract_2026_event_player_lines(event)}
    assert lines["Goal Scorer"].goals == 1
    assert lines["Assist Provider"].assists == 1


def test_extracts_assist_from_named_assisted_by_text_when_no_second_athlete_exists():
    event = {
        "id": "760458",
        "competitions": [{"details": [{
            "type": {"text": "Goal"},
            "scoringPlay": True,
            "team": {"id": "202"},
            "shortText": "Goal Scorer goal, assisted by Text Provider",
            "athletesInvolved": [{"id": "10", "displayName": "Goal Scorer", "team": {"id": "202"}}],
        }]}],
    }

    lines = {line.name: line for line in extract_2026_event_player_lines(event)}
    assert lines["Goal Scorer"].goals == 1
    assert lines["Text Provider"].assists == 1
