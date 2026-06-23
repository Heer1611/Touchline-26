"""Load free StatsBomb Open Data into PostgreSQL.

Examples:
    python scripts/import_statsbomb_open_data.py --recent-world-cups
    python scripts/import_statsbomb_open_data.py --world-cups --max-matches 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.repository import upsert_statsbomb_match_with_appearances  # noqa: E402
from app.services.statsbomb_open_data import StatsBombOpenDataImporter  # noqa: E402


def write_match(match_data: dict, appearances: list[dict]) -> int:
    with SessionLocal() as session:
        return upsert_statsbomb_match_with_appearances(session, match_data, appearances)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import free StatsBomb Open Data World Cup history.")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--recent-world-cups", action="store_true", help="Import the free 2018 and 2022 men's World Cups.")
    scope.add_argument("--world-cups", action="store_true", help="Import every available men's FIFA World Cup season.")
    parser.add_argument("--max-matches", type=int, default=None, help="Stop after this many matches for a small test run.")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    importer = StatsBombOpenDataImporter(get_settings())
    if args.recent_world_cups:
        summary = importer.import_recent_world_cups(write_match)
        label = "2018 + 2022"
    else:
        summary = importer.import_world_cups(write_match, max_matches=args.max_matches)
        label = "all available seasons"
    print(
        f"Imported {summary.matches} StatsBomb matches ({label}) across {summary.competitions} competition entries "
        f"with {summary.appearances} player appearances."
    )


if __name__ == "__main__":
    main()
