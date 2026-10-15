import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_api


class FakeResponse:
    def __init__(self, value):
        self.content = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, *_):
        return self.content


def handler_for(value):
    handler = local_api.RequestHandler.__new__(local_api.RequestHandler)
    body = json.dumps(value).encode("utf-8")
    handler.path = "/api/foundry/explain"
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: setattr(handler, "status", status)
    handler.send_header = lambda *_: None
    handler.end_headers = lambda: None
    return handler


def explanation_request(event_time):
    return {
        "insight": {
            "match_id": "simulation-42",
            "match_time": 120,
            "observation": "The team recorded 3 defensive turnovers.",
            "hypothesis": "The opponent's press may be narrowing short options.",
            "supporting_event_ids": ["pass-1"],
            "audience_mode": "analyst",
            "language": "en",
        },
        "statistics": {"passes": 12, "passAccuracy": 75},
        "current_match_time": 120,
        "filters": {"team": "Northbridge FC", "player": ""},
        "evidence_events": [{"id": "pass-1", "matchTime": event_time, "x": 18, "y": 40}],
    }


class FoundryApiTests(unittest.TestCase):
    def test_rejects_evidence_from_after_the_replay_clock_before_network_call(self):
        handler = handler_for(explanation_request(121))
        with patch.object(local_api, "foundry_configuration", return_value=("https://example.test/models", "secret", "model")), \
             patch("local_api.urllib.request.urlopen") as request:
            handler.do_POST()
        self.assertEqual(handler.status, 400)
        self.assertIn("received by the current replay time", json.loads(handler.wfile.getvalue())["error"])
        request.assert_not_called()

    def test_rejects_unprovided_numeric_claims_from_model(self):
        handler = handler_for(explanation_request(118))
        model_result = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "observation": "The team recorded 999 defensive turnovers.",
                        "hypothesis": "The opponent may be narrowing short options.",
                    })
                }
            }]
        }
        with patch.object(local_api, "foundry_configuration", return_value=("https://example.test/models", "secret", "model")), \
             patch("local_api.urllib.request.urlopen", return_value=FakeResponse(model_result)):
            handler.do_POST()
        self.assertEqual(handler.status, 502)
        self.assertIn("numeric claims", json.loads(handler.wfile.getvalue())["error"])

    def test_rejects_spelled_out_unprovided_quantities(self):
        handler = handler_for(explanation_request(118))
        model_result = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "observation": "The team recorded three defensive turnovers.",
                        "hypothesis": "The opponent's press may be narrowing short options.",
                    })
                }
            }]
        }
        with patch.object(local_api, "foundry_configuration", return_value=("https://example.test/models", "secret", "model")), \
             patch("local_api.urllib.request.urlopen", return_value=FakeResponse(model_result)):
            handler.do_POST()
        self.assertEqual(handler.status, 502)
        self.assertIn("number words or quantities", json.loads(handler.wfile.getvalue())["error"])

    def test_returns_grounded_model_explanation(self):
        handler = handler_for(explanation_request(118))
        expected = {
            "observation": "The recorded event context supports the supplied observation.",
            "hypothesis": "The opponent's press may be narrowing short options.",
        }
        model_result = {"choices": [{"message": {"content": json.dumps(expected)}}]}
        with patch.object(local_api, "foundry_configuration", return_value=("https://example.test/models", "secret", "model")), \
             patch("local_api.urllib.request.urlopen", return_value=FakeResponse(model_result)):
            handler.do_POST()
        self.assertEqual(handler.status, 200)
        self.assertEqual(json.loads(handler.wfile.getvalue()), expected)


if __name__ == "__main__":
    unittest.main()
