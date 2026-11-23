"""M1b transport tests against invented operational generations."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen
from urllib.request import Request
from urllib.error import HTTPError

from touchline_fixture import create, CAREER
from touchline_server import Store, APIError, make_server
import touchline_generation as generation


class TouchlineServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name) / "fixture"
        cls.first, cls.second = create(cls.root)
        cls.store = Store(cls.root, CAREER)

    def test_canonical_joins_and_order(self):
        manifest, ix = generation.read_generation(self.root / "generations" / self.first)
        overview = self.store.data("overview", self.first)
        self.assertEqual(overview["generation_id"], self.first)
        self.assertEqual(overview["data"]["bench_cover"], ix["bench_cover"])
        self.assertEqual([p["player_id"] for p in overview["data"]["recommendations"]], ix["signing_order"])
        self.assertEqual(overview["data"]["summary"]["totals"], ix["summary"]["totals"])
        self.assertTrue(any(r["player_id"] is None for r in overview["data"]["baseline"]))
        self.assertTrue(ix["bench_cover"]["shared_cover"])
        self.assertTrue(ix["bench_cover"]["bench_cover_dependencies"])
        self.assertTrue(any(c["depth"]["status"] == "not_evaluated_limit" for c in ix["signings"].values()))
        self.assertTrue(any(c["classification"] == "already_in_squad" for c in ix["signings"].values()))
        self.assertEqual(len([p for p in overview["data"]["players"] if "Alex Example" in p["display_name"]]), 2)
        for sid in ix["slot_order"]:
            slot = self.store.data("slot", self.first, slot=sid)["data"]
            self.assertEqual(slot["assignment"], ix["baseline"][sid])
            candidates = self.store.data("candidates", self.first, slot=sid)["data"]["candidates"]
            self.assertEqual([v["player_id"] for v in candidates], ix["signing_order"])
            for row in candidates:
                pid = row["player_id"]
                self.assertEqual(row["assessment"], ix["assessments"][pid, sid])
                self.assertEqual(row["eligible"], sid in ix["signings"][pid]["eligible_slot_ids"])
                self.assertEqual(row["depth_status"], ix["signings"][pid]["depth"]["status"])
        for pid in ix["signing_order"]:
            signing = self.store.data("signing", self.first, player=pid)["data"]
            self.assertEqual(signing["xi"], ix["signings"][pid]["xi"])
            self.assertEqual(signing["depth"], ix["signings"][pid]["depth"])

    def test_pinned_generation_and_missing(self):
        generation.rollback(self.root, self.second)
        try:
            self.assertEqual(self.store.data("current")["generation_id"], self.second)
            self.assertEqual(self.store.data("overview", self.first)["generation_id"], self.first)
            self.assertEqual(self.store.data("candidates", self.second, slot="lb")["data"]["candidates"], [])
            with self.assertRaises(APIError):
                self.store.data("signing", self.second, player="unknown")
            with self.assertRaises(APIError):
                self.store.data("overview", "0" * 32)
            with self.assertRaises(APIError):
                Store(self.root, "another-career").data("overview", self.first)
            pointer = self.root / "current.json"
            pointer.write_text("{}", encoding="utf-8")
            with self.assertRaises(APIError):
                self.store.data("current")
            self.assertEqual(self.store.data("overview", self.first)["generation_id"], self.first)
        finally:
            generation.rollback(self.root, self.first)

    def test_http_local_read_only(self):
        dist = Path(self.temp.name) / "dist"
        dist.mkdir(exist_ok=True)
        (dist / "index.html").write_text("<!doctype html><title>Invented</title>", encoding="utf-8")
        with make_server(self.store, dist, 0) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/api/current", timeout=5) as response:
                    self.assertEqual(json.load(response)["generation_id"], self.first)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                with urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
                    self.assertIn(b"Invented", response.read())
                base = f"http://127.0.0.1:{server.server_port}"
                for request, expected in (
                    (Request(base + "/api/current", headers={"Host": "localhost"}), 403),
                    (Request(base + "/api/current", headers={"Origin": "http://localhost"}), 403),
                    (Request(base + "/not-an-asset"), 404),
                    (Request(base + "/api/overview?generation=invalid"), 400),
                    (Request(base + "/api/current", method="POST"), 405),
                ):
                    with self.assertRaises(HTTPError) as exc:
                        urlopen(request, timeout=5)
                    self.assertEqual(exc.exception.code, expected)
                    self.assertIn("error", json.load(exc.exception))
            finally:
                server.shutdown()
                thread.join()
