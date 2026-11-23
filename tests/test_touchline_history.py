"""M2a fixtures: sparse capture, identity, immutable publication and API bounds."""
import json
import threading
import unittest
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import test_rangers_integration as integration
import touchline_generation as generation
from touchline_server import Store, APIError, make_server


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        f = integration.IntegrationTests()
        f.setUp()
        cls.addClassCleanup(f.doCleanups)
        cls.f = f
        for i in range(100, 143):
            p = integration.player(i, f"Invented squad {i}", squad=True)
            if i == 100:
                p.update(on_loan="true", loan_parent_club_uid="200")
            if i == 101:
                p.update(on_loan="true", club_uid="200", club_name="Invented FC", loan_parent_club_uid="100")
            f.squad.append(p)
            f.world.append(p)
        for i in range(200, 278):
            p = integration.player(i, f"Invented target {i}")
            f.world.append(p)
        f.target["name"] = f.target_gk["name"] = "Invented namesake"
        f.process(candidates=[])
        f.process(candidates=[{"Unique ID": str(i)} for i in [3, 4, *range(200, 278)]])
        with f.db:
            f.db.execute("UPDATE snapshots SET selection_sha256='x' WHERE id=1")
            f.db.execute("UPDATE snapshots SET selection_sha256='' WHERE id=2")
        other = dict(f.cb, name="Other career defender")
        key = integration.watcher.identity(other)
        integration.watcher.import_selection(f.db, "different-career", f.source, "a" * 64,
                                             "b" * 64, {"game_date": f.game_date}, {key: other},
                                             {key: {"squad"}}, f.export, ("100", "800"))
        cls.args = SimpleNamespace(db=f.dbpath, career=integration.CAREER, formation=None, signing_depth_limit=0)
        cls.root = f.root / "history-generations"
        cls.provenance = {}
        cls.reports = integration.bridge.build_reports(cls.args, integration.ROOT, provenance=cls.provenance)[:6]
        cls.first = generation.publish(cls.root, cls.reports, cls.provenance)
        cls.store = Store(cls.root, integration.CAREER)
        cls.manifest, cls.ix = generation.read_generation(cls.root / "generations" / cls.first)
        cls.defender = next(p for p, r in cls.ix["players"].items() if r["name"] == f.cb["name"])
        cls.targets = [p for p, r in cls.ix["players"].items() if r["name"] == "Invented namesake"]
        f.cb["name"] = "Invented renamed defender"
        f.process(candidates=[{"Unique ID": "1"}])
        evidence = {}
        reports = integration.bridge.build_reports(cls.args, integration.ROOT, provenance=evidence)[:6]
        cls.second = generation.publish(cls.root, reports, evidence)
        generation.rollback(cls.root, cls.first)

    def test_sparse_same_day_and_identity(self):
        self.assertEqual(len(self.targets), 2)
        self.assertEqual(len(self.manifest["source"]["members"]), 125)
        versions = generation.read_history(self.root / "generations" / self.first, self.manifest)
        alias = self.root / "generations" / self.first / ".." / self.first
        self.assertEqual(generation.read_history(alias, self.manifest), versions)
        counts = [sum(o["snapshot_id"] == sid for p in versions.values() for o in p["observations"]) for sid in (1, 2)]
        self.assertEqual(counts, [45, 80])
        first = self.store.data("history", self.first, player=self.defender)["data"]
        self.assertEqual(first["total"], 1)
        self.assertEqual(first["observations"][0]["selection_fingerprint_status"], "unverified_invalid")
        self.assertEqual(first["observations"][0]["field_states"]["contract_end"], "not_recorded")
        self.assertNotIn("Other career defender", json.dumps(versions))
        for name, loan in (("Invented squad 100", "incoming"), ("Invented squad 101", "outgoing")):
            pid = next(p for p, r in self.ix["players"].items() if r["name"] == name)
            self.assertEqual(self.store.data("profile", self.first, player=pid)["data"]["assessment"]["loan_state"], loan)
        target = self.store.data("history", self.first, player=self.targets[0])["data"]
        self.assertEqual(target["observations"][0]["selection_fingerprint_status"], "unverified_missing")
        second = self.store.data("history", self.second, player=self.defender, limit=1)["data"]
        third = self.store.data("history", self.second, player=self.defender, offset=second["next_offset"], limit=1)["data"]
        self.assertEqual(second["total"], 2)
        self.assertEqual(second["observations"][0]["game_date"], third["observations"][0]["game_date"])
        self.assertNotEqual(second["observations"][0]["record"]["name"], third["observations"][0]["record"]["name"])
        self.assertEqual(third["observations"][0]["player_id"], self.defender)
        profile = self.store.data("profile", self.second, player=self.defender)["data"]
        self.assertEqual({m["cohort"] for m in profile["membership"] if m["active"]}, {"squad", "target"})
        inactive = self.store.data("profile", self.second, player=self.targets[0])["data"]
        self.assertIsNone(inactive["assessment"])
        self.assertFalse(inactive["membership"][0]["active"])
        self.assertEqual(self.store.data("history", self.first, player=self.defender)["data"], first)

    def test_legacy_absence_and_corruption(self):
        old = dict(self.provenance)
        del old["history"]
        gid = generation.publish(self.root, self.reports, old)
        try:
            for name in generation.FILES:
                self.assertEqual((self.root / "generations" / gid / name).read_bytes(),
                                 (self.root / "generations" / self.first / name).read_bytes())
            result = self.store.data("history", gid, player=self.defender)["data"]
            self.assertEqual(result["status"], "unavailable")
            self.assertIsNone(result["total"])
            path = self.root / "generations" / self.first / generation.HISTORY_FILE
            body = path.read_bytes()
            try:
                for changed in (None, body + b" "):
                    if changed is None:
                        path.unlink()
                    else:
                        path.write_bytes(changed)
                    with self.assertRaises(APIError) as error:
                        self.store.data("history", self.first, player=self.defender)
                    self.assertEqual(error.exception.code, "history_invalid")
                    self.assertEqual(self.store.data("overview", self.first)["generation_id"], self.first)
            finally:
                path.write_bytes(body)
        finally:
            generation.rollback(self.root, self.first)

    def test_relationship_and_bounds(self):
        pointer = (self.root / "current.json").read_bytes()
        for field, value in (("snapshot_id", 999), ("snapshot_career", "different"), ("record_hash", "x")):
            broken = deepcopy(self.provenance)
            broken["history"]["versions"][0][field] = value
            with self.assertRaises(ValueError):
                generation.publish(self.root, self.reports, broken)
        broken = deepcopy(self.provenance)
        broken["history"]["versions"].pop()
        with self.assertRaises(ValueError):
            generation.publish(self.root, self.reports, broken)
        self.assertEqual((self.root / "current.json").read_bytes(), pointer)
        with self.assertRaises(APIError):
            Store(self.root, "different").data("profile", self.first, player=self.defender)
        for limit in (0, 51):
            with self.assertRaises(APIError):
                self.store.data("history", self.first, player=self.defender, limit=limit)
        for route in ("profile", "history", "benchmark"):
            value = self.store.data(route, self.first, player=self.defender)
            self.assertLess(len(generation.canonical(value)), 64 * 1024)
            self.assertNotIn(self.targets[0], json.dumps(value, ensure_ascii=False))

    def test_http_contract(self):
        dist = self.f.root / "history-dist"
        dist.mkdir(exist_ok=True)
        (dist / "index.html").write_text("<title>Invented</title>", encoding="utf-8")
        with make_server(self.store, dist, 0) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                params = {"generation": self.first, "player": self.defender}
                for route in ("profile", "history", "benchmark"):
                    query = params | ({"offset": 0, "limit": 1} if route == "history" else {})
                    with urlopen(base + "/api/" + route + "?" + urlencode(query)) as response:
                        value = json.load(response)
                        self.assertEqual(value["generation_id"], self.first)
                        self.assertEqual(value["data"]["player_id"], self.defender)
                url = base + "/api/history?" + urlencode(params | {"offset": 0, "limit": 1})
                for request, status in ((Request(url, method="POST"), 405),
                                        (Request(url, headers={"Origin": "http://localhost"}), 403),
                                        (Request(url + "&limit=2"), 400),
                                        (Request(base + "/api/history?" + urlencode(params)), 400)):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(request)
                    self.assertEqual(error.exception.code, status)
            finally:
                server.shutdown()
                thread.join()
