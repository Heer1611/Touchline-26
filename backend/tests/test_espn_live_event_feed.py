from app.services.espn import extract_live_event_feed


def test_extracts_current_soccer_events_and_team_stats():
    event = {
        "id": "760456",
        "competitions": [
            {
                "competitors": [
                    {
                        "team": {"id": "202", "displayName": "Argentina", "abbreviation": "ARG"},
                        "statistics": [
                            {"name": "possessionPct", "displayValue": "60.2"},
                            {"name": "totalShots", "displayValue": "3"},
                        ],
                    },
                    {
                        "team": {"id": "474", "displayName": "Austria", "abbreviation": "AUT"},
                        "statistics": [
                            {"name": "possessionPct", "displayValue": "39.8"},
                            {"name": "totalShots", "displayValue": "2"},
                        ],
                    },
                ],
                "details": [
                    {
                        "type": {"text": "Goal"},
                        "clock": {"displayValue": "38'"},
                        "team": {"id": "202"},
                        "athletesInvolved": [{"displayName": "Lionel Messi"}],
                    },
                    {
                        "type": {"text": "Yellow Card"},
                        "clock": {"displayValue": "40'"},
                        "team": {"id": "474"},
                        "athletesInvolved": [{"displayName": "Stefan Posch"}],
                    },
                ],
            }
        ],
    }

    events, stats = extract_live_event_feed(event)

    assert [item["player_name"] for item in events] == ["Stefan Posch", "Lionel Messi"]
    assert events[1]["icon"] == "⚽"
    assert stats[0]["stats"] == {"Possession": "60.2", "Shots": "3"}
