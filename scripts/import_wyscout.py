#!/usr/bin/env python3
"""Import Wyscout Open Data matches into Tacticore."""

from __future__ import annotations

import argparse
import codecs
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request
import zipfile
import zlib
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "wyscout"
OUTPUT = ROOT / "public" / "data" / "historical"
MATCH_FILES = OUTPUT / "matches"
COMPETITIONS_URL = "https://ndownloader.figshare.com/files/15073685"
MATCHES_URL = "https://ndownloader.figshare.com/files/14464622"
TEAMS_URL = "https://ndownloader.figshare.com/files/15073697"
PLAYERS_URL = "https://ndownloader.figshare.com/files/15073721"
EVENTS_URL = "https://ndownloader.figshare.com/files/14464685"
EVENTS_ARCHIVE_SIZE = 77_323_413
COLLECTION_URL = "https://figshare.com/collections/Soccer_match_event_dataset/4415000"
EVENT_DATA_URL = "https://figshare.com/articles/dataset/Events/7770599"
COLORS = ["#69e0c0", "#9b8cff", "#f3a95e", "#70a5ff", "#e47c98", "#d3bd78"]
EVENT_MEMBERS = {
    "Italian first division": "Italy",
    "English first division": "England",
    "Spanish first division": "Spain",
    "French first division": "France",
    "German first division": "Germany",
    "European Championship": "European_Championship",
    "World Cup": "World_Cup",
}


class ImportErrorMessage(Exception):
    """An actionable import or repository-data error."""


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def fetch_bytes(url: str, cache_path: Path, refresh: bool) -> bytes:
    if cache_path.is_file() and not refresh:
        return cache_path.read_bytes()
    request = urllib.request.Request(url, headers={"User-Agent": "Tacticore-local-importer/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
    except urllib.error.HTTPError as error:
        raise ImportErrorMessage(f"Figshare returned HTTP {error.code} for {url}") from error
    except urllib.error.URLError as error:
        raise ImportErrorMessage(f"Could not download {url}: {error.reason}") from error
    atomic_write(cache_path, content)
    return content


def fetch_json(url: str, cache_path: Path, refresh: bool) -> Any:
    content = fetch_bytes(url, cache_path, refresh)
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ImportErrorMessage(f"Cached or downloaded JSON is invalid ({cache_path}): {error}") from error


class HttpRangeFile:
    """Small seekable reader that fetches only requested byte ranges from Figshare."""

    def __init__(self, url: str, size: int):
        self.url = url
        self.size = size
        self.position = 0

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self.position = offset
        elif whence == 1:
            self.position += offset
        elif whence == 2:
            self.position = self.size + offset
        else:
            raise ValueError(f"Invalid seek mode: {whence}")
        if self.position < 0:
            raise ValueError("Cannot seek before the start of the source archive.")
        return self.position

    def tell(self) -> int:
        return self.position

    def seekable(self) -> bool:
        return True

    def read(self, length: int = -1) -> bytes:
        if length < 0:
            length = self.size - self.position
        if length == 0 or self.position >= self.size:
            return b""
        end = min(self.size - 1, self.position + length - 1)
        request = urllib.request.Request(
            self.url,
            headers={
                "Range": f"bytes={self.position}-{end}",
                "User-Agent": "Tacticore-local-importer/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content_range = response.headers.get("Content-Range", "")
                expected_range = f"bytes {self.position}-{end}/{self.size}"
                if response.status != 206 or content_range != expected_range:
                    raise ImportErrorMessage(
                        "Figshare did not honor the requested byte range; refusing to download the full event archive."
                    )
                content = response.read()
        except urllib.error.HTTPError as error:
            raise ImportErrorMessage(f"Figshare returned HTTP {error.code} for the requested event archive range.") from error
        except urllib.error.URLError as error:
            raise ImportErrorMessage(f"Could not read the Wyscout event archive: {error.reason}") from error
        if len(content) != end - self.position + 1:
            raise ImportErrorMessage("Figshare returned an incomplete byte range for the event archive.")
        self.position += len(content)
        return content


def download_competition_events(member: str, destination: Path, refresh: bool) -> tuple[Path, int]:
    remote = HttpRangeFile(EVENTS_URL, EVENTS_ARCHIVE_SIZE)
    try:
        with zipfile.ZipFile(remote) as archive:
            try:
                info = archive.getinfo(member)
            except KeyError as error:
                raise ImportErrorMessage(f"The Wyscout event archive does not contain {member}.") from error
            remote.seek(info.header_offset)
            header = remote.read(30)
            if len(header) != 30 or header[:4] != b"PK\x03\x04":
                raise ImportErrorMessage(f"The Wyscout ZIP header for {member} is invalid.")
            filename_length = int.from_bytes(header[26:28], "little")
            extra_length = int.from_bytes(header[28:30], "little")
            if int.from_bytes(header[8:10], "little") != zipfile.ZIP_DEFLATED:
                raise ImportErrorMessage(f"The Wyscout event segment uses an unsupported ZIP compression method.")
            flags = int.from_bytes(header[6:8], "little")
            if flags & 0x1:
                raise ImportErrorMessage(f"The Wyscout event segment {member} is encrypted and cannot be imported.")
            compressed_start = info.header_offset + 30 + filename_length + extra_length
            compressed_end = compressed_start + info.compress_size - 1
            uncompressed_size = info.file_size
    except (OSError, zipfile.BadZipFile) as error:
        raise ImportErrorMessage(f"Could not inspect the Wyscout event archive: {error}") from error

    if destination.is_file() and not refresh:
        return destination, uncompressed_size

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    request = urllib.request.Request(
        EVENTS_URL,
        headers={
            "Range": f"bytes={compressed_start}-{compressed_end}",
            "User-Agent": "Tacticore-local-importer/1.0",
        },
    )
    downloaded = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content_range = response.headers.get("Content-Range", "")
            expected_range = f"bytes {compressed_start}-{compressed_end}/{EVENTS_ARCHIVE_SIZE}"
            if response.status != 206 or content_range != expected_range:
                raise ImportErrorMessage(
                    "Figshare did not honor the selected competition's byte range; refusing to download the full event archive."
                )
            with temporary.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
    except urllib.error.HTTPError as error:
        temporary.unlink(missing_ok=True)
        raise ImportErrorMessage(f"Figshare returned HTTP {error.code} while downloading {member}.") from error
    except urllib.error.URLError as error:
        temporary.unlink(missing_ok=True)
        raise ImportErrorMessage(f"Could not download {member}: {error.reason}") from error
    if downloaded != info.compress_size:
        temporary.unlink(missing_ok=True)
        raise ImportErrorMessage(f"Figshare returned an incomplete {member} event segment.")
    temporary.replace(destination)
    return destination, uncompressed_size


def iter_json_array(chunks: Iterable[bytes]) -> Iterable[Any]:
    decoder = json.JSONDecoder()
    text_decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    position = 0
    started = False
    ended = False
    for raw_chunk in chunks:
        buffer += text_decoder.decode(raw_chunk, final=False)
        if not started:
            while position < len(buffer) and buffer[position].isspace():
                position += 1
            if position == len(buffer):
                buffer = ""
                position = 0
                continue
            if buffer[position] != "[":
                raise ImportErrorMessage("Wyscout event segment is not a JSON array.")
            position += 1
            started = True
        while True:
            if ended:
                if buffer[position:].strip():
                    raise ImportErrorMessage("Unexpected content follows the Wyscout event array.")
                position = len(buffer)
                break
            while position < len(buffer) and (buffer[position].isspace() or buffer[position] == ","):
                position += 1
            if position == len(buffer):
                break
            if buffer[position] == "]":
                position += 1
                ended = True
                continue
            try:
                value, end = decoder.raw_decode(buffer, position)
            except json.JSONDecodeError:
                break
            yield value
            position = end
        if position:
            buffer = buffer[position:]
            position = 0
    buffer += text_decoder.decode(b"", final=True)
    if ended:
        if buffer.strip():
            raise ImportErrorMessage("Unexpected content follows the Wyscout event array.")
    elif started:
        buffer = buffer.lstrip()
        if buffer.startswith("]") and not buffer[1:].strip():
            ended = True
    if not started or not ended or buffer.strip():
        raise ImportErrorMessage("Wyscout event segment contains incomplete or invalid JSON.")


def iter_deflated(path: Path, expected_size: int) -> Iterable[bytes]:
    inflater = zlib.decompressobj(-zlib.MAX_WBITS)
    total = 0
    with path.open("rb") as source:
        while True:
            compressed = source.read(128 * 1024)
            if not compressed:
                break
            output = inflater.decompress(compressed)
            total += len(output)
            if output:
                yield output
        output = inflater.flush()
        total += len(output)
        if output:
            yield output
    if not inflater.eof or total != expected_size:
        raise ImportErrorMessage("The cached Wyscout event segment failed its decompression or size check.")


def names_by_id(items: Any, name_fields: tuple[str, ...]) -> dict[int, str]:
    result: dict[int, str] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("wyId"), int):
            continue
        name = next(
            (item.get(field, "").strip() for field in name_fields if isinstance(item.get(field), str) and item[field].strip()),
            "",
        )
        if name:
            result[item["wyId"]] = name
    return result


def team_code(name: str) -> str:
    words = name.split()
    return "".join(word[0] for word in words[:3]).upper() if len(words) > 1 else name[:3].upper()


def integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def tag_ids(raw: Any) -> set[int]:
    if not isinstance(raw, list):
        return set()
    return {
        item["id"] for item in raw
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }


def event_time(raw: dict[str, Any]) -> tuple[int, int] | None:
    seconds = raw.get("eventSec")
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return None
    if seconds < 0:
        return None
    period = raw.get("matchPeriod")
    offset = {"1H": 0, "2H": 45, "E1": 90, "E2": 105, "P": 120}.get(period)
    if offset is None:
        return None
    whole_seconds = int(seconds)
    return offset + whole_seconds // 60, whole_seconds % 60


def make_event(
    raw: dict[str, Any],
    index: int,
    team_names: dict[int, str],
    player_names: dict[int, str],
    home: str,
    away: str,
) -> tuple[dict[str, Any], str | None, bool, bool, bool]:
    raw_id = raw.get("id")
    missing_id = raw_id is None or raw_id == ""
    event_id = f"missing-id-{index}" if missing_id else str(raw_id)
    team_id = integer(raw.get("teamId"))
    player_id = integer(raw.get("playerId"))
    team = team_names.get(team_id, "") if team_id is not None else ""
    player = player_names.get(player_id, "") if player_id is not None else ""
    missing_team = not team
    missing_player = not player
    team = team or "Unknown team"
    event_type = raw.get("eventName") if isinstance(raw.get("eventName"), str) else "Unknown"
    sub_event = raw.get("subEventName") if isinstance(raw.get("subEventName"), str) else ""
    ids = tag_ids(raw.get("tags"))
    time = event_time(raw)
    minute, second = time if time is not None else (0, 0)
    name = f"{event_type} · {sub_event}" if sub_event else event_type
    event: dict[str, Any] = {
        "eventId": event_id,
        "minute": minute,
        "second": second,
        "team": team,
        "player": player,
        "type": "other",
        "sourceEventType": event_type,
        "sourceEventName": name,
    }
    unsupported: str | None = None
    missing_shot_outcome = False

    if event_type.casefold() == "pass":
        event["type"] = "pass"
        has_accurate = 1801 in ids
        has_inaccurate = 1802 in ids
        event["completed"] = True if has_accurate and not has_inaccurate else False if has_inaccurate and not has_accurate else None
        if has_accurate and not has_inaccurate:
            event["passOutcome"] = "Accurate"
        elif has_inaccurate and not has_accurate:
            event["passOutcome"] = "Not accurate"
        else:
            event["passOutcome"] = None
    elif event_type.casefold() == "shot":
        event["type"] = "shot"
        event["goalOwnGoal"] = 102 in ids
        event["goalPenalty"] = sub_event.casefold() == "penalty" or raw.get("matchPeriod") == "P"
        if 101 in ids:
            event["outcome"] = "Goal"
            event["onTarget"] = True
            if event["goalOwnGoal"] and team in {home, away}:
                event["goalTeam"] = away if team == home else home
        elif 2101 in ids:
            event["outcome"] = "Blocked"
            event["onTarget"] = False
        elif ids.intersection(range(1201, 1210)):
            event["outcome"] = "On target"
            event["onTarget"] = True
        elif ids.intersection(range(1210, 1224)):
            event["outcome"] = "Off target"
            event["onTarget"] = False
        else:
            event["outcome"] = None
            event["onTarget"] = None
            missing_shot_outcome = True
    elif event_type.casefold() == "duel" and sub_event.casefold() == "ground defending duel":
        event["type"] = "tackle"
        event["successful"] = True if 703 in ids else False if 701 in ids else None
        event["sourceEventName"] = "Tackle · Ground defending duel"
    else:
        unsupported = event_type + (f": {sub_event}" if sub_event else "")

    return event, unsupported, missing_player, missing_team, missing_id


def convert_match(
    metadata: dict[str, Any],
    competition: dict[str, Any],
    season_label: str,
    raw_events: list[dict[str, Any]],
    teams: Any,
    players: Any,
) -> dict[str, Any]:
    team_names = names_by_id(teams, ("name", "officialName"))
    player_names = names_by_id(players, ("shortName", "shortName2"))
    if isinstance(players, list):
        for item in players:
            if not isinstance(item, dict) or not isinstance(item.get("wyId"), int):
                continue
            full_name = " ".join(
                value.strip() for value in (item.get("firstName"), item.get("lastName"))
                if isinstance(value, str) and value.strip()
            )
            if full_name:
                player_names.setdefault(item["wyId"], full_name)

    team_data = metadata.get("teamsData")
    if not isinstance(team_data, dict):
        team_data = {}
    sides: dict[str, tuple[int, dict[str, Any]]] = {}
    for raw_team_id, item in team_data.items():
        if not isinstance(item, dict) or item.get("side") not in {"home", "away"}:
            continue
        team_id = integer(item.get("teamId"))
        if team_id is None:
            try:
                team_id = int(raw_team_id)
            except (TypeError, ValueError):
                continue
        sides[item["side"]] = (team_id, item)

    home_id = sides.get("home", (None, {}))[0]
    away_id = sides.get("away", (None, {}))[0]
    home = team_names.get(home_id, "Unknown home team") if home_id is not None else "Unknown home team"
    away = team_names.get(away_id, "Unknown away team") if away_id is not None else "Unknown away team"
    unsupported: Counter[str] = Counter()
    missing_players = 0
    missing_teams = 0
    missing_ids = 0
    missing_time = 0
    missing_shot_outcome = 0
    converted_events: list[dict[str, Any]] = []

    for index, raw in enumerate(raw_events, start=1):
        if not isinstance(raw, dict):
            continue
        event, unsupported_type, missing_player, missing_team, missing_source_id = make_event(
            raw, index, team_names, player_names, home, away
        )
        if unsupported_type:
            unsupported[unsupported_type] += 1
        if missing_player:
            missing_players += 1
        if missing_team:
            missing_teams += 1
        if missing_source_id:
            missing_ids += 1
        if event["type"] == "shot" and event.get("onTarget") is None:
            missing_shot_outcome += 1
        if event_time(raw) is None:
            missing_time += 1
        converted_events.append(event)

    colors = {home: COLORS[0], away: COLORS[1]}
    lineups: list[dict[str, Any]] = []
    unresolved_lineup_players = 0
    for side in ("home", "away"):
        team_entry = sides.get(side)
        if not team_entry:
            continue
        lineup_team_id, item = team_entry
        lineup_team_name = team_names.get(lineup_team_id, f"Unknown team {lineup_team_id}")
        formation = item.get("formation")
        lineup = formation.get("lineup") if isinstance(formation, dict) else None
        lineup_names: list[str] = []
        if isinstance(lineup, list):
            for player in lineup:
                player_id = integer(player.get("playerId")) if isinstance(player, dict) else None
                if player_id is None:
                    unresolved_lineup_players += 1
                    continue
                name = player_names.get(player_id)
                if name:
                    lineup_names.append(name)
                else:
                    unresolved_lineup_players += 1
        lineups.append({"team": lineup_team_name, "players": lineup_names})

    score_field = {
        "ExtraTime": "scoreET",
        "Penalties": "scoreP",
    }.get(metadata.get("duration"), "score")
    home_score = integer(sides.get("home", (None, {}))[1].get(score_field))
    away_score = integer(sides.get("away", (None, {}))[1].get(score_field))
    event_home_score = sum(
        event["type"] == "shot" and event.get("outcome") == "Goal" and
        (event.get("goalTeam") or event["team"]) == home
        for event in converted_events
    )
    event_away_score = sum(
        event["type"] == "shot" and event.get("outcome") == "Goal" and
        (event.get("goalTeam") or event["team"]) == away
        for event in converted_events
    )
    match_id = integer(metadata.get("wyId"))
    if match_id is None:
        raise ImportErrorMessage("The selected Wyscout match has no valid wyId.")
    raw_date = metadata.get("dateutc")
    match_date = "Date unavailable"
    if isinstance(raw_date, str):
        try:
            match_date = date.fromisoformat(raw_date[:10]).isoformat()
        except ValueError:
            match_date = raw_date
    competition_name = competition.get("name") if isinstance(competition.get("name"), str) else "Wyscout Open Data"
    competition_label = f"{competition_name}{f' · {season_label}' if season_label else ''}"
    venue = metadata.get("venue") if isinstance(metadata.get("venue"), str) and metadata["venue"].strip() else "Venue unavailable"
    return {
        "id": f"wyscout-{match_id}",
        "sourceMatchId": match_id,
        "date": match_date,
        "competition": competition_label,
        "venue": venue,
        "homeTeam": home,
        "awayTeam": away,
        "homeCode": team_code(home),
        "awayCode": team_code(away),
        "homeColor": colors[home],
        "awayColor": colors[away],
        "source": "wyscout-open-data",
        "status": "historical",
        "sourceUrl": COLLECTION_URL,
        "availableMetrics": ["goals", "passes", "shots", "tackles"],
        "officialScore": {"home": home_score, "away": away_score},
        "lineups": lineups,
        "dataQuality": {
            "missingPlayerEvents": missing_players,
            "missingTeamEvents": missing_teams,
            "missingSourceEventIds": missing_ids,
            "passEventsWithoutPassData": sum(
                event["type"] == "pass" and event.get("completed") is None for event in converted_events
            ),
            "shotsWithoutOutcome": missing_shot_outcome,
            "unrecognizedShotOutcomes": {},
            "unsupportedEventTypes": dict(sorted(unsupported.items())),
            "missingTimeEvents": missing_time,
            "unresolvedLineupPlayers": unresolved_lineup_players,
            "officialScoreMismatch": (
                home_score is not None and away_score is not None and
                (home_score != event_home_score or away_score != event_away_score)
            ),
            "unavailableMetrics": [
                "Expected goals (xG) and possession percentages are not provided.",
                "Tackles are Wyscout Ground defending duel events.",
                "Shot-on-target status is unavailable when the source has no shot-position or outcome tag.",
                "Passing accuracy uses the Wyscout Accurate and Not accurate tags.",
            ],
        },
        "events": converted_events,
    }


def season_label(matches: list[dict[str, Any]]) -> str:
    years: set[int] = set()
    for match in matches:
        raw = match.get("dateutc")
        if isinstance(raw, str) and len(raw) >= 4 and raw[:4].isdigit():
            years.add(int(raw[:4]))
    if not years:
        return "Season unavailable"
    first, last = min(years), max(years)
    if first == last:
        return str(first)
    if last == first + 1:
        return f"{first}/{last % 100:02d}"
    return f"{first}–{last}"


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


def read_matches(archive_path: Path, member: str) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            raw = json.loads(archive.read(member).decode("utf-8"))
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ImportErrorMessage(f"Could not read Wyscout match metadata {member}: {error}") from error
    if not isinstance(raw, list):
        raise ImportErrorMessage(f"Wyscout match metadata {member} is not a JSON array.")
    return [item for item in raw if isinstance(item, dict)]


def load_metadata(refresh: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Path]:
    competitions = fetch_json(COMPETITIONS_URL, CACHE / "competitions.json", refresh)
    teams = fetch_json(TEAMS_URL, CACHE / "teams.json", refresh)
    matches_path = CACHE / "matches.zip"
    fetch_bytes(MATCHES_URL, matches_path, refresh)
    if not isinstance(competitions, list) or not isinstance(teams, list):
        raise ImportErrorMessage("Wyscout competition or team metadata is not a JSON array.")
    return (
        [item for item in competitions if isinstance(item, dict)],
        [item for item in teams if isinstance(item, dict)],
        matches_path,
    )


def catalog_matches(refresh: bool = False) -> list[dict[str, Any]]:
    competitions, teams, matches_path = load_metadata(refresh)
    team_names = {
        integer(team.get("wyId")): team["name"]
        for team in teams
        if integer(team.get("wyId")) is not None and isinstance(team.get("name"), str)
    }
    catalog: list[dict[str, Any]] = []
    for competition in competitions:
        name = competition.get("name")
        competition_id = integer(competition.get("wyId"))
        suffix = EVENT_MEMBERS.get(name) if isinstance(name, str) else None
        if not suffix or competition_id is None:
            continue
        rows = [
            row for row in read_matches(matches_path, f"matches_{suffix}.json")
            if integer(row.get("competitionId")) == competition_id and row.get("status") == "Played"
        ]
        seasons: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            season_id = integer(row.get("seasonId"))
            if season_id is not None:
                seasons.setdefault(season_id, []).append(row)
        for season_rows in seasons.values():
            season = season_label(season_rows)
            for row in season_rows:
                source_match_id = integer(row.get("wyId"))
                if source_match_id is None:
                    continue
                sides = row.get("teamsData")
                if not isinstance(sides, dict):
                    sides = {}
                home = next((item for item in sides.values() if isinstance(item, dict) and item.get("side") == "home"), {})
                away = next((item for item in sides.values() if isinstance(item, dict) and item.get("side") == "away"), {})
                home_name = team_names.get(integer(home.get("teamId")), "Unknown team")
                away_name = team_names.get(integer(away.get("teamId")), "Unknown team")
                raw_date = row.get("dateutc")
                match_date = raw_date[:10] if isinstance(raw_date, str) and len(raw_date) >= 10 else ""
                catalog.append({
                    "matchId": source_match_id,
                    "date": match_date,
                    "competition": name,
                    "season": season,
                    "homeTeam": home_name,
                    "awayTeam": away_name,
                    "venue": row.get("venue") if isinstance(row.get("venue"), str) else "",
                })
    catalog.sort(key=lambda item: (item["date"], item["competition"], item["homeTeam"]), reverse=True)
    return catalog


def read_index() -> dict[str, Any]:
    index_path = OUTPUT / "index.json"
    if not index_path.is_file():
        return {"source": "local-imports", "matches": []}
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ImportErrorMessage(f"Imported-match index is invalid: {error}") from error
    if not isinstance(index, dict) or not isinstance(index.get("matches"), list):
        raise ImportErrorMessage("Imported-match index has an invalid matches list.")
    return index


def import_match_by_id(
    source_match_id: int,
    refresh: bool = False,
    metadata: tuple[list[dict[str, Any]], list[dict[str, Any]], Path] | None = None,
) -> Path:
    competitions, teams, matches_path = metadata if metadata is not None else load_metadata(refresh)
    players = fetch_json(PLAYERS_URL, CACHE / "players.json", refresh)
    if not isinstance(players, list):
        raise ImportErrorMessage("Wyscout players.json is not a JSON array.")
    competition_by_id = {
        integer(item.get("wyId")): item for item in competitions
        if integer(item.get("wyId")) is not None
    }
    team_by_id = {
        integer(item.get("wyId")): item for item in teams
        if integer(item.get("wyId")) is not None
    }
    matches_by_suffix: dict[str, list[dict[str, Any]]] = {}
    selected: dict[str, Any] | None = None
    selected_competition: dict[str, Any] | None = None
    selected_season: list[dict[str, Any]] = []
    selected_suffix = ""
    for competition_id, competition in competition_by_id.items():
        name = competition.get("name")
        suffix = EVENT_MEMBERS.get(name) if isinstance(name, str) else None
        if not suffix:
            continue
        rows = matches_by_suffix.get(suffix)
        if rows is None:
            rows = read_matches(matches_path, f"matches_{suffix}.json")
            matches_by_suffix[suffix] = rows
        for row in rows:
            if integer(row.get("wyId")) == source_match_id and integer(row.get("competitionId")) == competition_id and row.get("status") == "Played":
                selected = row
                selected_competition = competition
                selected_suffix = suffix
                selected_season = [
                    item for item in rows
                    if integer(item.get("competitionId")) == competition_id and
                    integer(item.get("seasonId")) == integer(row.get("seasonId")) and
                    item.get("status") == "Played"
                ]
                break
        if selected is not None:
            break
    if selected is None or selected_competition is None:
        raise ImportErrorMessage(f"Played Wyscout match {source_match_id} was not found in the cached catalog.")

    match_id = f"wyscout-{source_match_id}"
    match_path = MATCH_FILES / f"{match_id}.json"
    index = read_index()
    imported = any(
        isinstance(item, dict) and item.get("source") == "wyscout-open-data" and item.get("id") == match_id
        for item in index["matches"]
    )
    if match_path.is_file() and imported and not refresh:
        return match_path

    event_segment, event_size = download_competition_events(
        f"events_{selected_suffix}.json",
        CACHE / "events" / f"{selected_suffix}.deflate",
        refresh,
    )
    raw_events = selected_events(event_segment, event_size, source_match_id)
    converted = convert_match(
        selected,
        selected_competition,
        season_label(selected_season),
        raw_events,
        teams,
        players,
    )
    atomic_write(match_path, (json.dumps(converted, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    update_index(converted, match_path)
    return match_path


def selected_events(path: Path, member_size: int, match_id: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in iter_json_array(iter_deflated(path, member_size)):
        if not isinstance(item, dict):
            continue
        event_match_id = integer(item.get("matchId"))
        if event_match_id == match_id:
            result.append(item)
        elif event_match_id is not None and event_match_id > match_id:
            # The published event segments are ordered by match ID; stop once this match is passed.
            break
    if not result:
        raise ImportErrorMessage(f"No events for match {match_id} were found in its competition event segment.")
    return result


def iter_event_groups(path: Path, member_size: int) -> Iterable[tuple[int, list[dict[str, Any]]]]:
    current_id: int | None = None
    current_events: list[dict[str, Any]] = []
    previous_id: int | None = None
    for item in iter_json_array(iter_deflated(path, member_size)):
        if not isinstance(item, dict):
            continue
        match_id = integer(item.get("matchId"))
        if match_id is None:
            continue
        if previous_id is not None and match_id < previous_id:
            raise ImportErrorMessage("The Wyscout event segment is not ordered by match ID; batch import was stopped.")
        previous_id = match_id
        if current_id is not None and match_id != current_id:
            yield current_id, current_events
            current_events = []
        current_id = match_id
        current_events.append(item)
    if current_id is not None:
        yield current_id, current_events


def index_entry(converted: dict[str, Any], match_path: Path) -> dict[str, Any]:
    version = hashlib.sha256(match_path.read_bytes()).hexdigest()[:16]
    return {
        "id": converted["id"],
        "date": converted["date"],
        "competition": converted["competition"],
        "homeTeam": converted["homeTeam"],
        "awayTeam": converted["awayTeam"],
        "file": f"matches/{match_path.name}",
        "cacheKey": version,
        "status": "historical",
        "source": converted["source"],
    }


def write_index_entries(index: dict[str, Any], additions: list[dict[str, Any]]) -> None:
    entries = index["matches"]
    added_ids = {str(item["id"]) for item in additions}
    kept = [
        item for item in entries
        if not (
            isinstance(item, dict) and
            item.get("source") == "wyscout-open-data" and
            str(item.get("id")) in added_ids
        )
    ]
    kept.extend(additions)
    kept.sort(key=lambda item: str(item.get("date", "")), reverse=True)
    index["matches"] = kept
    atomic_write(
        OUTPUT / "index.json",
        (json.dumps({"source": "local-imports", "matches": kept}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def update_index(converted: dict[str, Any], match_path: Path) -> str:
    index = read_index()
    entry = index_entry(converted, match_path)
    write_index_entries(index, [entry])
    return entry["cacheKey"]


def import_all_matches(
    refresh: bool = False,
    competition_filter: str | None = None,
    season_filter: str | None = None,
) -> tuple[int, int, int]:
    competitions, teams, matches_path = load_metadata(refresh)
    players = fetch_json(PLAYERS_URL, CACHE / "players.json", refresh)
    if not isinstance(players, list):
        raise ImportErrorMessage("Wyscout players.json is not a JSON array.")
    player_names = names_by_id(players, ("shortName", "name", "firstName"))
    competition_by_id = {
        integer(item.get("wyId")): item for item in competitions
        if integer(item.get("wyId")) is not None
    }
    index = read_index()
    indexed_ids = {
        str(item.get("id")) for item in index["matches"]
        if isinstance(item, dict) and item.get("source") == "wyscout-open-data"
    }

    batches: list[tuple[str, str, list[tuple[dict[str, Any], dict[str, Any], str]]]] = []
    found_competitions: set[str] = set()
    found_seasons: set[str] = set()
    matches_by_suffix: dict[str, list[dict[str, Any]]] = {}
    for competition_id, competition in competition_by_id.items():
        name = competition.get("name")
        suffix = EVENT_MEMBERS.get(name) if isinstance(name, str) else None
        if not suffix or not isinstance(name, str):
            continue
        if competition_filter and name.casefold() != competition_filter.casefold():
            continue
        found_competitions.add(name)
        rows = matches_by_suffix.get(suffix)
        if rows is None:
            rows = read_matches(matches_path, f"matches_{suffix}.json")
            matches_by_suffix[suffix] = rows
        played = [
            item for item in rows
            if integer(item.get("competitionId")) == competition_id and item.get("status") == "Played"
        ]
        seasons: dict[int, list[dict[str, Any]]] = {}
        for row in played:
            season_id = integer(row.get("seasonId"))
            if season_id is not None:
                seasons.setdefault(season_id, []).append(row)
        selected_rows: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        for season_rows in seasons.values():
            label = season_label(season_rows)
            if season_filter and label.casefold() != season_filter.casefold():
                continue
            found_seasons.add(label)
            if any(integer(row.get("wyId")) is not None for row in season_rows):
                selected_rows.extend((row, competition, label) for row in season_rows)
        if selected_rows:
            batches.append((name, suffix, selected_rows))

    if competition_filter and not found_competitions:
        available = ", ".join(sorted(EVENT_MEMBERS))
        raise ImportErrorMessage(f"Unknown Wyscout competition {competition_filter!r}. Available: {available}.")
    if season_filter and not found_seasons:
        raise ImportErrorMessage(f"No played Wyscout matches were found for season {season_filter!r}.")
    if not batches:
        raise ImportErrorMessage("No played Wyscout matches matched the selected filters.")

    total = sum(len(rows) for _, _, rows in batches)
    skipped = 0
    imported = 0
    additions: list[dict[str, Any]] = []
    event_seen: set[int] = set()
    print(f"Wyscout batch import: {total} matches selected.")

    for competition_name, suffix, competition_rows in batches:
        match_metadata: dict[int, tuple[dict[str, Any], dict[str, Any], str]] = {}
        for row, competition, label in competition_rows:
            source_id = integer(row.get("wyId"))
            if source_id is None:
                continue
            match_metadata[source_id] = (row, competition, label)

        pending: set[int] = set()
        for source_id in match_metadata:
            match_path = MATCH_FILES / f"wyscout-{source_id}.json"
            if not refresh and f"wyscout-{source_id}" in indexed_ids and match_path.is_file():
                skipped += 1
            else:
                pending.add(source_id)
        if not pending:
            print(f"  {competition_name}: all {len(match_metadata)} matches already imported.")
            continue

        print(f"  {competition_name}: importing {len(pending)} matches.")
        event_seen: set[int] = set()
        event_segment, event_size = download_competition_events(
            f"events_{suffix}.json",
            CACHE / "events" / f"{suffix}.deflate",
            refresh,
        )
        for source_id, raw_events in iter_event_groups(event_segment, event_size):
            event_seen.add(source_id)
            if source_id not in pending:
                continue
            metadata = match_metadata.get(source_id)
            if metadata is None:
                continue
            match_row, competition, season = metadata
            converted = convert_match(match_row, competition, season, raw_events, teams, players)
            match_path = MATCH_FILES / f"wyscout-{source_id}.json"
            atomic_write(
                match_path,
                (json.dumps(converted, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
            additions.append(index_entry(converted, match_path))
            imported += 1
            if len(additions) >= 25:
                write_index_entries(index, additions)
                indexed_ids.update(str(entry["id"]) for entry in additions)
                additions.clear()
            if imported % 100 == 0:
                print(f"    Imported {imported} / {total - skipped} new matches…")

        missing_ids = pending - event_seen
        if missing_ids:
            print(
                f"  Warning: {len(missing_ids)} matches in {competition_name} had no events and were not imported."
            )
        if additions:
            write_index_entries(index, additions)
            indexed_ids.update(str(entry["id"]) for entry in additions)
            additions.clear()

    print(f"Batch complete: {imported} imported, {skipped} already cached, {total - imported - skipped} unavailable.")
    return imported, skipped, total - imported - skipped


def run_import(refresh: bool = False) -> Path:
    print("Wyscout Open Data — local historical match importer")
    competitions, teams, matches_path = load_metadata(refresh)
    competition = choose(
        [item for item in competitions if isinstance(item, dict) and isinstance(item.get("name"), str)],
        "competition",
        lambda item: item["name"],
    )
    suffix = EVENT_MEMBERS.get(competition["name"])
    competition_id = integer(competition.get("wyId"))
    if not suffix or competition_id is None:
        raise ImportErrorMessage(f"Unsupported Wyscout competition metadata: {competition.get('name')!r}.")
    match_rows = [
        item for item in read_matches(matches_path, f"matches_{suffix}.json")
        if integer(item.get("competitionId")) == competition_id and item.get("status") == "Played"
    ]
    if not match_rows:
        raise ImportErrorMessage(f"No played matches were found for {competition['name']}.")
    seasons: dict[int, list[dict[str, Any]]] = {}
    for row in match_rows:
        season_id = integer(row.get("seasonId"))
        if season_id is not None:
            seasons.setdefault(season_id, []).append(row)
    selected_season_id = choose(
        sorted(seasons, key=lambda key: season_label(seasons[key]), reverse=True),
        "season",
        lambda key: f"{season_label(seasons[key])} ({len(seasons[key])} matches)",
    )
    available = sorted(
        seasons[selected_season_id],
        key=lambda row: (str(row.get("dateutc", "")), str(row.get("label", ""))),
    )
    selected = choose(
        available,
        "match",
        lambda row: f"{row.get('dateutc', 'date unavailable')} · {row.get('label', 'Teams unavailable')}",
    )
    source_match_id = integer(selected.get("wyId"))
    if source_match_id is None:
        raise ImportErrorMessage("The selected Wyscout match has an invalid wyId.")
    match_path = import_match_by_id(source_match_id, refresh, (competitions, teams, matches_path))
    converted = json.loads(match_path.read_text(encoding="utf-8"))
    quality = converted["dataQuality"]
    print(f"\nImported {converted['homeTeam']} vs {converted['awayTeam']} ({converted['date']}).")
    print(f"  Match data: {match_path.relative_to(ROOT)}")
    print(f"  Events: {len(converted['events'])}; lineup teams: {len(converted['lineups'])}")
    print("  Original Wyscout event IDs are preserved as strings in each event's eventId field.")
    print(
        "  Data notes: "
        f"{quality['missingPlayerEvents']} events without a player, "
        f"{quality['passEventsWithoutPassData']} passes without an accuracy tag, "
        f"{quality['shotsWithoutOutcome']} shots without an outcome tag, "
        f"{sum(quality['unsupportedEventTypes'].values())} unsupported event subtypes."
    )
    event_segment = CACHE / "events" / f"{suffix}.deflate"
    if event_segment.is_file():
        print(f"  Cached only events_{suffix}.json ({event_segment.stat().st_size / (1024 * 1024):.1f} MB compressed).")
    print("  Source: Wyscout Soccer Match Event Dataset (historical; not live; CC BY 4.0).")
    return match_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Batch import every played match in the public Wyscout catalog.",
    )
    parser.add_argument(
        "--competition",
        help="With --all, limit the batch to this competition name.",
    )
    parser.add_argument(
        "--season",
        help="With --all, limit the batch to this season label (for example 2017/18).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download cached metadata and selected competition event segments.",
    )
    args = parser.parse_args()
    if not args.all and (args.competition or args.season):
        parser.error("--competition and --season can only be used with --all.")
    try:
        if args.all:
            import_all_matches(
                refresh=args.refresh,
                competition_filter=args.competition,
                season_filter=args.season,
            )
        else:
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
