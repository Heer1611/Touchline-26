from app.services.espn import extract_live_event_feed


def test_merges_scoreboard_and_summary_incidents_with_extra_context():
    event = {
        "id": "fixture-1",
        "competitions": [{
            "competitors": [
                {"team": {"id": "1", "displayName": "Alpha", "abbreviation": "ALP"}, "statistics": [{"name": "possessionPct", "displayValue": "56"}, {"name": "shotsOnTarget", "displayValue": "4"}]},
                {"team": {"id": "2", "displayName": "Beta", "abbreviation": "BET"}, "statistics": [{"name": "possessionPct", "displayValue": "44"}, {"name": "offsides", "displayValue": "2"}]},
            ],
            "details": [{"id": "g1", "type": {"text": "Goal"}, "scoringPlay": True, "clock": {"displayValue": "18'"}, "team": {"id": "1"}, "athletesInvolved": [{"displayName": "Forward One"}], "homeScore": "1", "awayScore": "0"}],
        }],
    }
    summary = {
        "plays": [
            {"id": "g1", "type": {"text": "Goal"}, "scoringPlay": True, "clock": {"displayValue": "18'"}, "team": {"id": "1"}, "shortText": "Forward One scores (assist: Creator Two)", "athletesInvolved": [{"displayName": "Forward One", "role": "scorer"}, {"displayName": "Creator Two", "role": "assist"}], "homeScore": "1", "awayScore": "0"},
            {"id": "sub1", "type": {"text": "Substitution"}, "clock": {"displayValue": "63'"}, "team": {"id": "2"}, "shortText": "Beta makes a substitution"},
            {"id": "var1", "type": {"text": "VAR Review"}, "clock": {"displayValue": "72'"}, "team": {"id": "1"}, "shortText": "VAR review in progress"},
        ]
    }

    feed, stats = extract_live_event_feed(event, summary)

    assert len(feed) == 3
    assert feed[0]["kind"] == "var"
    goal = next(row for row in feed if row["kind"] == "goal")
    assert goal["assist_name"] == "Creator Two"
    assert goal["score"] == "1–0"
    assert goal["source"] == "match summary"
    assert stats[0]["stats"]["Possession"] == "56"
    assert stats[0]["stats"]["On target"] == "4"
