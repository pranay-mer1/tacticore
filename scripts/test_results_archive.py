import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import import_results_archive
from import_results_archive import make_match, read_csv_from_zip


class ResultsArchiveTests(unittest.TestCase):
    def test_converts_score_and_scorers_without_inventing_shots_or_tackles(self):
        match = make_match(
            {
                "date": "2024-05-01",
                "home_team": "Home FC",
                "away_team": "Away FC",
                "home_score": "2",
                "away_score": "1",
                "tournament": "Example Cup",
                "city": "London",
                "country": "England",
            },
            [{
                "date": "2024-05-01",
                "home_team": "Home FC",
                "away_team": "Away FC",
                "team": "Home FC",
                "scorer": "A. Player",
                "minute": "12",
                "own_goal": "FALSE",
                "penalty": "TRUE",
            }],
            "2024",
            "Example Cup",
        )
        self.assertEqual(match["source"], "user-results-archive")
        self.assertEqual(match["availableMetrics"], ["goals"])
        self.assertEqual(match["officialScore"], {"home": 2, "away": 1})
        self.assertEqual(match["events"][0]["type"], "goal")
        self.assertEqual(match["events"][0]["eventId"], f"missing-id-archive:{match['id'].removeprefix('results-')}:1")
        self.assertEqual(match["events"][0]["player"], "A. Player")
        self.assertTrue(match["events"][0]["goalPenalty"])
        self.assertTrue(match["dataQuality"]["scorerRecordMismatch"])
        self.assertEqual(match["dataQuality"]["unavailableMetrics"], [
            "Pass counts and passing accuracy",
            "Shot counts and shots on target",
            "Tackle counts",
            "Lineups and non-goal match events",
        ])

    def test_reads_expected_csv_files_from_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "matches.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "dataset/results.csv",
                    "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
                    "2024-01-01,Home,Away,1,0,Cup,Town,Country,FALSE\n",
                )
                archive.writestr(
                    "dataset/goalscorers.csv",
                    "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n"
                    "2024-01-01,Home,Away,Home,Player,25,FALSE,FALSE\n",
                )
            with zipfile.ZipFile(archive_path) as archive:
                results = read_csv_from_zip(archive, "results.csv")
                scorers = read_csv_from_zip(archive, "goalscorers.csv")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["home_score"], "1")
        self.assertEqual(scorers[0]["scorer"], "Player")

    def test_interactive_import_updates_local_index_and_cache_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "matches.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "results.csv",
                    "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
                    "2024-01-01,Home,Away,1,0,Cup,Town,Country,FALSE\n",
                )
                archive.writestr(
                    "goalscorers.csv",
                    "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n"
                    "2024-01-01,Home,Away,Home,Player,25,FALSE,FALSE\n",
                )
            output = root / "public" / "data" / "historical"
            with (
                patch.object(import_results_archive, "ROOT", root),
                patch.object(import_results_archive, "OUTPUT", output),
                patch.object(import_results_archive, "MATCH_FILES", output / "matches"),
                patch("builtins.input", side_effect=["1", "1", "1"]),
                redirect_stdout(StringIO()),
            ):
                match_path = import_results_archive.run_import(archive_path)
            match = json.loads(match_path.read_text(encoding="utf-8"))
            index = json.loads((output / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(match["events"][0]["player"], "Player")
        self.assertEqual(index["matches"][0]["source"], "user-results-archive")
        self.assertTrue(index["matches"][0]["cacheKey"])


if __name__ == "__main__":
    unittest.main()
