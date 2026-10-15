import io
import json
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

import import_wyscout
from import_wyscout import (
    convert_match,
    catalog_matches,
    download_competition_events,
    iter_deflated,
    iter_json_array,
    season_label,
    selected_events,
)


class ConvertWyscoutMatchTests(unittest.TestCase):
    def setUp(self):
        self.competition = {"name": "Example League", "wyId": 42}
        self.teams = [
            {"wyId": 10, "name": "North City"},
            {"wyId": 20, "name": "South United"},
        ]
        self.players = [
            {"wyId": 100, "shortName": "N. Player", "firstName": "North", "lastName": "Player"},
            {"wyId": 200, "shortName": "S. Player", "firstName": "South", "lastName": "Player"},
        ]
        self.metadata = {
            "wyId": 700,
            "dateutc": "2018-01-01 14:00:00",
            "venue": "Tacticore Park",
            "teamsData": {
                "10": {
                    "teamId": 10,
                    "side": "home",
                    "score": 1,
                    "formation": {"lineup": [{"playerId": 100}]},
                },
                "20": {
                    "teamId": 20,
                    "side": "away",
                    "score": 1,
                    "formation": {"lineup": [{"playerId": 200}]},
                },
            },
        }

    def test_converts_event_metrics_lineups_and_own_goal_credit(self):
        raw_events = [
            {
                "id": 101,
                "eventName": "Pass",
                "subEventName": "Simple pass",
                "matchPeriod": "1H",
                "eventSec": 12.4,
                "teamId": 10,
                "playerId": 100,
                "tags": [{"id": 1801}],
            },
            {
                "id": 102,
                "eventName": "Pass",
                "subEventName": "Cross",
                "matchPeriod": "1H",
                "eventSec": 65,
                "teamId": 10,
                "playerId": 100,
                "tags": [{"id": 1802}],
            },
            {
                "id": 103,
                "eventName": "Shot",
                "subEventName": "Shot",
                "matchPeriod": "2H",
                "eventSec": 60,
                "teamId": 10,
                "playerId": 100,
                "tags": [{"id": 101}],
            },
            {
                "id": 104,
                "eventName": "Shot",
                "subEventName": "Shot",
                "matchPeriod": "2H",
                "eventSec": 120,
                "teamId": 10,
                "playerId": 100,
                "tags": [{"id": 101}, {"id": 102}],
            },
            {
                "id": 105,
                "eventName": "Shot",
                "subEventName": "Shot",
                "matchPeriod": "2H",
                "eventSec": 150,
                "teamId": 20,
                "playerId": 200,
                "tags": [{"id": 1203}],
            },
            {
                "id": 106,
                "eventName": "Shot",
                "subEventName": "Shot",
                "matchPeriod": "2H",
                "eventSec": 180,
                "teamId": 20,
                "playerId": 200,
                "tags": [{"id": 2101}],
            },
            {
                "id": 107,
                "eventName": "Duel",
                "subEventName": "Ground defending duel",
                "matchPeriod": "2H",
                "eventSec": 200,
                "teamId": 20,
                "playerId": 200,
                "tags": [{"id": 703}],
            },
            {
                "id": 108,
                "eventName": "Duel",
                "subEventName": "Ground attacking duel",
                "matchPeriod": "2H",
                "eventSec": 210,
                "teamId": 20,
                "playerId": 200,
                "tags": [{"id": 701}],
            },
        ]
        result = convert_match(self.metadata, self.competition, "2017/18", raw_events, self.teams, self.players)
        self.assertEqual(result["source"], "wyscout-open-data")
        self.assertEqual(result["status"], "historical")
        self.assertEqual(result["sourceMatchId"], 700)
        self.assertEqual(result["date"], "2018-01-01")
        self.assertEqual([event["eventId"] for event in result["events"]], [str(i) for i in range(101, 109)])
        self.assertEqual(result["events"][0]["completed"], True)
        self.assertEqual(result["events"][1]["completed"], False)
        self.assertEqual(result["events"][2]["outcome"], "Goal")
        self.assertEqual(result["events"][2]["minute"], 46)
        self.assertEqual(result["events"][3]["goalTeam"], "South United")
        self.assertTrue(result["events"][3]["goalOwnGoal"])
        self.assertTrue(result["events"][4]["onTarget"])
        self.assertFalse(result["events"][5]["onTarget"])
        self.assertEqual(result["events"][6]["type"], "tackle")
        self.assertTrue(result["events"][6]["successful"])
        self.assertEqual(result["events"][7]["type"], "other")
        self.assertEqual(result["lineups"], [
            {"team": "North City", "players": ["N. Player"]},
            {"team": "South United", "players": ["S. Player"]},
        ])
        self.assertFalse(result["dataQuality"]["officialScoreMismatch"])
        self.assertEqual(result["availableMetrics"], ["goals", "passes", "shots", "tackles"])
        self.assertEqual(result["dataQuality"]["unsupportedEventTypes"], {"Duel: Ground attacking duel": 1})

    def test_missing_fields_are_explicit_and_not_guessed(self):
        result = convert_match(
            self.metadata,
            self.competition,
            "2017/18",
            [
                {"eventName": "Pass"},
                {"id": 102, "eventName": "Shot", "teamId": 10, "playerId": 100, "matchPeriod": "X"},
            ],
            self.teams,
            self.players,
        )
        self.assertEqual(result["dataQuality"]["missingSourceEventIds"], 1)
        self.assertEqual(result["dataQuality"]["missingPlayerEvents"], 1)
        self.assertEqual(result["dataQuality"]["missingTeamEvents"], 1)
        self.assertEqual(result["dataQuality"]["passEventsWithoutPassData"], 1)
        self.assertEqual(result["dataQuality"]["shotsWithoutOutcome"], 1)
        self.assertEqual(result["dataQuality"]["missingTimeEvents"], 2)
        self.assertEqual(result["events"][0]["eventId"], "missing-id-1")
        self.assertIsNone(result["events"][0]["completed"])
        self.assertIsNone(result["events"][1]["onTarget"])

    def test_season_label_uses_match_dates(self):
        self.assertEqual(season_label([{"dateutc": "2017-08-01"}, {"dateutc": "2018-05-01"}]), "2017/18")
        self.assertEqual(season_label([{"dateutc": "2018-06-14"}]), "2018")
        self.assertEqual(season_label([]), "Season unavailable")

    def test_uses_extra_time_or_penalty_match_score_fields_when_available(self):
        for duration, expected_home, expected_away in (
            ("ExtraTime", 2, 1),
            ("Penalties", 3, 2),
        ):
            metadata = {
                **self.metadata,
                "duration": duration,
                "teamsData": {
                    "10": {"teamId": 10, "side": "home", "score": 1, "scoreET": 2, "scoreP": 3},
                    "20": {"teamId": 20, "side": "away", "score": 1, "scoreET": 1, "scoreP": 2},
                },
            }
            result = convert_match(metadata, self.competition, "2017/18", [], self.teams, self.players)
            self.assertEqual(result["officialScore"], {"home": expected_home, "away": expected_away})


class WyscoutCatalogTests(unittest.TestCase):
    def test_builds_historical_catalog_with_competition_season_and_team_names(self):
        competitions = [{"wyId": 42, "name": "English first division"}]
        teams = [
            {"wyId": 10, "name": "North City"},
            {"wyId": 20, "name": "South United"},
        ]
        rows = [
            {
                "wyId": 700,
                "competitionId": 42,
                "seasonId": 1,
                "status": "Played",
                "dateutc": "2018-01-01 14:00:00",
                "venue": "Tacticore Park",
                "teamsData": {
                    "10": {"teamId": 10, "side": "home"},
                    "20": {"teamId": 20, "side": "away"},
                },
            },
            {
                "wyId": 701,
                "competitionId": 42,
                "seasonId": 1,
                "status": "Played",
                "dateutc": "2017-08-01 14:00:00",
                "teamsData": {
                    "10": {"teamId": 20, "side": "home"},
                    "20": {"teamId": 10, "side": "away"},
                },
            },
            {"wyId": 702, "competitionId": 42, "seasonId": 1, "status": "Scheduled"},
        ]
        with patch("import_wyscout.load_metadata", return_value=(competitions, teams, Path("cached.zip"))), \
             patch("import_wyscout.read_matches", return_value=rows):
            result = catalog_matches()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {
            "matchId": 700,
            "date": "2018-01-01",
            "competition": "English first division",
            "season": "2017/18",
            "homeTeam": "North City",
            "awayTeam": "South United",
            "venue": "Tacticore Park",
        })
        self.assertEqual(result[1]["homeTeam"], "South United")
        self.assertEqual(result[1]["awayTeam"], "North City")


class WyscoutBatchImportTests(unittest.TestCase):
    def test_imports_all_matches_in_one_event_pass_and_skips_them_on_rerun(self):
        competitions = [{"wyId": 42, "name": "English first division"}]
        rows = [
            {
                "wyId": 700 + index,
                "competitionId": 42,
                "seasonId": 1,
                "status": "Played",
                "dateutc": f"2018-01-0{index + 1} 14:00:00",
            }
            for index in range(2)
        ]
        raw_events = json.dumps([
            {"id": 1, "matchId": 700},
            {"id": 2, "matchId": 701},
        ]).encode()
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        compressed = compressor.compress(raw_events) + compressor.flush()

        def converted(row, competition, season, events, teams, players):
            return {
                "id": f"wyscout-{row['wyId']}",
                "date": row["dateutc"][:10],
                "competition": competition["name"] + " · " + season,
                "homeTeam": "North City",
                "awayTeam": "South United",
                "source": "wyscout-open-data",
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_path = root / "events.deflate"
            event_path.write_bytes(compressed)
            output = root / "historical"
            match_files = output / "matches"
            metadata = (competitions, [], root / "matches.zip")
            patches = (
                patch.object(import_wyscout, "OUTPUT", output),
                patch.object(import_wyscout, "MATCH_FILES", match_files),
                patch.object(import_wyscout, "CACHE", root / ".cache"),
                patch("import_wyscout.load_metadata", return_value=metadata),
                patch("import_wyscout.fetch_json", return_value=[]),
                patch("import_wyscout.read_matches", return_value=rows),
                patch("import_wyscout.download_competition_events", return_value=(event_path, len(raw_events))),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
                 patch("import_wyscout.convert_match", side_effect=converted) as convert:
                self.assertEqual(import_wyscout.import_all_matches(), (2, 0, 0))
                self.assertEqual(convert.call_count, 2)
                index = json.loads((output / "index.json").read_text(encoding="utf-8"))
                self.assertEqual({item["id"] for item in index["matches"]}, {"wyscout-700", "wyscout-701"})
                self.assertTrue((match_files / "wyscout-700.json").is_file())
                self.assertTrue((match_files / "wyscout-701.json").is_file())

                with patch("import_wyscout.download_competition_events") as download, \
                     patch("import_wyscout.convert_match") as convert_again:
                    self.assertEqual(import_wyscout.import_all_matches(), (0, 2, 0))
                    download.assert_not_called()
                    convert_again.assert_not_called()

    def test_event_grouping_rejects_unsorted_match_ids(self):
        raw_events = json.dumps([
            {"id": 1, "matchId": 2},
            {"id": 2, "matchId": 1},
        ]).encode()
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        compressed = compressor.compress(raw_events) + compressor.flush()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.deflate"
            path.write_bytes(compressed)
            with self.assertRaises(import_wyscout.ImportErrorMessage):
                list(import_wyscout.iter_event_groups(path, len(raw_events)))


class WyscoutStreamTests(unittest.TestCase):
    def test_json_array_parser_handles_chunk_boundaries_and_utf8(self):
        value = json.dumps([{"name": "Équipe"}, {"id": 2}], ensure_ascii=False).encode("utf-8")
        chunks = [value[index:index + 3] for index in range(0, len(value), 3)]
        self.assertEqual(list(iter_json_array(chunks)), [{"name": "Équipe"}, {"id": 2}])

    def test_json_array_parser_rejects_invalid_payload(self):
        with self.assertRaises(import_wyscout.ImportErrorMessage):
            list(iter_json_array([b'{"not":"an array"}']))

    def test_cached_deflate_segment_is_filtered_to_selected_match(self):
        data = json.dumps([
            {"id": 1, "matchId": 11},
            {"id": 2, "matchId": 22},
            {"id": 3, "matchId": 22},
            {"id": 4, "matchId": 33},
        ]).encode()
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        compressed = compressor.compress(data) + compressor.flush()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.deflate"
            path.write_bytes(compressed)
            events = selected_events(path, len(data), 22)
            self.assertEqual([event["id"] for event in events], [2, 3])
            self.assertEqual(list(iter_deflated(path, len(data))), [data])
            with self.assertRaises(import_wyscout.ImportErrorMessage):
                selected_events(path, len(data), 23)

    def test_downloads_and_caches_only_the_requested_competition_segment(self):
        archive_buffer = io.BytesIO()
        raw_json = b'[{"matchId":1}]'
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        compressed = compressor.compress(raw_json) + compressor.flush()
        with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("events_Italy.json", raw_json)
            archive.writestr("events_England.json", b"other competition")
        archive_bytes = archive_buffer.getvalue()
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            info = archive.getinfo("events_Italy.json")
            local = archive_bytes[info.header_offset:info.header_offset + 30]
            data_start = info.header_offset + 30 + int.from_bytes(local[26:28], "little") + int.from_bytes(local[28:30], "little")
            data_end = data_start + info.compress_size - 1

        class Response:
            status = 206

            def __init__(self, body, content_range):
                self.body = io.BytesIO(body)
                self.headers = {"Content-Range": content_range}

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def read(self, size=-1):
                return self.body.read(size)

        def range_request(request, timeout=60):
            start, end = map(int, request.headers["Range"].replace("bytes=", "").split("-"))
            content_range = f"bytes {start}-{end}/{len(archive_bytes)}"
            return Response(archive_bytes[start:end + 1], content_range)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "italy.deflate"
            with (
                patch.object(import_wyscout, "EVENTS_ARCHIVE_SIZE", len(archive_bytes)),
                patch.object(import_wyscout, "EVENTS_URL", "https://example.test/events.zip"),
                patch.object(import_wyscout, "HttpRangeFile", return_value=io.BytesIO(archive_bytes)),
                patch("urllib.request.urlopen", side_effect=range_request) as urlopen,
            ):
                cached_path, uncompressed_size = download_competition_events(
                    "events_Italy.json", destination, False
                )
                self.assertEqual(cached_path, destination)
                self.assertEqual(uncompressed_size, len(raw_json))
                self.assertEqual(destination.read_bytes(), compressed)
                self.assertEqual(destination.stat().st_size, info.compress_size)
                urlopen.assert_called_once()
                download_competition_events("events_Italy.json", destination, False)
                urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
