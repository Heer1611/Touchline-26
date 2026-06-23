"""Free StatsBomb Open Data importer for historical World Cup match centers.

The project imports only public competitions and labels locally derived ratings as
"Pulse Ratings". It does not present them as official commercial player ratings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

import httpx

from app.config import Settings


@dataclass(frozen=True)
class ImportSummary:
    competitions: int
    matches: int
    appearances: int


class StatsBombOpenDataClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.statsbomb_open_data_base_url.rstrip("/")
        self.timeout = settings.statsbomb_request_timeout_seconds

    def get_json(self, path: str) -> Any:
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            response = client.get(f"{self.base_url}/{path.lstrip('/')}")
            response.raise_for_status()
            return response.json()

    def world_cup_competitions(self) -> list[dict[str, Any]]:
        competitions = self.get_json("competitions.json")
        return [
            item
            for item in competitions
            if item.get("competition_name") == "FIFA World Cup"
            and item.get("competition_gender") == "male"
            and not item.get("competition_youth")
        ]

    def matches(self, competition_id: int, season_id: int) -> list[dict[str, Any]]:
        return self.get_json(f"matches/{competition_id}/{season_id}.json")

    def events(self, match_id: int) -> list[dict[str, Any]]:
        return self.get_json(f"events/{match_id}.json")


def _new_player(
    *, provider_id: int, name: str, position: str | None, national_team_name: str | None
) -> dict[str, Any]:
    return {
        "provider_id": f"statsbomb:{provider_id}",
        "name": name or "Unknown player",
        "position": position,
        "national_team_name": national_team_name,
        "goals": 0,
        "assists": 0,
        "shots": 0,
        "xg": 0.0,
        "passes_completed": 0,
        "passes_attempted": 0,
        "key_passes": 0,
        "tackles_won": 0,
        "interceptions": 0,
        "clearances": 0,
        "saves": 0,
    }


def _pulse_rating(player: dict[str, Any], minutes: int) -> float:
    """A small transparent 0–10 rating for imported event data.

    This is intentionally a portfolio metric, not an Opta/Sofascore/ESPN rating.
    The inputs are all visible in the Match Center so users can understand it.
    """
    involvement = min(minutes, 90) / 90 * 0.45
    passing = 0.0
    attempted = int(player["passes_attempted"])
    if attempted:
        completion = int(player["passes_completed"]) / attempted
        passing = max(-0.12, min(0.28, (completion - 0.68) * 0.75))
    score = (
        5.8
        + involvement
        + int(player["goals"]) * 1.25
        + int(player["assists"]) * 0.78
        + float(player["xg"]) * 0.25
        + int(player["shots"]) * 0.04
        + int(player["key_passes"]) * 0.10
        + int(player["tackles_won"]) * 0.10
        + int(player["interceptions"]) * 0.12
        + int(player["clearances"]) * 0.05
        + int(player["saves"]) * 0.12
        + passing
    )
    return round(max(0.0, min(10.0, score)), 1)


class StatsBombNormalizer:
    @staticmethod
    def normalize_match(raw: dict[str, Any]) -> dict[str, Any]:
        kickoff_time = str(raw.get("kick_off") or "00:00:00").replace("Z", "")
        date_value = raw["match_date"]
        try:
            kickoff = datetime.fromisoformat(f"{date_value}T{kickoff_time}")
        except ValueError:
            kickoff = datetime.fromisoformat(f"{date_value}T00:00:00")
        kickoff = kickoff.replace(tzinfo=UTC)

        home = raw["home_team"]
        away = raw["away_team"]
        competition = raw.get("competition") or {}
        season = raw.get("season") or {}
        stage = raw.get("competition_stage") or {}
        return {
            "provider_id": f"statsbomb:{raw['match_id']}",
            "kickoff_at": kickoff,
            "minute": int(raw.get("match_length") or 90),
            "home_score": raw.get("home_score"),
            "away_score": raw.get("away_score"),
            "stage": (
                f"{competition.get('competition_name', 'FIFA World Cup')} · "
                f"{season.get('season_name', '')} · {stage.get('name', 'Match')}"
            ).strip(" ·"),
            "venue": (raw.get("stadium") or {}).get("name"),
            "home_team": {
                "provider_id": f"statsbomb:team:{home.get('home_team_id')}",
                "name": home["home_team_name"],
                "code": None,
                "logo_url": None,
            },
            "away_team": {
                "provider_id": f"statsbomb:team:{away.get('away_team_id')}",
                "name": away["away_team_name"],
                "code": None,
                "logo_url": None,
            },
            "competition_name": competition.get("competition_name", "FIFA World Cup"),
        }

    @staticmethod
    def appearances(raw_match: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        home_name = raw_match["home_team"]["home_team_name"]
        away_name = raw_match["away_team"]["away_team_name"]
        competition_name = (raw_match.get("competition") or {}).get("competition_name", "FIFA World Cup")

        players: dict[int, dict[str, Any]] = {}
        starters: set[int] = set()
        substitutions_on: dict[int, int] = {}
        substitutions_off: dict[int, int] = {}
        max_minute = int(raw_match.get("match_length") or 90)

        for event in events:
            max_minute = max(max_minute, int(event.get("minute") or 0))
            event_type = (event.get("type") or {}).get("name")
            event_team = (event.get("team") or {}).get("name")

            if event_type == "Starting XI":
                for lineup_player in ((event.get("tactics") or {}).get("lineup") or []):
                    player_data = lineup_player.get("player") or {}
                    player_id = player_data.get("id")
                    if player_id is None:
                        continue
                    starters.add(player_id)
                    players[player_id] = _new_player(
                        provider_id=player_id,
                        name=player_data.get("name", "Unknown player"),
                        position=(lineup_player.get("position") or {}).get("name"),
                        national_team_name=event_team,
                    )

            player_data = event.get("player") or {}
            player_id = player_data.get("id")
            if player_id is not None:
                players.setdefault(
                    player_id,
                    _new_player(
                        provider_id=player_id,
                        name=player_data.get("name", "Unknown player"),
                        position=(event.get("position") or {}).get("name"),
                        national_team_name=event_team,
                    ),
                )

            if event_type == "Substitution" and player_id is not None:
                substitutions_off[player_id] = int(event.get("minute") or 0)
                replacement = (event.get("substitution") or {}).get("replacement") or {}
                replacement_id = replacement.get("id")
                if replacement_id is not None:
                    substitutions_on[replacement_id] = int(event.get("minute") or 0)
                    players.setdefault(
                        replacement_id,
                        _new_player(
                            provider_id=replacement_id,
                            name=replacement.get("name", "Unknown player"),
                            position=None,
                            national_team_name=event_team,
                        ),
                    )

            if player_id is None or player_id not in players:
                continue
            player = players[player_id]

            if event_type == "Shot":
                shot = event.get("shot") or {}
                player["shots"] += 1
                if (shot.get("outcome") or {}).get("name") == "Goal":
                    player["goals"] += 1
                player["xg"] += float(shot.get("statsbomb_xg") or 0.0)

            elif event_type == "Pass":
                passing = event.get("pass") or {}
                player["passes_attempted"] += 1
                if not (passing.get("outcome") or {}).get("name"):
                    player["passes_completed"] += 1
                if passing.get("goal_assist"):
                    player["assists"] += 1
                if passing.get("shot_assist"):
                    player["key_passes"] += 1

            elif event_type == "Interception":
                player["interceptions"] += 1

            elif event_type == "Clearance":
                player["clearances"] += 1

            elif event_type == "Duel":
                duel = event.get("duel") or {}
                if (duel.get("type") or {}).get("name") == "Tackle" and (duel.get("outcome") or {}).get("name") == "Won":
                    player["tackles_won"] += 1

            elif event_type == "Goal Keeper":
                keeper = event.get("goalkeeper") or {}
                if (keeper.get("outcome") or {}).get("name") == "Saved":
                    player["saves"] += 1

        appearances: list[dict[str, Any]] = []
        for player_id, player in players.items():
            started = player_id in starters
            entered_at = substitutions_on.get(player_id)
            left_at = substitutions_off.get(player_id, max_minute)
            if started:
                minutes = max(0, left_at)
            elif entered_at is not None:
                minutes = max(0, max_minute - entered_at)
            else:
                continue

            national_team = player.get("national_team_name")
            if national_team not in {home_name, away_name}:
                continue
            opponent = away_name if national_team == home_name else home_name
            minutes = min(minutes, 130)
            appearances.append(
                {
                    **player,
                    "opponent_name": opponent,
                    "competition": competition_name,
                    "started": started,
                    "minutes": minutes,
                    "xg": round(float(player["xg"]), 3) if player["xg"] else None,
                    "xa": None,
                    "rating": _pulse_rating(player, minutes),
                }
            )
        return appearances


class StatsBombOpenDataImporter:
    def __init__(self, settings: Settings) -> None:
        self.client = StatsBombOpenDataClient(settings)

    def import_world_cup_seasons(self, season_names: Iterable[str], write_match: Any) -> ImportSummary:
        requested = {str(item) for item in season_names}
        competitions = [
            item for item in self.client.world_cup_competitions() if str(item.get("season_name", "")) in requested
        ]
        found = {str(item.get("season_name", "")) for item in competitions}
        missing = requested - found
        if missing:
            raise ValueError(
                "StatsBomb Open Data does not include the requested men's FIFA World Cup season(s): "
                + ", ".join(sorted(missing))
            )
        return self._import_competitions(competitions, write_match)

    def import_world_cup_season(self, season_name: str, write_match: Any) -> ImportSummary:
        return self.import_world_cup_seasons([season_name], write_match)

    def import_recent_world_cups(self, write_match: Any) -> ImportSummary:
        """Import the two most recent completed men's World Cups in the free data set."""
        return self.import_world_cup_seasons(["2018", "2022"], write_match)

    def import_world_cups(self, write_match: Any, max_matches: int | None = None) -> ImportSummary:
        competitions = self.client.world_cup_competitions()
        return self._import_competitions(competitions, write_match, max_matches=max_matches)

    def _import_competitions(
        self, competitions: list[dict[str, Any]], write_match: Any, max_matches: int | None = None
    ) -> ImportSummary:
        matches_imported = 0
        appearances_imported = 0
        for competition in sorted(competitions, key=lambda item: str(item.get("season_name", ""))):
            raw_matches = self.client.matches(competition["competition_id"], competition["season_id"])
            for raw_match in raw_matches:
                if max_matches is not None and matches_imported >= max_matches:
                    return ImportSummary(len(competitions), matches_imported, appearances_imported)
                raw_events = self.client.events(raw_match["match_id"])
                match = StatsBombNormalizer.normalize_match(raw_match)
                appearances = StatsBombNormalizer.appearances(raw_match, raw_events)
                appearances_imported += write_match(match, appearances)
                matches_imported += 1
        return ImportSummary(len(competitions), matches_imported, appearances_imported)
