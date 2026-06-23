from app.services.espn import extract_roster_players


def test_extract_roster_players_supports_flat_and_grouped_payloads():
    payload = {
        "athletes": [
            {"id": "11", "displayName": "Ada Forward", "position": {"displayName": "Forward"}},
            {"id": "22", "displayName": "Bea Keeper", "position": {"abbreviation": "GK"}},
        ],
        "groups": [
            {"athletes": [{"athlete": {"id": "11", "displayName": "Ada Forward"}, "position": {"displayName": "Forward"}}]}
        ],
    }
    players = extract_roster_players(payload, "espn:team:55")
    assert [(item.provider_id, item.name, item.team_provider_id) for item in players] == [
        ("espn:athlete:11", "Ada Forward", "espn:team:55"),
        ("espn:athlete:22", "Bea Keeper", "espn:team:55"),
    ]
