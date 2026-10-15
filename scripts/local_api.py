#!/usr/bin/env python3
"""Serve Tacticore's cached Wyscout catalog and local match collection."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import import_wyscout


HOST = "127.0.0.1"
PORT = 8765
catalog_cache: list[dict[str, Any]] | None = None


def collection() -> list[dict[str, Any]]:
    return [
        item for item in import_wyscout.read_index()["matches"]
        if isinstance(item, dict) and item.get("source") in {
            "statsbomb-open-data", "user-results-archive", "wyscout-open-data"
        }
    ]


def foundry_configuration() -> tuple[str, str, str] | None:
    endpoint = os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT", "").strip().rstrip("/")
    api_key = os.environ.get("AZURE_AI_FOUNDRY_API_KEY", "").strip()
    model = os.environ.get("AZURE_AI_FOUNDRY_MODEL", "").strip()
    if not endpoint or not api_key or not model:
        return None
    parsed = urlparse(endpoint)
    local_host = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local_host):
        raise ValueError("AZURE_AI_FOUNDRY_ENDPOINT must use HTTPS.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("AZURE_AI_FOUNDRY_ENDPOINT must be a base URL without embedded credentials, query, or fragment.")
    return endpoint, api_key, model


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "TacticoreLocalAPI/1.0"

    def respond(self, status: int, value: Any) -> None:
        content = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        global catalog_cache
        route = urlparse(self.path)
        try:
            if route.path == "/api/foundry/status":
                try:
                    configured = foundry_configuration() is not None
                except ValueError as error:
                    self.respond(200, {"configured": False, "error": str(error)})
                    return
                self.respond(200, {"configured": configured})
                return
            if route.path == "/api/collection":
                self.respond(200, {"matches": collection()})
                return
            if route.path == "/api/wyscout/catalog":
                refresh = parse_qs(route.query).get("refresh") == ["1"]
                if catalog_cache is None or refresh:
                    catalog_cache = import_wyscout.catalog_matches(refresh=refresh)
                imported_ids = {
                    item.get("id") for item in collection()
                    if item.get("source") == "wyscout-open-data"
                }
                matches = [
                    {**item, "imported": f"wyscout-{item['matchId']}" in imported_ids}
                    for item in catalog_cache
                ]
                self.respond(200, {"matches": matches})
                return
            self.respond(404, {"error": "Unknown API endpoint."})
        except import_wyscout.ImportErrorMessage as error:
            self.respond(500, {"error": str(error)})

    def do_POST(self) -> None:
        route_path = urlparse(self.path).path
        if route_path == "/api/foundry/explain":
            self.explain_with_foundry()
            return
        self.import_wyscout_match()

    def read_request_json(self, maximum_length: int = 65536) -> Any | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.respond(400, {"error": "Invalid request length."})
            return None
        if length < 1 or length > maximum_length:
            self.respond(400, {"error": f"Request body must be between 1 and {maximum_length} bytes."})
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.respond(400, {"error": "Request body must be valid JSON."})
            return None

    def explain_with_foundry(self) -> None:
        try:
            configuration = foundry_configuration()
        except ValueError as error:
            self.respond(503, {"error": str(error)})
            return
        if configuration is None:
            self.respond(503, {"error": "Microsoft Foundry is not configured. Set AZURE_AI_FOUNDRY_ENDPOINT, AZURE_AI_FOUNDRY_API_KEY, and AZURE_AI_FOUNDRY_MODEL in the local backend environment."})
            return
        body = self.read_request_json()
        if body is None:
            return
        if not isinstance(body, dict):
            self.respond(400, {"error": "Request body must be a JSON object."})
            return
        insight = body.get("insight")
        current_time = body.get("current_match_time")
        evidence = body.get("evidence_events")
        statistics = body.get("statistics")
        filters = body.get("filters")
        if not isinstance(insight, dict) or not isinstance(current_time, int) or not isinstance(evidence, list) or not isinstance(statistics, dict) or not isinstance(filters, dict):
            self.respond(400, {"error": "Request must include an insight, current match time, filtered statistics, filters, and evidence events."})
            return
        match_id = insight.get("match_id")
        supporting_ids = insight.get("supporting_event_ids")
        if (
            not isinstance(match_id, str) or
            not isinstance(supporting_ids, list) or
            not all(isinstance(event_id, str) for event_id in supporting_ids) or
            len(evidence) > 24
        ):
            self.respond(400, {"error": "Insight metadata or supporting event IDs are invalid."})
            return
        allowed_ids = set(supporting_ids)
        for event in evidence:
            if (
                not isinstance(event, dict) or
                event.get("id") not in allowed_ids or
                event.get("matchTime") is None or
                not isinstance(event.get("matchTime"), int) or
                event["matchTime"] > current_time
            ):
                self.respond(400, {"error": "Evidence must contain only supported events received by the current replay time."})
                return

        endpoint, api_key, model = configuration
        prompt_data = {
            "insight": {
                "headline": insight.get("headline"),
                "observation": insight.get("observation"),
                "hypothesis": insight.get("hypothesis"),
                "match_time": insight.get("match_time"),
                "audience_mode": insight.get("audience_mode"),
                "language": insight.get("language"),
                "supporting_event_ids": supporting_ids,
            },
            "statistics": statistics,
            "current_match_time": current_time,
            "filters": filters,
            "evidence_events": evidence,
        }
        system_prompt = (
            "You explain football findings for a local analytics demo. Use only the supplied statistics and event evidence. "
            "Do not add facts, causes, outcomes, or numbers that are not explicitly supported. The observation must state "
            "what the supplied data records; the hypothesis must be clearly tentative and must not be phrased as a fact. "
            "Do not mention events after current_match_time. Respect the insight language and audience_mode. "
            "Return only a JSON object with string fields observation and hypothesis."
        )
        user_prompt = json.dumps(prompt_data, ensure_ascii=False, separators=(",", ":"))
        request_body = json.dumps({
            "model": model,
            "temperature": 0,
            "max_tokens": 240,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{endpoint}/chat/completions?api-version=2024-05-01-preview",
            data=request_body,
            headers={
                "Content-Type": "application/json",
                "api-key": api_key,
                "User-Agent": "Tacticore-local-backend/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            self.respond(502, {"error": f"Microsoft Foundry returned HTTP {error.code}."})
            return
        except (urllib.error.URLError, TimeoutError) as error:
            self.respond(502, {"error": f"Could not reach Microsoft Foundry: {error}."})
            return
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self.respond(502, {"error": f"Microsoft Foundry returned an invalid response: {error}."})
            return

        try:
            content = result["choices"][0]["message"]["content"]
            explanation = json.loads(content)
            observation = explanation["observation"]
            hypothesis = explanation["hypothesis"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            self.respond(502, {"error": "Microsoft Foundry did not return the required observation/hypothesis JSON."})
            return
        if (
            not isinstance(observation, str) or
            not isinstance(hypothesis, str) or
            not observation.strip() or
            not hypothesis.strip() or
            len(observation) > 800 or
            len(hypothesis) > 800
        ):
            self.respond(502, {"error": "Microsoft Foundry returned invalid or overlong explanation fields."})
            return
        supported_number_context = json.dumps({
            "statistics": statistics,
            "current_match_time": current_time,
            "observation": insight.get("observation"),
            "hypothesis": insight.get("hypothesis"),
            "evidence_positions_and_times": [
                {key: event.get(key) for key in ("matchTime", "x", "y")}
                for event in evidence
            ],
        }, ensure_ascii=False)
        evidence_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", supported_number_context))
        response_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", f"{observation} {hypothesis}"))
        if response_numbers - evidence_numbers:
            self.respond(502, {"error": "Microsoft Foundry added numeric claims not present in the supplied evidence."})
            return
        number_words = re.compile(
            r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
            r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|once|twice|thrice|"
            r"cero|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|"
            r"trece|catorce|quince|dieciséis|diecisiete|dieciocho|diecinueve|veinte|"
            r"treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa|cien|ciento|"
            r"varios|varias|muchos|muchas|pocos|pocas)\b",
            re.IGNORECASE,
        )
        supported_words = {word.casefold() for word in number_words.findall(supported_number_context)}
        response_words = {word.casefold() for word in number_words.findall(f"{observation} {hypothesis}")}
        if response_words - supported_words:
            self.respond(502, {"error": "Microsoft Foundry added number words or quantities not present in the supplied evidence."})
            return
        self.respond(200, {"observation": observation.strip(), "hypothesis": hypothesis.strip()})

    def import_wyscout_match(self) -> None:
        if urlparse(self.path).path != "/api/wyscout/import":
            self.respond(404, {"error": "Unknown API endpoint."})
            return
        body = self.read_request_json(4096)
        if body is None:
            return
        match_id = body.get("matchId") if isinstance(body, dict) else None
        if isinstance(match_id, bool) or not isinstance(match_id, int) or match_id <= 0:
            self.respond(400, {"error": "matchId must be a positive integer."})
            return
        try:
            match_key = f"wyscout-{match_id}"
            was_imported = any(
                item.get("id") == match_key and item.get("source") == "wyscout-open-data"
                for item in collection()
            )
            match_path = import_wyscout.import_match_by_id(match_id)
            converted = json.loads(match_path.read_text(encoding="utf-8"))
            global catalog_cache
            if catalog_cache is not None:
                catalog_cache = [
                    {**item, "imported": True} if item["matchId"] == match_id else item
                    for item in catalog_cache
                ]
            self.respond(200, {
                "match": {
                    "id": converted["id"],
                    "date": converted["date"],
                    "competition": converted["competition"],
                    "homeTeam": converted["homeTeam"],
                    "awayTeam": converted["awayTeam"],
                },
                "alreadyImported": was_imported,
            })
        except import_wyscout.ImportErrorMessage as error:
            self.respond(422, {"error": str(error)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[Tacticore API] {format % args}", file=sys.stderr)


def main() -> int:
    try:
        with ThreadingHTTPServer((HOST, PORT), RequestHandler) as server:
            print(f"Tacticore local data API listening on http://{HOST}:{PORT}")
            server.serve_forever()
    except OSError as error:
        print(f"Could not start the local data API: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nTacticore local data API stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
