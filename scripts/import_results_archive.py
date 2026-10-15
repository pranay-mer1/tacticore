#!/usr/bin/env python3
"""Import a single historical international match from the user's CSV ZIP."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = Path.home() / "Downloads" / "archive.zip"
OUTPUT = ROOT / "public" / "data" / "historical"
MATCH_FILES = OUTPUT / "matches"
COLORS = ["#69e0c0", "#9b8cff"]
REQUIRED_COLUMNS = {
    "results.csv": {"date", "home_team", "away_team", "home_score", "away_score", "tournament", "city", "country"},
    "goalscorers.csv": {"date", "home_team", "away_team", "team", "scorer", "minute"},
}


class ImportErrorMessage(Exception):
    """An actionable archive-data error."""


def atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_csv_from_zip(archive: zipfile.ZipFile, filename: str) -> list[dict[str, str]]:
    candidates = [
        name for name in archive.namelist()
        if not name.endswith("/") and Path(name).name.casefold() == filename.casefold()
    ]
    if len(candidates) != 1:
        raise ImportErrorMessage(
            f"Expected exactly one {filename} inside the archive; found {len(candidates)}."
        )
    try:
        with archive.open(candidates[0]) as raw:
            content = raw.read().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ImportErrorMessage(f"{filename} is not valid UTF-8 CSV: {error}") from error
    reader = csv.DictReader(content.splitlines())
    columns = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS[filename] - columns
    if missing:
        raise ImportErrorMessage(f"{filename} is missing required columns: {', '.join(sorted(missing))}.")
    return [
        {key: (value or "").strip() for key, value in row.items() if key is not None}
        for row in reader
    ]


def prompt_choice(options: list[Any], title: str, describe: Any) -> Any:
    if not options:
        raise ImportErrorMessage(f"No {title.lower()} are available in the archive.")
    for index, option in enumerate(options, start=1):
        print(f"  {index}. {describe(option)}")
    while True:
        answer = input(f"Choose {title.lower()} [1-{len(options)}]: ").strip()
        try:
            choice = int(answer)
        except ValueError:
            print("Enter one of the numbers shown.")
            continue
        if 1 <= choice <= len(options):
            return options[choice - 1]
        print(f"Choose a number from 1 to {len(options)}.")


def safe_int(value: str, column: str, row_number: int) -> int:
    try:
        number = int(value)
    except (ValueError, TypeError) as error:
        raise ImportErrorMessage(f"Invalid {column} value on results.csv row {row_number}: {value!r}.") from error
    if number < 0:
        raise ImportErrorMessage(f"Negative {column} value on results.csv row {row_number}: {value!r}.")
    return number


def make_match(
    result: dict[str, str],
    scorers: list[dict[str, str]],
    year: str,
    tournament: str,
) -> dict[str, Any]:
    home = result["home_team"]
    away = result["away_team"]
    match_key = {
        "date": result["date"],
        "homeTeam": home,
        "awayTeam": away,
        "tournament": tournament,
    }
    stable_id = hashlib.sha256(
        json.dumps(match_key, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    events: list[dict[str, Any]] = []
    scorer_record_mismatch = False
    scorer_team_counts: Counter[str] = Counter()
    for index, row in enumerate(scorers, start=1):
        team = row["team"]
        scorer = row["scorer"]
        minute_text = row["minute"]
        try:
            minute = int(minute_text.split("+", 1)[0]) if minute_text else 0
        except ValueError:
            minute = 0
        minute = max(0, minute)
        if scorer:
            scorer_team_counts[team] += 1
        events.append({
            "eventId": f"missing-id-archive:{stable_id}:{index}",
            "minute": minute,
            "team": team if team in {home, away} else "",
            "player": scorer,
            "type": "goal",
            "sourceEventType": "Goal scorer record",
            "sourceEventName": "Recorded goal",
            "goalOwnGoal": row.get("own_goal", "").casefold() == "true",
            "goalPenalty": row.get("penalty", "").casefold() == "true",
        })

    home_score = safe_int(result["home_score"], "home_score", 0)
    away_score = safe_int(result["away_score"], "away_score", 0)
    if scorer_team_counts[home] != home_score or scorer_team_counts[away] != away_score:
        scorer_record_mismatch = True

    venue_parts = [part for part in (result.get("city", ""), result.get("country", "")) if part]
    match_date = result["date"]
    try:
        date.fromisoformat(match_date)
        parsed_date = date.fromisoformat(match_date)
        date_label = parsed_date.strftime("%d %b %Y").upper()
    except ValueError:
        date_label = match_date or "Date unavailable"
    return {
        "id": f"results-{stable_id}",
        "date": date_label,
        "competition": tournament,
        "venue": " · ".join(venue_parts) or "Venue unavailable",
        "homeTeam": home or "Unknown home team",
        "awayTeam": away or "Unknown away team",
        "homeCode": "".join(word[0] for word in home.split()[:3]).upper() or "HOM",
        "awayCode": "".join(word[0] for word in away.split()[:3]).upper() or "AWY",
        "homeColor": COLORS[0],
        "awayColor": COLORS[1],
        "source": "user-results-archive",
        "status": "historical",
        "sourceUrl": "",
        "availableMetrics": ["goals"],
        "officialScore": {"home": home_score, "away": away_score},
        "lineups": [],
        "dataQuality": {
            "missingPlayerEvents": sum(not event["player"] for event in events),
            "missingTeamEvents": sum(not event["team"] for event in events),
            "missingSourceEventIds": len(events),
            "passEventsWithoutPassData": 0,
            "shotsWithoutOutcome": 0,
            "unrecognizedShotOutcomes": {},
            "unsupportedEventTypes": {},
            "unavailableMetrics": [
                "Pass counts and passing accuracy",
                "Shot counts and shots on target",
                "Tackle counts",
                "Lineups and non-goal match events",
            ],
            "scorerRecordMismatch": scorer_record_mismatch,
            "scorerRecords": len(events),
        },
        "archiveSeason": year,
        "archiveTournament": tournament,
        "events": events,
    }


def run_import(path: Path) -> Path:
    if not path.is_file():
        raise ImportErrorMessage(
            f"Archive not found: {path}\nPass its path as an argument, for example: "
            'python scripts/import_results_archive.py "C:\\Users\\prana\\Downloads\\archive.zip"'
        )
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise ImportErrorMessage(f"Could not open ZIP archive {path}: {error}") from error

    with archive:
        results = read_csv_from_zip(archive, "results.csv")
        goals = read_csv_from_zip(archive, "goalscorers.csv")
    available_results = [
        row for row in results
        if row.get("date") and row.get("home_team") and row.get("away_team") and row.get("tournament")
    ]
    if not available_results:
        raise ImportErrorMessage("results.csv contains no rows with date, teams, and tournament.")

    tournament_names = sorted({row["tournament"] for row in available_results}, key=str.casefold)
    tournament = prompt_choice(tournament_names, "tournament", lambda item: item)
    year_rows = [
        row for row in available_results
        if row["tournament"] == tournament and len(row["date"]) >= 4
    ]
    years = sorted({row["date"][:4] for row in year_rows}, reverse=True)
    year = prompt_choice(years, "season/year", str)
    matches = sorted(
        [row for row in year_rows if row["date"].startswith(year)],
        key=lambda row: (row["date"], row["home_team"].casefold(), row["away_team"].casefold()),
    )

    def describe(row: dict[str, str]) -> str:
        return f"{row['date']} · {row['home_team']} {row['home_score']}-{row['away_score']} {row['away_team']} · {row.get('city', '')}, {row.get('country', '')}".strip(" ,")

    selected = prompt_choice(matches, "match", describe)
    match_scorers = [
        row for row in goals
        if row.get("date") == selected["date"] and
        row.get("home_team") == selected["home_team"] and
        row.get("away_team") == selected["away_team"]
    ]
    converted = make_match(selected, match_scorers, year, tournament)
    match_path = MATCH_FILES / f"{converted['id']}.json"
    index_path = OUTPUT / "index.json"
    existing: list[dict[str, Any]] = []
    if index_path.is_file():
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ImportErrorMessage(f"Existing historical match index is invalid: {error}") from error
        existing_value = index_data.get("matches", []) if isinstance(index_data, dict) else []
        if not isinstance(existing_value, list):
            raise ImportErrorMessage("Existing historical match index has an invalid matches list.")
        existing = [item for item in existing_value if isinstance(item, dict)]

    atomic_json_write(match_path, converted)
    version = hashlib.sha256(match_path.read_bytes()).hexdigest()[:16]
    existing = [item for item in existing if item.get("id") != converted["id"]]
    existing.append({
        "id": converted["id"],
        "date": converted["date"],
        "competition": converted["competition"],
        "homeTeam": converted["homeTeam"],
        "awayTeam": converted["awayTeam"],
        "file": f"matches/{converted['id']}.json",
        "cacheKey": version,
        "source": converted["source"],
        "status": "historical",
    })
    existing.sort(key=lambda item: str(item.get("date", "")), reverse=True)
    atomic_json_write(index_path, {
        "source": "local-imports",
        "matches": existing,
    })
    quality = converted["dataQuality"]
    print(f"\nImported {converted['homeTeam']} {converted['officialScore']['home']}-{converted['officialScore']['away']} {converted['awayTeam']} ({converted['date']}).")
    print(f"  Match: {match_path.relative_to(ROOT)}")
    print(f"  Local index: {index_path.relative_to(ROOT)}")
    print(f"  Goal-scorer records: {quality['scorerRecords']}")
    if quality["scorerRecordMismatch"]:
        print("  Note: goal-scorer records do not match the listed score; the results.csv score is authoritative.")
    print("  Available metric: listed final score. Passing, shots, tackles, and lineups are not in this archive.")
    print(f"  User-provided archive: {path}")
    return match_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "archive",
        nargs="?",
        type=Path,
        default=DEFAULT_ARCHIVE,
        help=f"Path to the user-provided ZIP (default: {DEFAULT_ARCHIVE})",
    )
    args = parser.parse_args()
    try:
        run_import(args.archive)
    except ImportErrorMessage as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nImport cancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
