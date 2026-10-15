import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import import_statsbomb
from import_statsbomb import convert_match, fetch_json


class ConvertMatchTests(unittest.TestCase):
    def setUp(self):
        self.metadata = {
            "match_id": 123,
            "match_date": "2024-05-01",
            "competition": "Example League",
            "season": "2023/2024",
            "home_team": {"name": "Home FC"},
            "away_team": {"name": "Away FC"},
            "home_score": 1,
            "away_score": 0,
        }

    def test_converts_supported_event_metrics_and_preserves_event_ids(self):
        raw_events = [
            {
                "id": "pass-complete",
                "minute": 1,
                "team": {"name": "Home FC"},
                "player": {"name": "A. Player"},
                "type": {"name": "Pass"},
                "pass": {},
            },
            {
                "id": "pass-incomplete",
                "minute": 2,
                "team": {"name": "Home FC"},
                "player": {"name": "A. Player"},
                "type": {"name": "Pass"},
                "pass": {"outcome": {"name": "Incomplete"}},
            },
            {
                "id": "goal",
                "minute": 3,
                "team": {"name": "Home FC"},
                "player": {"name": "B. Player"},
                "type": {"name": "Shot"},
                "shot": {"outcome": {"name": "Goal"}},
            },
            {
                "id": "saved-shot",
                "minute": 4,
                "team": {"name": "Away FC"},
                "player": {"name": "C. Player"},
                "type": {"name": "Shot"},
                "shot": {"outcome": {"name": "Saved"}},
            },
            {
                "id": "tackle",
                "minute": 5,
                "team": {"name": "Away FC"},
                "player": {"name": "C. Player"},
                "type": {"name": "Duel"},
                "duel": {"type": {"name": "Tackle"}, "outcome": {"name": "Won"}},
            },
            {
                "id": "carry",
                "minute": 6,
                "team": {"name": "Home FC"},
                "player": {"name": "A. Player"},
                "type": {"name": "Carry"},
            },
        ]
        result = convert_match(self.metadata, raw_events, [])
        self.assertEqual(result["source"], "statsbomb-open-data")
        self.assertEqual(result["status"], "historical")
        self.assertEqual([event["eventId"] for event in result["events"]], [
            "pass-complete", "pass-incomplete", "goal", "saved-shot", "tackle", "carry"
        ])
        self.assertEqual(
            [(event["type"], event.get("completed"), event.get("onTarget")) for event in result["events"]],
            [
                ("pass", True, None),
                ("pass", False, None),
                ("shot", None, True),
                ("shot", None, True),
                ("tackle", None, None),
                ("other", None, None),
            ],
        )
        self.assertEqual(result["dataQuality"]["unsupportedEventTypes"], {"Carry": 1})
        self.assertFalse(result["dataQuality"]["officialScoreMismatch"])
        self.assertEqual(result["lineups"], [])

    def test_missing_fields_are_explicit_and_unknown_outcomes_are_not_guessed(self):
        raw_events = [
            {"id": "missing-pass", "type": {"name": "Pass"}},
            {"id": "missing-shot-result", "type": {"name": "Shot"}, "shot": {}},
            {"type": {"name": "Shot"}, "shot": {"outcome": {"name": "Post"}}},
            {"id": "unknown-outcome", "type": {"name": "Shot"}, "shot": {"outcome": {"name": "Unknown Outcome"}}},
        ]
        result = convert_match(self.metadata, raw_events, None)
        self.assertIsNone(result["events"][0]["completed"])
        self.assertIsNone(result["events"][1]["onTarget"])
        self.assertFalse(result["events"][2]["onTarget"])
        self.assertIsNone(result["events"][3]["onTarget"])
        self.assertEqual(result["dataQuality"]["missingPlayerEvents"], 4)
        self.assertEqual(result["dataQuality"]["missingTeamEvents"], 4)
        self.assertEqual(result["dataQuality"]["missingSourceEventIds"], 1)
        self.assertEqual(result["dataQuality"]["passEventsWithoutPassData"], 1)
        self.assertEqual(result["dataQuality"]["shotsWithoutOutcome"], 1)
        self.assertEqual(result["events"][2]["eventId"], "missing-id-3")
        self.assertEqual(result["dataQuality"]["unrecognizedShotOutcomes"], {"Unknown Outcome": 1})
        self.assertTrue(result["dataQuality"]["officialScoreMismatch"])
        self.assertEqual(result["lineups"], [])

    def test_converts_statsbomb_lineup_shape(self):
        result = convert_match(
            self.metadata,
            [],
            [{"team_name": "Home FC", "lineup": [{"player_name": "A. Player"}]}],
        )
        self.assertEqual(result["lineups"], [{"team": "Home FC", "players": ["A. Player"]}])

    def test_reads_actual_statsbomb_match_metadata_field_names(self):
        metadata = {
            **self.metadata,
            "home_team": {"home_team_name": "Argentina"},
            "away_team": {"away_team_name": "France"},
            "competition": {"competition_name": "FIFA World Cup"},
            "season": {"season_name": "2022"},
            "stadium": {"stadium_name": "Lusail Stadium"},
        }
        result = convert_match(metadata, [], [])
        self.assertEqual(result["homeTeam"], "Argentina")
        self.assertEqual(result["awayTeam"], "France")
        self.assertEqual(result["competition"], "FIFA World Cup · 2022")
        self.assertEqual(result["venue"], "Lusail Stadium")

    def test_cached_source_file_does_not_make_a_network_request(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "events.json"
            expected = [{"id": "cached-event"}]
            cache_path.write_text(json.dumps(expected), encoding="utf-8")
            with patch("urllib.request.urlopen") as urlopen:
                self.assertEqual(fetch_json("https://example.test/events.json", cache_path, False), expected)
                urlopen.assert_not_called()

    def test_interactive_import_writes_one_match_and_a_local_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "public" / "data" / "historical"
            values = {
                f"{import_statsbomb.RAW_BASE}/competitions.json": [
                    {
                        "competition_id": 2,
                        "season_id": 3,
                        "competition_name": "Example League",
                        "season_name": "2023/2024",
                    }
                ],
                f"{import_statsbomb.RAW_BASE}/matches/2/3.json": [
                    {
                        "match_id": 99,
                        "match_date": "2024-05-01",
                        "home_team": {"name": "Home FC"},
                        "away_team": {"name": "Away FC"},
                        "home_score": 1,
                        "away_score": 0,
                    }
                ],
                f"{import_statsbomb.RAW_BASE}/events/99.json": [
                    {
                        "id": "goal-99",
                        "minute": 10,
                        "team": {"name": "Home FC"},
                        "player": {"name": "A. Player"},
                        "type": {"name": "Shot"},
                        "shot": {"outcome": {"name": "Goal"}},
                    }
                ],
                f"{import_statsbomb.RAW_BASE}/lineups/99.json": [],
            }

            def fetch(url, _cache_path, _refresh):
                return values[url]

            with (
                patch.object(import_statsbomb, "ROOT", root),
                patch.object(import_statsbomb, "CACHE", root / ".cache" / "statsbomb"),
                patch.object(import_statsbomb, "OUTPUT", output),
                patch.object(import_statsbomb, "MATCH_FILES", output / "matches"),
                patch.object(import_statsbomb, "fetch_json", side_effect=fetch) as fetch_mock,
                patch("builtins.input", side_effect=["1", "1", "1"]),
                redirect_stdout(io.StringIO()),
            ):
                imported_path = import_statsbomb.run_import()

            imported = json.loads(imported_path.read_text(encoding="utf-8"))
            index = json.loads((output / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(imported["source"], "statsbomb-open-data")
            self.assertEqual(imported["events"][0]["eventId"], "goal-99")
            self.assertEqual(index["matches"][0]["file"], "matches/99.json")
            self.assertEqual(len(fetch_mock.call_args_list), 4)
            self.assertTrue(index["matches"][0]["cacheKey"])


if __name__ == "__main__":
    unittest.main()
