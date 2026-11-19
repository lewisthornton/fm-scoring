"""Characterisation of the existing Rangers integration using invented data."""
import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations" / "rangers"))
import rangers_autosave_watcher as watcher
import rangers_fm_scoring_bridge as bridge

MODEL = tomllib.loads((ROOT / "weights/fm27v2.toml").read_text(encoding="utf-8"))
CAREER = "invented-career"
SLUG = "invented-dashboard"
DATE = "2027-01-01"


def player(uid, name, squad=False, keeper=False):
    record = {
        "uid": str(uid), "unique_id": str(uid), "name": name,
        "birth_date": "2000-01-01", "age": "27",
        "club_name": "Rangers" if squad else "Invented FC",
        "club_uid": "100" if squad else "200",
        "ability_current": "100", "ability_potential": "120",
        "positions_gk": "20" if keeper else "1",
        "positions_dc": "1" if keeper else "20",
    }
    names = sorted(set(MODEL["gk"]).union(*MODEL["outfield"].values()))
    for index, name in enumerate(names):
        record["attributes_" + name.lower().replace(" ", "_")] = str(8 + (index + uid) % 12)
    return record


def write_csv(path, rows):
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dbpath = self.root / "fixture.sqlite3"
        self.db = watcher.connect(self.dbpath)
        self.addCleanup(self.db.close)
        self.source = self.root / "invented.fm"
        self.source.write_bytes(b"invented save bytes")
        self.export = self.root / "invented.csv"
        self.cb = player(1, "Fixture Defender", squad=True)
        self.gk = player(2, "Fixture Keeper", squad=True, keeper=True)
        self.target = player(3, "Fixture Target")
        self.target_gk = player(4, "Fixture Target Keeper", keeper=True)
        self.unselected = player(5, "Unselected World Player")
        self.squad = [self.cb, self.gk]
        self.world = self.squad + [self.target, self.target_gk, self.unselected]
        self.candidates = [{"Unique ID": str(i)} for i in (1, 3, 4)]
        self.game_date = DATE
        self.copies = []
        self.commands = []

    def fake_fmsave(self, command, copied_save, *args):
        copied = Path(copied_save)
        self.assertNotEqual(copied, self.source)
        self.assertEqual(copied.read_bytes(), self.source.read_bytes())
        self.copies.append(copied)
        self.commands.append((command, *args))
        if command == "info":
            return json.dumps({"game_date": self.game_date})
        rows = self.squad if "--managed-club" in args else self.world
        write_csv(Path(args[args.index("-o") + 1]), rows)
        return ""

    def process(self, candidates=None):
        self.source.write_bytes(b"invented save bytes " + self.game_date.encode("ascii"))
        candidates = self.candidates if candidates is None else candidates
        write_csv(self.export, candidates or [{"Unique ID": ""}])
        if not candidates:
            self.export.write_text("Unique ID\n", encoding="utf-8")
        with patch.object(watcher, "fmsave", side_effect=self.fake_fmsave):
            watcher.process(self.db, self.source, CAREER, self.export)

    def dump(self):
        return list(self.db.iterdump())

    def active(self):
        return set(self.db.execute("SELECT player_key, cohort FROM cohort_membership WHERE active=1"))

    def prepare_renderer(self):
        for name in ("score.py", "template.html", "charts.html", "theme.css"):
            shutil.copyfile(ROOT / name, self.root / name)
        shutil.copytree(ROOT / "weights", self.root / "weights")

    def render(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "integrations/rangers/rangers_fm_scoring_bridge.py"),
             "--fm-scoring-root", str(self.root), "--db", str(self.dbpath),
             "--career", CAREER, "--slug", SLUG],
            cwd=self.root, capture_output=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.root / "out" / SLUG

    def native_data(self, directory, page):
        body = (directory / (page + ".html")).read_text(encoding="utf-8")
        return json.loads(re.search(r"const DATA = (.*?);\n", body).group(1))

    def dashboard(self, directory):
        body = (directory / "recruitment.html").read_text(encoding="utf-8")
        return json.loads(re.search(r'<script id="dataset" type="application/json">(.*?)</script>', body).group(1))

    def expected_score(self, record, weights):
        return sum(int(record["attributes_" + a.lower().replace(" ", "_")]) * w
                   for a, w in weights.items()) / sum(weights.values())

    def test_end_to_end_scoped_import_and_native_pages(self):
        original = b"invented save bytes " + DATE.encode("ascii")
        self.process()
        self.assertEqual(self.source.read_bytes(), original)
        self.assertTrue(all(not path.exists() for path in self.copies))
        self.assertEqual(len(self.active()), 5)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM player_versions").fetchone()[0], 4)
        self.assertNotIn("Unselected World Player", str(self.dump()))
        before = self.dump()
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        bytes_before = self.dbpath.read_bytes()
        self.prepare_renderer()
        out = self.render()
        self.assertEqual(self.dump(), before)
        self.assertEqual(self.dbpath.read_bytes(), bytes_before)
        self.assertEqual({p.stem for p in out.glob("*.html")},
                         {"squad", "players", "last", "staff", "last_staff", "charts", "filters", "recruitment"})
        squad = {p["name"]: p for p in self.native_data(out, "squad")}
        targets = {p["name"]: p for p in self.native_data(out, "last")}
        self.assertEqual(set(squad), {self.cb["name"], self.gk["name"]})
        self.assertEqual(set(targets), {self.target["name"], self.target_gk["name"]})
        for record, page, weights in [(self.cb, squad, MODEL["outfield"]),
                                      (self.target, targets, MODEL["outfield"]),
                                      (self.gk, squad, {"GK": MODEL["gk"]}),
                                      (self.target_gk, targets, {"GK": MODEL["gk"]})]:
            for role, profile in weights.items():
                self.assertAlmostEqual(page[record["name"]][role], self.expected_score(record, profile))
        report = self.dashboard(out)
        self.assertEqual((report["meta"]["squad"], report["meta"]["targets"]), (2, 2))
        for role, profile in MODEL["outfield"].items():
            candidate, = report["roles"][role]["candidates"]
            self.assertEqual(candidate["uid"], self.target["uid"])
            self.assertAlmostEqual(candidate["score"], self.expected_score(self.target, profile), places=3)
        keeper, = report["roles"]["GK"]["candidates"]
        self.assertAlmostEqual(keeper["score"], self.expected_score(self.target_gk, MODEL["gk"]), places=3)
        self.assertEqual(report["roles"]["CB"]["incumbent"]["name"], self.cb["name"])
        self.assertAlmostEqual(report["roles"]["CB"]["candidates"][0]["uplift"],
                               self.expected_score(self.target, MODEL["outfield"]["CB"]) -
                               self.expected_score(self.cb, MODEL["outfield"]["CB"]), places=3)
        save = self.root / "saves" / SLUG
        self.assertFalse((save / "world").exists())
        self.assertEqual(len(tomllib.loads((save / "save.toml").read_text(encoding="utf-8"))["last_batch"]), 2)
        self.assertNotIn("Unselected World Player", "".join(p.read_text(encoding="utf-8") for p in out.glob("*.html")))

    def test_idempotent_import_and_empty_targets(self):
        self.process()
        before = self.dump()
        self.process()
        self.assertEqual(self.dump(), before)
        self.prepare_renderer()
        self.render()
        self.process([])
        self.assertEqual(self.active(), {(watcher.identity(p), "squad") for p in self.squad})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM player_versions").fetchone()[0], 4)
        out = self.render()
        self.assertEqual(self.dashboard(out)["meta"]["targets"], 0)
        self.assertEqual(self.native_data(out, "last"), [])
        self.assertFalse(list((self.root / "saves" / SLUG / "obs").glob("*search-rangers-targets*")))
        self.process()
        self.assertEqual(len(self.active()), 5)

    def test_ambiguous_match_preserves_previous_cohort(self):
        self.process()
        before = self.dump()
        duplicate = dict(self.target, uid="99", unique_id="99")
        self.world.append(duplicate)
        with self.assertRaisesRegex(ValueError, "refusing to replace"):
            self.process([{"Player": self.target["name"], "Age": "27", "Club": "Invented FC"}])
        self.assertEqual(self.dump(), before)

    def test_f9_without_unique_id_matches_names_and_attribute_confirmed_club_mismatch(self):
        # Exporter columns use the in-game display names, not fmsave keys.
        fields = ("Pace", "Acceleration", "Stamina", "Strength", "Anticipation", "Passing")

        def candidate(record, club):
            return {
                "Player": record["name"], "Age": record["age"], "Club": club,
                **{name: record["attributes_" + name.lower()] for name in fields},
            }

        # Same name and age as the target keeper, but a different identity and
        # incompatible attributes. Neither club matches the exported label.
        namesake = dict(self.target_gk, uid="99", unique_id="99", club_name="Other FC")
        for name in fields:
            key = "attributes_" + name.lower()
            namesake[key] = "1"
        self.world.append(namesake)
        candidates = [
            candidate(self.cb, "Rangers"),
            candidate(self.target, "Invented FC"),
            candidate(self.target_gk, "Invented Football Club"),
        ]
        self.process(candidates)
        self.assertEqual(set(watcher.read_csv(self.export)[0]), {"Player", "Age", "Club", *fields})
        self.assertEqual(self.active(), {
            (watcher.identity(self.cb), "squad"),
            (watcher.identity(self.cb), "target"),
            (watcher.identity(self.gk), "squad"),
            (watcher.identity(self.target), "target"),
            (watcher.identity(self.target_gk), "target"),
        })
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM player_versions").fetchone()[0], 4)

    def once_args(self):
        return SimpleNamespace(
            file=None, watch_dir=self.root, pattern="*.fm",
            exports_dir=self.root, export_pattern="f9-*.csv",
            db=self.dbpath, career=CAREER, once=True,
        )

    def test_once_selects_newest_stable_save_and_matching_export(self):
        newer_save = self.root / "newer.fm"
        newer_save.write_bytes(b"newer invented save")
        older_export = self.root / "f9-older.csv"
        newest_export = self.root / "f9-newest.csv"
        ignored_export = self.root / "unrelated.csv"
        for path, timestamp in [(self.source, 100), (newer_save, 200),
                                (older_export, 100), (newest_export, 200),
                                (ignored_export, 300)]:
            if path.suffix == ".csv":
                write_csv(path, self.candidates)
            modified = 1_700_000_000 + timestamp
            os.utime(path, (modified, modified))
        with patch.object(watcher.time, "sleep") as sleep, patch.object(watcher, "process") as process:
            self.assertEqual(watcher.run(self.once_args()), 0)
        sleep.assert_called_once_with(3)
        process.assert_called_once()
        self.assertEqual(process.call_args.args[1:], (newer_save, CAREER, newest_export))

    def test_once_rejects_save_or_export_that_changes_during_stability_wait(self):
        export = self.root / "f9-latest.csv"
        write_csv(export, self.candidates)
        for changing in (self.source, export):
            with self.subTest(changing=changing.name):
                def change_during_wait(seconds):
                    with changing.open("ab") as stream:
                        stream.write(b"changed")

                with patch.object(watcher.time, "sleep", side_effect=change_during_wait), \
                        patch.object(watcher, "process") as process:
                    with self.assertRaisesRegex(RuntimeError, "still being written"):
                        watcher.run(self.once_args())
                process.assert_not_called()

    def test_parser_failure_preserves_previous_cohort(self):
        self.process()
        before = self.dump()
        with patch.object(watcher, "fmsave", side_effect=RuntimeError("invented parser failure")):
            with self.assertRaisesRegex(RuntimeError, "invented parser failure"):
                watcher.process(self.db, self.source, CAREER, self.export)
        self.assertEqual(self.dump(), before)

    def test_invalid_membership_rolls_back_versions(self):
        self.process()
        before = self.dump()
        p = player(90, "Invalid Cohort")
        key = watcher.identity(p)
        with self.assertRaises(sqlite3.IntegrityError):
            watcher.import_selection(self.db, CAREER, self.source, "new", "new",
                                     {"game_date": "2027-01-02"}, {key: p}, {key: {"invalid"}}, self.export)
        self.assertEqual(self.dump(), before)

    def test_keeper_attribute_spelling_and_incomplete_record(self):
        self.assertEqual(bridge.fm_attribute_name("one_on_ones"), "One on Ones")
        self.assertEqual(bridge.fm_attribute_name("command_of_area"), "Command of Area")
        del self.gk["attributes_one_on_ones"]
        self.process()
        self.prepare_renderer()
        result = subprocess.run(
            [sys.executable, str(ROOT / "integrations/rangers/rangers_fm_scoring_bridge.py"),
             "--fm-scoring-root", str(self.root), "--db", str(self.dbpath), "--career", CAREER, "--slug", SLUG],
            cwd=self.root, capture_output=True, encoding="utf-8", errors="replace",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Goalkeeper scoring incomplete", result.stdout)
        self.assertFalse((self.root / "out").exists())

    def test_empty_squad_rejected_without_replacing_membership(self):
        self.process()
        before = self.dump()
        self.squad = []
        with patch.object(watcher, "fmsave", side_effect=self.fake_fmsave):
            with self.assertRaisesRegex(ValueError, "no Rangers players"):
                watcher.process(self.db, self.source, CAREER, self.export)
        self.assertEqual(self.dump(), before)

    def test_incomplete_outfield_has_no_position_score(self):
        person = {"raw": {"name": "Incomplete", "positions_dc": "20", "age": "27"},
                  "cohorts": {"target"}}
        bridge.scored_people([person], MODEL)
        self.assertEqual(person["scores"], dict.fromkeys(MODEL["outfield"]))
        self.assertEqual(person["fit"]["CB"], 20)

    def test_history_tracks_stable_sqlite_key_and_native_dates(self):
        self.process()
        self.prepare_renderer()
        self.render()
        self.game_date = "2027-01-02"
        self.cb["attributes_pace"] = "20"
        self.process()
        key = watcher.identity(self.cb)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM player_versions WHERE player_key=?", (key,)).fetchone()[0], 2)
        out = self.render()
        defender = next(p for p in self.native_data(out, "squad") if p["name"] == self.cb["name"])
        self.assertEqual([p["date"] for p in defender["history"]], [DATE, self.game_date])
        self.assertEqual(defender["history"][-1]["attrs"]["Pace"], 20)

    @unittest.expectedFailure
    def test_known_chronology_unchanged_later_date_blocks_older_import(self):
        self.process()
        self.game_date = "2027-01-03"
        self.process()
        self.game_date = "2027-01-02"
        self.process()
        self.assertEqual(self.db.execute("SELECT MAX(last_seen_game_date) FROM cohort_membership").fetchone()[0], "2027-01-03")

    @unittest.expectedFailure
    def test_known_incoming_loan_is_not_outgoing(self):
        self.cb.update(on_loan="true", loan_parent_club_uid="200")
        self.process()
        self.prepare_renderer()
        out = self.render()
        defender = next(p for p in self.native_data(out, "squad") if p["name"] == self.cb["name"])
        self.assertEqual(defender["loan"], "in")

    @unittest.expectedFailure
    def test_known_namesake_does_not_split_native_history(self):
        self.process()
        self.prepare_renderer()
        self.render()
        self.game_date = "2027-01-02"
        self.target["name"] = self.cb["name"]
        self.process()
        out = self.render()
        defender = next(p for p in self.native_data(out, "squad") if p["name"].startswith(self.cb["name"]))
        self.assertEqual(len(defender["history"]), 2)


if __name__ == "__main__":
    unittest.main()
