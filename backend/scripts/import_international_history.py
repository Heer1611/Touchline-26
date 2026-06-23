"""Example import point for a licensed/exported historical dataset.

Usage:
    python scripts/import_international_history.py ../../data/international_appearances.csv

The provider feeding live World Cup fixtures and the source feeding full historic
player appearances can be different. Keep the raw CSV outside Git if it is licensed.
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models import InternationalAppearance, Player, Team  # noqa: E402


def main(path: str) -> None:
    with SessionLocal() as session, open(path, newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            team = session.scalar(select(Team).where(Team.name == row["national_team"]))
            if not team:
                team = Team(name=row["national_team"])
                session.add(team)
                session.flush()

            player = session.scalar(
                select(Player).where(Player.name == row["player_name"], Player.national_team_id == team.id)
            )
            if not player:
                player = Player(name=row["player_name"], national_team_id=team.id)
                session.add(player)
                session.flush()

            session.add(
                InternationalAppearance(
                    player_id=player.id,
                    match_date=datetime.fromisoformat(row["match_date"]),
                    opponent_name=row["opponent_name"],
                    competition=row.get("competition") or None,
                    minutes=int(row.get("minutes") or 0),
                    goals=int(row.get("goals") or 0),
                    assists=int(row.get("assists") or 0),
                    xg=float(row["xg"]) if row.get("xg") else None,
                    xa=float(row["xa"]) if row.get("xa") else None,
                    rating=float(row["rating"]) if row.get("rating") else None,
                )
            )
        session.commit()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Pass the CSV path. See data/international_appearances_template.csv")
    main(sys.argv[1])
