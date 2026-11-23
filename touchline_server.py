"""Optional, read-only loopback transport for validated Touchline generations."""
import argparse
import json
import mimetypes
import os
import re
import threading
from collections import OrderedDict
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
            "historical_selection_fingerprint_evidence": generation.historical_selection_evidence(manifest["source"]),
            "schema_version": manifest["version"],
            "report_versions": {name: data["version"] for name, data in manifest["files"].items()}}


def player_card(row):
    return fields(row, "player_id", "display_name", "club", "cohorts", "availability", "loan_state",
                  "keeper", "record_game_date", "last_seen_game_date", "game_build")


def assignment(row):
    return fields(row, "slot_id", "player_id", "attribute_profile_score", "warnings", "vacancy_reason",
                  "eligibility_position", "league_benchmark_reason")


class Store:
    def __init__(self, root, career, *, cache_entries=2, cache_bytes=32 * 1024 * 1024):
        self.root = Path(root).resolve()
        self.career = career
        self.cache_entries = max(0, cache_entries)
        self.cache_bytes = max(0, cache_bytes)
        self._cache = OrderedDict()
        self._seen_manifests = {}
        self._lock = threading.RLock()

    def _snapshot(self, gid, expected_manifest=None):
        directory = self.directory(gid)
        raw = (directory / "manifest.json").read_bytes()
        manifest_hash = generation.digest(raw)
        if expected_manifest is not None and expected_manifest != manifest_hash:
            raise APIError(422, "generation_invalid")
        bodies = [(directory / name).read_bytes() for name in generation.FILES]
        # Hash all captured bytes on every request, including cache hits.
        # Never trust mtimes, sizes or the manifest's declared digests alone.
        key = (gid, manifest_hash, tuple(generation.digest(body) for body in bodies))
        size = len(raw) + sum(map(len, bodies))
        with self._lock:
            if gid in self._seen_manifests and self._seen_manifests[gid] != manifest_hash:
                raise APIError(422, "generation_identity_changed")
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key][1]
            manifest, indexes = generation.validate_generation_bytes(gid, raw, bodies)
            if manifest["career"] != self.career:
                raise APIError(404, "generation_unavailable")
            self._seen_manifests[gid] = manifest_hash
            # A different byte identity for the same ID cannot reuse its old indexes.
            for old in list(self._cache):
                if old[0] == gid:
                    del self._cache[old]
            if self.cache_entries and size <= self.cache_bytes:
                while self._cache and (len(self._cache) >= self.cache_entries or
                        sum(entry[0] for entry in self._cache.values()) + size > self.cache_bytes):
                    self._cache.popitem(last=False)
                self._cache[key] = (size, (manifest, indexes))
            return manifest, indexes

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
                value = generation.decode(pointer.read_bytes())
                if value["version"] != generation.VERSION or not isinstance(value["manifest_sha256"], str):
                    raise APIError(422, "generation_invalid")
                manifest, indexes = self._snapshot(value["generation_id"], value["manifest_sha256"])
            else:
                manifest, indexes = self._snapshot(gid)
            if manifest["career"] != self.career:
                raise APIError(404, "generation_unavailable")
            return manifest, indexes
        except FileNotFoundError:
            raise APIError(404, "generation_unavailable") from None
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError, RecursionError):
            raise APIError(422, "generation_invalid") from None

    def data(self, route, gid=None, slot=None, player=None, offset=0, limit=20):
        manifest, ix = self.load(gid)
        meta = provenance(manifest)
        if route in ("current", "generation"):
            return {"generation_id": meta["generation_id"], "provenance": meta}
        if route in ("profile", "history", "benchmark"):
            if gid is None or player is None:
                raise APIError(400, "invalid_query")
            if route == "history" and (type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 50):
                raise APIError(400, "invalid_pagination")
            try:
                history = generation.read_history(self.directory(gid), manifest)
            except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError, RecursionError):
                raise APIError(422, "history_invalid") from None
            evidence = (history or {}).get(player)
            assessment = ix["players"].get(player)
            if evidence is None and assessment is None:
                raise APIError(404, "player_unavailable")
            meta["history_artifact"] = manifest.get("history")
            result = {"version": generation.HISTORY_VERSION, "player_id": player, "career": manifest["career"]}
            if route == "profile":
                result.update(assessment=assessment, membership=evidence["membership"] if evidence else None,
                              current_observation=evidence["observations"][-1] if evidence else None,
                              history_status="available" if evidence else "unavailable",
                              history_reason=None if evidence else "generation_has_no_history_artifact")
            elif route == "history":
                rows = evidence["observations"] if evidence else []
                result.update(status="available" if evidence else "unavailable", total=len(rows) if evidence else None,
                              reason=None if evidence else "generation_has_no_history_artifact",
                              offset=offset, limit=limit, observations=rows[offset:offset + limit],
                              next_offset=offset + limit if offset + limit < len(rows) else None)
            else:
                result.update(status=manifest["benchmark"]["status"] if assessment else "unavailable",
                              reason=manifest["benchmark"]["reason"] if assessment else "no_current_player_comparison",
                              reference=manifest["benchmark"], comparisons=[v for k, v in ix["benchmarks"].items() if k[0] == player])
            response = {"generation_id": gid, "provenance": meta, "data": result}
            if len(generation.canonical(response)) > 512 * 1024:
                raise APIError(422, "player_evidence_too_large")
            return response
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
    if "/" not in assets:
        raise ValueError("Production frontend index is unavailable")
    for ref in re.findall(rb'(?:src|href)="(/assets/[^"]+)"', assets["/"][0]):
        if ref.decode("utf-8") not in assets:
            raise ValueError("Production frontend asset is missing")

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
                          "/api/signing": ("signing", {"generation", "player"}),
                          "/api/profile": ("profile", {"generation", "player"}),
                          "/api/history": ("history", {"generation", "player", "offset", "limit"}),
                          "/api/benchmark": ("benchmark", {"generation", "player"})}
                if url.path not in routes:
                    raise APIError(404, "route_unavailable")
                route, keys = routes[url.path]
                query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=4)
                if set(query) != keys or any(len(v) != 1 or not v[0] or len(v[0]) > 4096 for v in query.values()):
                    raise APIError(400, "invalid_query")
                self.json_response(200, store.data(route, query.get("generation", [None])[0],
                                                   query.get("slot", [None])[0], query.get("player", [None])[0],
                                                   int(query.get("offset", ["0"])[0]), int(query.get("limit", ["20"])[0])))
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

    class LocalServer(ThreadingHTTPServer):
        # Do not permit a second listener to share the configured port.
        allow_reuse_address = os.name != "nt"
        def server_bind(self):
            import socket
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()
    return LocalServer(("127.0.0.1", port), Handler)


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
