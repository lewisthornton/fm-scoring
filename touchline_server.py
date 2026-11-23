"""Optional, read-only loopback transport for validated Touchline generations."""
import argparse
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import touchline_generation as generation


class APIError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def fields(row, *keys):
    return {key: row.get(key) for key in keys}


def provenance(manifest):
    return {**fields(manifest, "generation_id", "career", "game_date", "generated_utc",
                     "configuration", "benchmark", "source_sha256", "cohort_sha256"),
            "accepted_game_date": manifest["source"]["accepted_game_date"],
            "schema_version": manifest["version"],
            "report_versions": {name: data["version"] for name, data in manifest["files"].items()}}


def player_card(row):
    return fields(row, "player_id", "display_name", "club", "cohorts", "availability", "loan_state",
                  "keeper", "record_game_date", "last_seen_game_date", "game_build")


def assignment(row):
    return fields(row, "slot_id", "player_id", "attribute_profile_score", "warnings", "vacancy_reason",
                  "eligibility_position", "league_benchmark_reason")


class Store:
    def __init__(self, root, career):
        self.root = Path(root).resolve()
        self.career = career

    def directory(self, gid):
        if not isinstance(gid, str) or not re.fullmatch(r"[0-9a-f]{32}", gid):
            raise APIError(400, "invalid_generation_id")
        directory = self.root / "generations" / gid
        if directory.resolve() != directory:
            raise APIError(404, "generation_unavailable")
        for name in (*generation.FILES, "manifest.json"):
            path = directory / name
            if path.resolve() != path:
                raise APIError(404, "generation_unavailable")
        return directory

    def load(self, gid=None):
        try:
            if gid is None:
                pointer = self.root / "current.json"
                if pointer.resolve() != pointer:
                    raise APIError(422, "generation_invalid")
                current = generation.decode(pointer.read_bytes())["generation_id"]
                self.directory(current)
                manifest, indexes = generation.read_current(self.root)
                if manifest["generation_id"] != current:
                    raise APIError(409, "generation_changed_retry")
            else:
                manifest, indexes = generation.read_generation(self.directory(gid))
            if manifest["career"] != self.career:
                raise APIError(404, "generation_unavailable")
            return manifest, indexes
        except FileNotFoundError:
            raise APIError(404, "generation_unavailable") from None
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError, RecursionError):
            raise APIError(422, "generation_invalid") from None

    def data(self, route, gid=None, slot=None, player=None):
        manifest, ix = self.load(gid)
        meta = provenance(manifest)
        if route in ("current", "generation"):
            return {"generation_id": meta["generation_id"], "provenance": meta}
        if slot is not None and slot not in ix["slots"]:
            raise APIError(404, "slot_unavailable")
        if player is not None and player not in ix["players"]:
            raise APIError(404, "player_unavailable")
        if route == "overview":
            result = {"players": [player_card(v) for v in ix["players"].values()],
                      "slots": [ix["slots"][sid] for sid in ix["slot_order"]],
                      "baseline": [assignment(ix["baseline"][sid]) for sid in ix["slot_order"]],
                      "coverage": [fields(ix["depth"][sid], "slot_id", "starter_id", "direct_cover_count",
                                          "cover_type", "shared_direct_deputy_ids", "maintains_completeness",
                                          "effective_deputy_status") for sid in ix["slot_order"]],
                      "summary": ix["summary"], "bench_cover": ix["bench_cover"],
                      "absences": [fields(ix["absences"][pid], "original_slot_id", "removed_player_id",
                                          "filled_slot_loss", "outfield_score_loss", "goalkeeper_score_loss")
                                   for pid in ix["absence_order"]],
                      "recommendations": [fields(ix["signings"][pid], "player_id", "classification", "eligible_slot_ids")
                                          | {"selected_slot_id": (ix["signings"][pid]["xi"] or {}).get("selected_slot_id")}
                                          for pid in ix["signing_order"]],
                      "limitations": ix["limitations"], "signing_assumptions": ix["signing_assumptions"]}
        elif route == "slot":
            row = ix["depth"][slot]
            result = {"slot": ix["slots"][slot], "assignment": ix["baseline"][slot],
                      "coverage": row, "absence": ix["absences"].get(row["starter_id"]),
                      "shared_cover": [r for r in ix["bench_cover"]["shared_cover"] if slot in r["slot_ids"]],
                      "dependencies": [r for r in ix["bench_cover"]["bench_cover_dependencies"] if slot in r["direct_cover_slot_ids"]]}
        elif route == "candidates":
            result = {"slot_id": slot, "candidates": []}
            for pid in ix["signing_order"]:
                row = ix["signings"][pid]
                item = ix["assessments"][pid, slot]
                result["candidates"].append(fields(row, "player_id", "classification", "observed_availability",
                    "observed_cohorts", "scenario_assumed_availability") | {
                    "assessment": item, "eligible": slot in row["eligible_slot_ids"],
                    "reasons": next((r["reasons"] for r in row["rejected_slots"] if r["slot_id"] == slot), []),
                    "depth_status": row["depth"]["status"],
                    "selected_slot_id": (row["xi"] or {}).get("selected_slot_id")})
        elif route == "signing":
            if player not in ix["signings"]:
                raise APIError(404, "candidate_unavailable")
            row = ix["signings"][player]
            result = {k: v for k, v in row.items() if k not in ("observed_slot_evidence", "observations", "league_context", "native_league_context")}
            result["assumptions"] = ix["signing_assumptions"]
        else:
            raise APIError(404, "route_unavailable")
        return {"generation_id": meta["generation_id"], "provenance": meta, "data": result}


def make_server(store, dist, port=8765):
    dist = Path(dist).resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise ValueError("Build the frontend first")
    # Vite emits a closed set of hashed assets. Never map input paths to disk.
    assets = {"/": index, "/index.html": index}
    for path in (dist / "assets").glob("*"):
        if path.is_file() and path.resolve().parent == dist / "assets" and path.suffix in (".js", ".css", ".woff2", ".svg"):
            assets["/assets/" + path.name] = path
    assets = {key: (path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
              for key, path in assets.items() if path.resolve() == path}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send_body(self, status, body, mime):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def json_response(self, status, value):
            self.send_body(status, json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(), "application/json; charset=utf-8")

        def check_headers(self):
            allowed = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get_all("Host") != [allowed]:
                raise APIError(403, "host_not_allowed")
            origins = self.headers.get_all("Origin")
            if origins is not None and origins != ["http://" + allowed]:
                raise APIError(403, "origin_not_allowed")

        def do_GET(self):
            try:
                self.check_headers()
                url = urlsplit(self.path)
                # Reject nonlocal URLs and only accept literal allowlisted paths.
                if url.scheme or url.netloc or url.fragment:
                    raise APIError(404, "route_unavailable")
                if url.path in assets and not url.query:
                    body, mime = assets[url.path]
                    self.send_body(200, body, mime)
                    return
                routes = {"/api/current": ("current", set()), "/api/generation": ("generation", {"generation"}), "/api/overview": ("overview", {"generation"}),
                          "/api/slot": ("slot", {"generation", "slot"}), "/api/candidates": ("candidates", {"generation", "slot"}),
                          "/api/signing": ("signing", {"generation", "player"})}
                if url.path not in routes:
                    raise APIError(404, "route_unavailable")
                route, keys = routes[url.path]
                query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=3)
                if set(query) != keys or any(len(v) != 1 or not v[0] or len(v[0]) > 4096 for v in query.values()):
                    raise APIError(400, "invalid_query")
                self.json_response(200, store.data(route, query.get("generation", [None])[0],
                                                   query.get("slot", [None])[0], query.get("player", [None])[0]))
            except APIError as exc:
                self.json_response(exc.status, {"error": exc.code})
            except ValueError:
                self.json_response(400, {"error": "invalid_request"})

        def reject_method(self):
            try:
                self.check_headers()
                self.json_response(405, {"error": "method_not_allowed"})
            except APIError as exc:
                self.json_response(exc.status, {"error": exc.code})

        do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = reject_method

        def __getattr__(self, name):
            if name.startswith("do_"):
                return self.reject_method
            raise AttributeError(name)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generations", required=True, type=Path)
    parser.add_argument("--career", required=True)
    parser.add_argument("--dist", type=Path, default=Path(__file__).parent / "touchline" / "dist")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with make_server(Store(args.generations, args.career), args.dist, args.port) as server:
        print(f"Touchline: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
