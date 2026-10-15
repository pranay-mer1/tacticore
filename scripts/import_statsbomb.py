#!/usr/bin/env python3
"""Interactively import one StatsBomb Open Data match into Tacticore."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
REPOSITORY_URL = "https://github.com/hudl/open-data"
CACHE = ROOT / ".cache" / "statsbomb"
OUTPUT = ROOT / "public" / "data" / "historical"
MATCH_FILES = OUTPUT / "matches"
COLORS = ["#69e0c0", "#9b8cff", "#f3a95e", "#70a5ff", "#e47c98", "#d3bd78"]


class ImportErrorMessage(Exception):
    """An actionable import or repository-data error."""


def atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def fetch_json(url: str, cache_path: Path, refresh: bool) -> Any:
    if cache_path.is_file() and not refresh:
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ImportErrorMessage(f"Cached JSON is invalid: {cache_path} ({error})") from error

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Tacticore-local-importer/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise ImportErrorMessage(f"StatsBomb returned HTTP {error.code} for {url}") from error
    except urllib.error.URLError as error:
        raise ImportErrorMessage(f"Could not download {url}: {error.reason}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ImportErrorMessage(f"StatsBomb returned invalid JSON for {url}: {error}") from error
    atomic_json_write(cache_path, value)
    return value


def name_of(value: Any, fallback: str = "") -> str:
    if isinstance(value, dict):
        for field in (
            "name",
            "home_team_name",
            "away_team_name",
            "team_name",
            "competition_name",
            "season_name",
            "stadium_name",
        ):
            name = value.get(field)
            if isinstance(name, str) and name.strip():
                return name.strip()
        return fallback
    return value.strip() if isinstance(value, str) else fallback


def integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def team_code(name: str) -> str:
    words = name.split()
    if len(words) > 1:
        return "".join(word[0] for word in words[:3]).upper()
    return name[:3].upper()


def lineup_teams(raw_lineups: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_lineups, list):
        return []
    result: list[dict[str, Any]] = []
    for raw_team in raw_lineups:
        if not isinstance(raw_team, dict):
            continue
        team = name_of(raw_team.get("team_name"), "Unknown team")
        raw_players = raw_team.get("lineup")
        players = []
        if isinstance(raw_players, list):
            for item in raw_players:
                if not isinstance(item, dict):
                    continue
                player = item.get("player")
                player_name = name_of(player) if isinstance(player, dict) else ""
                if not player_name and isinstance(item.get("player_name"), str):
                    player_name = item["player_name"].strip()
                if player_name:
                    players.append(player_name)
        result.append({"team": team, "players": players})
    return result


def convert_match(metadata: dict[str, Any], raw_events: Any, raw_lineups: Any) -> dict[str, Any]:
    if not isinstance(raw_events, list):
        raise ImportErrorMessage("The selected match event file is not a JSON array.")

    home = name_of(metadata.get("home_team"), "Unknown home team")
    away = name_of(metadata.get("away_team"), "Unknown away team")
    unsupported: Counter[str] = Counter()
    missing_players = 0
    missing_teams = 0
    missing_event_ids = 0
    pass_without_data = 0
    shot_without_outcome = 0
    unrecognized_shot_outcomes: Counter[str] = Counter()
    converted_events: list[dict[str, Any]] = []

    for raw in raw_events:
        if not isinstance(raw, dict):
            continue
        event_type = name_of(raw.get("type"), "Unknown")
        event_id = raw.get("id")
        if not isinstance(event_id, str) or not event_id:
            missing_event_ids += 1
            event_id = f"missing-id-{len(converted_events) + 1}"
        team = name_of(raw.get("team")) or name_of(raw.get("possession_team"))
        if not team:
            missing_teams += 1
            team = "Unknown team"
        player = name_of(raw.get("player"))
        if not player:
            missing_players += 1

        event: dict[str, Any] = {
            "eventId": event_id,
            "minute": integer(raw.get("minute")) or 0,
            "second": integer(raw.get("second")) or 0,
            "team": team,
            "player": player,
            "type": "other",
            "sourceEventType": event_type,
            "sourceEventName": event_type,
        }

        if event_type == "Pass":
            pass_data = raw.get("pass")
            event["type"] = "pass"
            if isinstance(pass_data, dict):
                outcome = name_of(pass_data.get("outcome"))
                event["passOutcome"] = outcome or None
                event["completed"] = not outcome
            else:
                event["passOutcome"] = None
                event["completed"] = None
                pass_without_data += 1
        elif event_type == "Shot":
            shot_data = raw.get("shot")
            event["type"] = "shot"
            outcome = name_of(shot_data.get("outcome")) if isinstance(shot_data, dict) else ""
            event["outcome"] = outcome or None
            if not outcome:
                event["onTarget"] = None
                shot_without_outcome += 1
            elif outcome.casefold() in {"goal", "saved", "saved to post"}:
                event["onTarget"] = True
            elif outcome.casefold() in {"off t", "wayward", "post", "blocked", "saved off target"}:
                event["onTarget"] = False
            else:
                event["onTarget"] = None
                unrecognized_shot_outcomes[outcome] += 1
        elif event_type == "Duel":
            duel = raw.get("duel")
            duel_type = name_of(duel.get("type")) if isinstance(duel, dict) else ""
            if duel_type == "Tackle":
                event["type"] = "tackle"
                event["sourceEventName"] = "Tackle"
                outcome = name_of(duel.get("outcome")) if isinstance(duel, dict) else ""
                event["successful"] = outcome.casefold().startswith("won") if outcome else None
            else:
                unsupported[event_type + (f": {duel_type}" if duel_type else "")] += 1
        else:
            unsupported[event_type] += 1

        converted_events.append(event)

    home_score = integer(metadata.get("home_score"))
    away_score = integer(metadata.get("away_score"))
    event_home_score = sum(
        event["type"] == "shot" and (event.get("outcome") or "").casefold() == "goal" and event["team"] == home
        for event in converted_events
    )
    event_away_score = sum(
        event["type"] == "shot" and (event.get("outcome") or "").casefold() == "goal" and event["team"] == away
        for event in converted_events
    )
    colors = {home: COLORS[0], away: COLORS[1]}
    match_id = metadata.get("match_id")
    if match_id is None:
        raise ImportErrorMessage("The selected match has no match_id.")
    competition = name_of(metadata.get("competition"), "StatsBomb Open Data")
    season = name_of(metadata.get("season"), "")
    match_date = metadata.get("match_date")

    return {
        "id": str(match_id),
        "date": match_date if isinstance(match_date, str) else "Date unavailable",
        "competition": f"{competition}{f' · {season}' if season else ''}",
        "venue": name_of(metadata.get("stadium"), "Historical match"),
        "homeTeam": home,
        "awayTeam": away,
        "homeCode": team_code(home),
        "awayCode": team_code(away),
        "homeColor": colors[home],
        "awayColor": colors[away],
        "source": "statsbomb-open-data",
        "status": "historical",
        "sourceUrl": REPOSITORY_URL,
        "officialScore": {"home": home_score, "away": away_score},
        "lineups": lineup_teams(raw_lineups),
        "dataQuality": {
            "missingPlayerEvents": missing_players,
            "missingTeamEvents": missing_teams,
            "missingSourceEventIds": missing_event_ids,
            "passEventsWithoutPassData": pass_without_data,
            "shotsWithoutOutcome": shot_without_outcome,
            "unrecognizedShotOutcomes": dict(sorted(unrecognized_shot_outcomes.items())),
            "unsupportedEventTypes": dict(sorted(unsupported.items())),
            "officialScoreMismatch": (
                home_score is not None and away_score is not None and
                (home_score != event_home_score or away_score != event_away_score)
            ),
            "unavailableMetrics": [
                "Expected goals (xG) are not calculated.",
                "Possession percentages are not calculated.",
                "Tackles count StatsBomb Duel events with subtype Tackle only.",
                "Shots without a recognized outcome are excluded from shots-on-target totals.",
                "Passes without a pass payload are excluded from passing-accuracy denominators.",
            ],
        },
        "events": converted_events,
    }


def choose(options: list[Any], label: str, describe: Any) -> Any:
    if not options:
        raise ImportErrorMessage(f"No {label.lower()} are available.")
    for index, option in enumerate(options, start=1):
        print(f"  {index}. {describe(option)}")
    while True:
        answer = input(f"Choose {label.lower()} [1-{len(options)}]: ").strip()
        try:
            choice = int(answer)
        except ValueError:
            print("Enter the number shown beside your choice.")
            continue
        if 1 <= choice <= len(options):
            return options[choice - 1]
        print(f"Choose a number from 1 to {len(options)}.")


def run_import(refresh: bool = False) -> Path:
    print("StatsBomb Open Data — local historical match importer")
    competitions = fetch_json(
        f"{RAW_BASE}/competitions.json",
        CACHE / "competitions.json",
        refresh,
    )
    if not isinstance(competitions, list):
        raise ImportErrorMessage("competitions.json is not a JSON array.")

    grouped: dict[tuple[Any, str, str], list[dict[str, Any]]] = {}
    for row in competitions:
        if not isinstance(row, dict):
            continue
        name = name_of(row.get("competition_name"), "Unnamed competition")
        country = name_of(row.get("country_name"), "")
        key = (row.get("competition_id"), name, country)
        grouped.setdefault(key, []).append(row)
    competition_keys = sorted(grouped, key=lambda item: (item[1].casefold(), item[2].casefold()))
    selected_competition = choose(
        competition_keys,
        "competition",
        lambda item: f"{item[1]}{f' — {item[2]}' if item[2] else ''}",
    )
    seasons = sorted(
        grouped[selected_competition],
        key=lambda row: name_of(row.get("season_name")).casefold(),
    )
    season = choose(seasons, "season", lambda row: name_of(row.get("season_name"), "Unnamed season"))

    competition_id = integer(season.get("competition_id"))
    season_id = integer(season.get("season_id"))
    if competition_id is None or season_id is None:
        raise ImportErrorMessage("The selected competition or season has an invalid ID.")
    matches = fetch_json(
        f"{RAW_BASE}/matches/{competition_id}/{season_id}.json",
        CACHE / "matches" / f"{competition_id}_{season_id}.json",
        refresh,
    )
    if not isinstance(matches, list) or not matches:
        raise ImportErrorMessage("No matches were found for this competition and season.")

    def describe_match(item: dict[str, Any]) -> str:
        date = item.get("match_date") or "date unavailable"
        home = name_of(item.get("home_team"), "Unknown home team")
        away = name_of(item.get("away_team"), "Unknown away team")
        score = ""
        if integer(item.get("home_score")) is not None and integer(item.get("away_score")) is not None:
            score = f" — {item['home_score']}-{item['away_score']}"
        return f"{date} · {home} vs {away}{score}"

    competition_name = name_of(season.get("competition_name"), "StatsBomb Open Data")
    season_name = name_of(season.get("season_name"))
    for item in matches:
        if isinstance(item, dict):
            item["competition"] = competition_name
            item["season"] = season_name
    selected = choose(
        [item for item in matches if isinstance(item, dict)],
        "match",
        describe_match,
    )
    match_id = integer(selected.get("match_id"))
    if match_id is None:
        raise ImportErrorMessage("The selected match has an invalid match_id.")

    match_path = MATCH_FILES / f"{match_id}.json"
    index_path = OUTPUT / "index.json"
    existing_index: dict[str, Any] = {"matches": []}
    if index_path.is_file():
        try:
            existing_index = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ImportErrorMessage(f"Imported-match index is invalid: {error}") from error
    existing_matches = existing_index.get("matches", [])
    if not isinstance(existing_matches, list):
        raise ImportErrorMessage("Imported-match index has an invalid matches list.")
    already_imported = any(
        isinstance(item, dict) and str(item.get("id")) == str(match_id)
        for item in existing_matches
    )
    if already_imported and match_path.is_file() and not refresh:
        print(f"\nMatch {match_id} is already imported and cached locally:")
        print(f"  {match_path.relative_to(ROOT)}")
        if input("Replace it using cached/downloaded source files? [y/N]: ").strip().lower() not in {"y", "yes"}:
            return match_path

    events = fetch_json(
        f"{RAW_BASE}/events/{match_id}.json",
        CACHE / "events" / f"{match_id}.json",
        refresh,
    )
    lineups = fetch_json(
        f"{RAW_BASE}/lineups/{match_id}.json",
        CACHE / "lineups" / f"{match_id}.json",
        refresh,
    )
    converted = convert_match(selected, events, lineups)
    atomic_json_write(match_path, converted)
    cache_key = hashlib.sha256(
        json.dumps(converted, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    summary = {
        "id": str(match_id),
        "date": converted["date"],
        "competition": converted["competition"],
        "homeTeam": converted["homeTeam"],
        "awayTeam": converted["awayTeam"],
        "file": f"matches/{match_id}.json",
        "cacheKey": cache_key,
        "status": "historical",
        "source": converted["source"],
    }
    kept = [
        item
        for item in existing_matches
        if isinstance(item, dict) and str(item.get("id")) != str(match_id)
    ]
    kept.append(summary)
    kept.sort(key=lambda item: str(item.get("date", "")), reverse=True)
    atomic_json_write(index_path, {"source": converted["source"], "matches": kept})

    quality = converted["dataQuality"]
    print(f"\nImported {converted['homeTeam']} vs {converted['awayTeam']} ({converted['date']}).")
    print(f"  Match data: {match_path.relative_to(ROOT)}")
    print(f"  Local match index: {index_path.relative_to(ROOT)}")
    print(f"  Events: {len(converted['events'])}; lineup teams: {len(converted['lineups'])}")
    print(f"  Original StatsBomb event IDs are preserved in each event's eventId field.")
    print(
        "  Data notes: "
        f"{quality['missingPlayerEvents']} events without player, "
        f"{quality['passEventsWithoutPassData']} passes without pass data, "
        f"{quality['shotsWithoutOutcome']} shots without outcome, "
        f"{sum(quality['unsupportedEventTypes'].values())} unsupported event subtypes."
    )
    print("  Source: StatsBomb Open Data (historical; not live).")
    return match_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download cached source files as well as refreshing the selected import.",
    )
    args = parser.parse_args()
    try:
        run_import(refresh=args.refresh)
    except ImportErrorMessage as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nImport cancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
