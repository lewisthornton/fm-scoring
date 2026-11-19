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
        "on_loan": "false", "loan_parent_club_uid": "",
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
        self.managed = [{"club_uid": "100", "club_name": "Rangers", "club_short_name": "Rangers",
                         "manager_staff_uid": "800"}]
        self.club = [{"uid": "100", "name": "Rangers", "short_name": "Rangers"}]

    def fake_fmsave(self, command, copied_save, *args):
        copied = Path(copied_save)
        self.assertNotEqual(copied, self.source)
        self.assertEqual(copied.read_bytes(), self.source.read_bytes())
        self.copies.append(copied)
        self.commands.append((command, *args))
        if command == "info":
            return json.dumps({"game_date": self.game_date})
        rows = {"managed-clubs": self.managed, "clubs": self.club, "players": self.world}[args[0]]
        write_csv(Path(args[args.index("-o") + 1]), rows)
        return ""

    def process(self, candidates=None):
        self.source.write_bytes(b"invented save bytes " + self.game_date.encode("ascii"))
        candidates = self.candidates if candidates is None else candidates
        write_csv(self.export, candidates or [{"Unique ID": ""}])
        if not candidates:
            self.export.write_text("Unique ID\n", encoding="utf-8")
        with patch.object(watcher, "fmsave", side_effect=self.fake_fmsave):
            return watcher.process(self.db, self.source, CAREER, self.export)

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
                                     {"game_date": "2027-01-02"}, {key: p}, {key: {"invalid"}}, self.export, ("100", "800"))
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
        self.world = [self.target, self.target_gk, self.unselected]
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

    def watermark(self, career=CAREER):
        row = self.db.execute("SELECT latest_game_date FROM career_chronology WHERE career=?", (career,)).fetchone()
        return row[0] if row else None

    def test_known_chronology_unchanged_later_date_blocks_older_import(self):
        self.assertTrue(self.process())
        self.game_date = "2027-01-03"
        self.assertTrue(self.process())
        self.assertEqual(self.watermark(), self.game_date)
        self.assertEqual(self.db.execute("SELECT MAX(game_date) FROM snapshots").fetchone()[0], DATE)
        before = self.dump()
        self.game_date = "2027-01-02"
        # An older save with both changed attributes and a different filter.
        self.cb["attributes_pace"] = "20"
        with patch.object(watcher, "log") as log:
            self.assertFalse(self.process([]))
        self.assertTrue(any("Skipping older rotating save" in call.args[0] for call in log.call_args_list))
        self.assertFalse(any("Accepted:" in call.args[0] for call in log.call_args_list))
        self.assertEqual(self.dump(), before)
        self.assertEqual(self.db.execute("SELECT MAX(last_seen_game_date) FROM cohort_membership").fetchone()[0], "2027-01-03")

    def test_same_date_filters_can_be_reinstated(self):
        self.process([{"Unique ID": "3"}])
        first = self.active()
        self.process([{"Unique ID": "4"}])
        self.assertIn((watcher.identity(self.target_gk), "target"), self.active())
        self.assertNotIn((watcher.identity(self.target), "target"), self.active())
        self.process([])
        self.assertFalse(any(cohort == "target" for _, cohort in self.active()))
        self.process([{"Unique ID": "3"}])
        self.assertEqual(self.active(), first)
        self.assertEqual(self.watermark(), DATE)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM player_versions").fetchone()[0], 4)

    def test_legacy_database_migration_uses_snapshot_and_cohort_evidence(self):
        self.process()
        self.game_date = "2027-01-03"
        self.process([])
        self.db.execute("UPDATE cohort_membership SET last_seen_game_date='2027-01-04' WHERE active=0")
        # Another career has a dated snapshot but no dated membership.
        self.db.execute("""INSERT INTO snapshots
            (career,source_file,source_sha256,selection_sha256,game_date,imported_utc,player_count,changed_count)
            VALUES ('snapshot-only','fixture','hash','filter','2027-02-01','fixture',0,0)""")
        self.db.execute("UPDATE cohort_membership SET last_seen_game_date='invalid' WHERE cohort='squad'")
        self.db.execute("UPDATE cohort_membership SET last_seen_game_date='2027-01-03' WHERE cohort='squad' AND player_key=?",
                        (watcher.identity(self.cb),))
        self.db.execute("DROP TABLE career_chronology")
        self.db.commit()
        before = self.dump()
        with watcher.connect(self.dbpath) as migrated:
            self.assertEqual(dict(migrated.execute("SELECT career,latest_game_date FROM career_chronology")),
                             {CAREER: "2027-01-04", "snapshot-only": "2027-02-01"})
        migrated.close()
        self.assertEqual([line for line in self.dump() if "career_chronology" not in line], before)
        self.game_date = "2027-01-02"
        self.assertFalse(self.process())
        self.assertEqual(self.watermark(), "2027-01-04")
        reopened = watcher.connect(self.dbpath)
        self.addCleanup(reopened.close)
        self.assertEqual(dict(reopened.execute("SELECT career,latest_game_date FROM career_chronology")),
                         {CAREER: "2027-01-04", "snapshot-only": "2027-02-01"})

    def test_career_watermarks_are_independent(self):
        self.process()
        self.game_date = "2027-01-03"
        self.process()
        key = watcher.identity(self.cb)
        result = watcher.import_selection(self.db, "other-career", self.source, "other", "filter",
                                          {"info": {"in_game_date": DATE}}, {key: self.cb}, {key: {"squad"}}, None, ("100", "800"))
        self.assertEqual(result, (1, 1))
        self.assertEqual(self.watermark("other-career"), DATE)
        self.assertEqual(self.watermark(), "2027-01-03")

    def test_missing_and_invalid_dates_never_mutate_database(self):
        self.process()
        before = self.dump()
        key = watcher.identity(self.cb)
        for metadata in ({}, None, {"info": None}, {"game_date": "2027-02-30"}, {"game_date": "20270102"},
                         {"game_date": 20270102}, {"game_date": "2027-01-02T12:00:00"}):
            with self.subTest(metadata=metadata):
                with self.assertRaisesRegex(ValueError, "Missing or invalid game date"):
                    watcher.import_selection(self.db, CAREER, self.source, "new", "filter",
                                             metadata, {key: self.cb}, {key: {"squad"}}, None, ("100", "800"))
                self.assertEqual(self.dump(), before)

    def test_watermark_write_failure_rolls_back_cohort_and_versions(self):
        self.process()
        self.db.execute("""CREATE TRIGGER reject_watermark BEFORE UPDATE ON career_chronology
            BEGIN SELECT RAISE(ABORT, 'invented failure'); END""")
        before = self.dump()
        self.game_date = "2027-01-03"
        self.cb["attributes_pace"] = "20"
        with self.assertRaisesRegex(sqlite3.IntegrityError, "invented failure"):
            self.process([])
        self.assertEqual(self.dump(), before)
        self.assertEqual(self.watermark(), DATE)

    def test_known_incoming_loan_is_not_outgoing(self):
        self.cb.update(on_loan="true", loan_parent_club_uid="200")
        self.process()
        self.prepare_renderer()
        out = self.render()
        defender = next(p for p in self.native_data(out, "squad") if p["name"] == self.cb["name"])
        self.assertEqual(defender["loan"], "in")

    def test_managed_club_binding_and_wrong_club_rejection(self):
        self.process()
        self.assertEqual(self.db.execute("SELECT club_uid,manager_staff_uid FROM career_club WHERE career=?", (CAREER,)).fetchone(),
                         ("100", "800"))
        before = self.dump()
        for managed, club in [
            ([{"club_uid": "200", "club_name": "Invented FC"}], self.club),
            ([{"club_uid": "", "club_name": "Rangers"}], self.club),
            ([{"club_uid": "100", "club_name": "Invented FC", "club_short_name": "Rangers"}], self.club),
            ([], self.club),
            (self.managed * 2, self.club),
            (self.managed, [{"uid": "200", "name": "Rangers"}]),
            ([dict(self.managed[0], manager_staff_uid="801")], self.club),
            ([dict(self.managed[0], club_uid="200")], [{"uid": "200", "name": "Rangers"}]),
        ]:
            with self.subTest(managed=managed, club=club):
                original_managed, original_club = self.managed, self.club
                self.managed, self.club = managed, club
                with self.assertRaises(ValueError):
                    self.process()
                self.managed, self.club = original_managed, original_club
                self.assertEqual(self.dump(), before)

    def test_legacy_career_binding_checks_existing_squad(self):
        self.process()
        self.db.execute("DROP TABLE career_club")
        self.db.commit()
        self.prepare_renderer()
        self.assertEqual(self.dashboard(self.render())["squad_availability"][0]["availability"], "available")
        # Opening an old database creates the additive table without binding it.
        migrated = watcher.connect(self.dbpath)
        migrated.close()
        before = self.dump()
        self.managed[0]["club_uid"] = "200"
        self.club[0]["uid"] = "200"
        with self.assertRaisesRegex(ValueError, "Cannot reconcile"):
            self.process()
        self.assertEqual(self.dump(), before)
        self.managed[0]["club_uid"] = self.club[0]["uid"] = "100"
        self.process()
        self.assertEqual(self.db.execute("SELECT club_uid FROM career_club").fetchone()[0], "100")

    def test_first_import_binding_failure_rolls_back_everything(self):
        self.db.execute("""CREATE TRIGGER reject_club BEFORE INSERT ON career_club
            BEGIN SELECT RAISE(ABORT, 'invented club binding failure'); END""")
        before = self.dump()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "invented club binding failure"):
            self.process()
        self.assertEqual(self.dump(), before)

    def test_unknown_loan_evidence_is_not_available(self):
        for raw in (
            {"club_uid": "100", "on_loan": "true"},
            {"club_uid": "100", "on_loan": "false", "loan_parent_club_uid": "200"},
            {"club_uid": "100", "on_loan": "true", "loan_parent_club_uid": "100"},
            {"club_uid": "", "on_loan": "true", "loan_parent_club_uid": "100"},
        ):
            with self.subTest(raw=raw):
                self.assertEqual(bridge.loan_state(raw, "100"), ("unknown", "unknown"))

    def test_uncertain_incumbents_are_separate_from_confirmed_uplift(self):
        uncertain = player(9, "Fixture Uncertain Defender", squad=True)
        uncertain["on_loan"] = ""
        for name in MODEL["outfield"]["CB"]:
            uncertain["attributes_" + name.lower().replace(" ", "_")] = "20"
        self.world.append(uncertain)
        self.process()
        self.prepare_renderer()
        section = self.dashboard(self.render())["roles"]["CB"]
        self.assertEqual(section["incumbent"]["name"], self.cb["name"])
        self.assertEqual(section["uncertain_incumbents"], [
            {"name": uncertain["name"], "score": 20.0, "fit": 20},
        ])
        target = section["candidates"][0]
        self.assertAlmostEqual(target["uplift"],
                               self.expected_score(self.target, MODEL["outfield"]["CB"]) -
                               self.expected_score(self.cb, MODEL["outfield"]["CB"]), places=3)

        # With no confirmed familiar defender, uplift and its attribute
        # breakdown must remain undefined even when uncertain players score.
        self.game_date = "2027-01-02"
        self.cb["on_loan"] = ""
        self.process()
        out = self.render()
        section = self.dashboard(out)["roles"]["CB"]
        self.assertIsNone(section["incumbent"])
        self.assertEqual({p["name"] for p in section["uncertain_incumbents"]},
                         {self.cb["name"], uncertain["name"]})
        self.assertIsNone(section["candidates"][0]["uplift"])
        self.assertEqual(section["candidates"][0]["attributes"], [])

    def test_uncertain_parent_uid_retains_possible_owned_players(self):
        players = [player(10, "Missing Flag"), player(11, "Conflicting Flag"),
                   player(12, "Invalid Flag"), player(13, "Unrelated Parent")]
        for record, flag in zip(players, ("", "false", "invalid", "")):
            record.update(on_loan=flag, loan_parent_club_uid="100")
        # A name alone cannot establish possible Rangers ownership.
        players[-1].update(loan_parent_club_uid="300", loan_parent_club_name="Rangers")
        self.world.extend(players)
        self.process([])
        for record in players[:-1]:
            self.assertIn((watcher.identity(record), "squad"), self.active())
        self.assertNotIn((watcher.identity(players[-1]), "squad"), self.active())
        self.prepare_renderer()
        out = self.render()
        states = {p["name"]: (p["loan_state"], p["availability"])
                  for p in self.dashboard(out)["squad_availability"]}
        native = {p["name"]: p for p in self.native_data(out, "squad")}
        for record in players[:-1]:
            self.assertEqual(states[record["name"]], ("unknown", "unknown"))
            self.assertEqual(native[record["name"]]["loan"], "unknown")
        self.assertNotIn(players[-1]["name"], states)

    def test_missing_loan_flag_column_preserves_uncertain_parent_uid(self):
        owned = player(10, "Fixture Possible Loan")
        owned["loan_parent_club_uid"] = "100"
        self.world.append(owned)
        for record in self.world:
            del record["on_loan"]
        self.process([])
        self.assertIn((watcher.identity(owned), "squad"), self.active())
        people, _, _ = bridge.get_database(self.dbpath, CAREER)
        self.assertTrue(all(p["availability"] == "unknown" for p in people))

    def test_world_export_timing_and_cleanup_with_and_without_targets(self):
        for candidates in (self.candidates, []):
            with self.subTest(candidates=candidates):
                with patch.object(watcher, "log") as log:
                    self.process(candidates)
                messages = [call.args[0] for call in log.call_args_list]
                self.assertIn("Starting temporary full-world player export", messages)
                self.assertTrue(any(re.fullmatch(
                    r"Temporary full-world player export completed in \d+\.\d{2}s; \d+\.\d{2} MiB \(temporary\)",
                    message) for message in messages))
                self.assertTrue(all(not path.parent.exists() for path in self.copies))
                self.assertNotIn(self.unselected["name"], str(self.dump()))

    def test_loan_availability_and_native_history(self):
        outgoing = player(6, "Fixture Outgoing")
        outgoing.update(on_loan="true", loan_parent_club_uid="100", loan_parent_club_name="Rangers")
        for name in MODEL["outfield"]["CB"]:
            outgoing["attributes_" + name.lower().replace(" ", "_")] = "20"
        incoming = player(7, "Fixture Incoming", squad=True)
        incoming.update(on_loan="true", loan_parent_club_uid="200")
        unknown = player(8, "Fixture Unknown", squad=True)
        unknown.update(on_loan="", loan_parent_club_uid="")
        self.world.extend([outgoing, incoming, unknown])
        self.process([])
        self.prepare_renderer()
        out = self.render()
        report = self.dashboard(out)
        states = {p["name"]: (p["loan_state"], p["availability"]) for p in report["squad_availability"]}
        self.assertEqual(states[self.cb["name"]], ("permanent", "available"))
        self.assertEqual(states[incoming["name"]], ("incoming", "available"))
        self.assertEqual(states[outgoing["name"]], ("outgoing", "unavailable"))
        self.assertEqual(states[unknown["name"]], ("unknown", "unknown"))
        self.assertNotEqual(report["roles"]["CB"]["incumbent"]["name"], outgoing["name"])
        native = {p["name"]: p for p in self.native_data(out, "squad")}
        self.assertEqual(native[outgoing["name"]]["loan"], "out")
        self.assertEqual(native[incoming["name"]]["loan"], "in")
        self.assertEqual(native[unknown["name"]]["loan"], "unknown")
        self.game_date = "2027-01-02"
        outgoing.update(on_loan="false", loan_parent_club_uid="", loan_parent_club_name="",
                        club_uid="100", club_name="Rangers")
        self.process([])
        out = self.render()
        native = {p["name"]: p for p in self.native_data(out, "squad")}
        self.assertIsNone(native[outgoing["name"]]["loan"])
        self.assertEqual(len(native[outgoing["name"]]["history"]), 2)
        key = watcher.identity(outgoing)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM player_versions WHERE player_key=?", (key,)).fetchone()[0], 2)

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
