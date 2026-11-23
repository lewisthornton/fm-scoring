"""Characterisation of the existing Rangers integration using invented data."""
import csv
import hashlib
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
import score as native
import touchline_generation as generation

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
    def test_touchline_generation_contract(self):
        self.process()
        self.prepare_renderer()
        shutil.copyfile(ROOT / "touchline_generation.py", self.root / "touchline_generation.py")
        out = self.render()
        legacy = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
        before = self.dump()
        destination = self.root / "touchline"
        self.render("--publish-generation", str(destination))
        first, indexes = generation.read_current(destination)
        self.assertEqual(self.dump(), before)
        self.assertEqual(legacy, {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()})
        directory = destination / "generations" / first["generation_id"]
        for name in generation.FILES:
            self.assertEqual((directory / name).read_bytes(), legacy[name])
        self.assertEqual(list(indexes["players"]), sorted(indexes["players"]))
        self.assertEqual(indexes, generation.read_generation(directory)[1])
        self.process(candidates=[{"Unique ID": "3"}])
        self.render("--publish-generation", str(destination))
        second, _ = generation.read_current(destination)
        self.assertEqual(first["game_date"], second["game_date"])
        self.assertNotEqual(first["source_sha256"], second["source_sha256"])
        self.assertNotEqual(first["cohort_sha256"], second["cohort_sha256"])
        self.assertEqual(first["source"]["snapshots"], second["source"]["snapshots"])
        self.assertNotEqual(first["generation_id"], second["generation_id"])
        generation.rollback(destination, first["generation_id"])
        self.assertEqual(generation.read_current(destination)[0], first)
        generation.rollback(destination, second["generation_id"])
        second_dir = destination / "generations" / second["generation_id"]
        manifest_path = second_dir / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest_path.write_bytes(manifest_bytes + b"\n")
        with self.assertRaisesRegex(ValueError, "Noncanonical"):
            generation.rollback(destination, second["generation_id"])
        manifest_path.write_bytes(manifest_bytes)
        damaged = second_dir / generation.FILES[0]
        original = damaged.read_bytes()
        damaged.write_bytes(b"{")
        with self.assertRaises(ValueError):
            generation.read_current(destination)
        damaged.write_bytes(original)
        damaged.unlink()
        with self.assertRaises(FileNotFoundError):
            generation.read_current(destination)
        damaged.write_bytes(original)
        self.assertEqual(generation.read_current(destination)[0], second)
        # A matching file hash must not make malformed JSON acceptable.
        damaged.write_bytes(b"{")
        second["files"][generation.FILES[0]].update(bytes=1, sha256=generation.digest(b"{"))
        manifest_path.write_bytes(generation.canonical(second))
        with self.assertRaises(json.JSONDecodeError):
            generation.read_generation(second_dir)
        damaged.write_bytes(original)
        manifest_path.write_bytes(manifest_bytes)

    def test_touchline_interrupted_and_inconsistent_publication(self):
        self.process()
        args = SimpleNamespace(db=self.dbpath, career=CAREER, formation=None)
        evidence = {}
        reports = bridge.build_reports(args, ROOT, provenance=evidence)[:6]
        destination = self.root / "touchline"
        first = generation.publish(destination, reports, evidence)
        with patch.object(generation.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                generation.publish(destination, reports, evidence)
        self.assertEqual(generation.read_current(destination)[0]["generation_id"], first)
        real_replace = generation.os.replace
        with patch.object(generation.os, "replace", side_effect=[PermissionError("locked"), None]) as replace:
            # Exercise the retry without changing the valid pointer.
            generation.replace_pointer(destination, generation.read_current(destination)[0])
            self.assertEqual(replace.call_count, 2)
        self.assertIs(generation.os.replace, real_replace)
        from copy import deepcopy
        for report_index, field, value in ((1, "career", "wrong"), (2, "scoring_model", {}),
                                           (3, "formation", {}), (4, "eligibility_policy", {}),
                                           (5, "baseline", {})):
            changed = deepcopy(reports)
            changed[report_index][field] = value
            with self.assertRaises(ValueError):
                generation.publish(destination, changed, evidence)
        with self.assertRaises(ValueError):
            generation.publish(destination, reports[:-1], evidence)
        changed = deepcopy(reports)
        changed[1]["players"].append(changed[1]["players"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            generation.publish(destination, changed, evidence)
        changed = deepcopy(reports)
        changed[1]["players"][0]["slots"][0]["ip"]["observed_role_suitability"] = 10
        with self.assertRaisesRegex(ValueError, "Unsupported role"):
            generation.publish(destination, changed, evidence)
        changed = deepcopy(reports)
        evaluated = next(c for c in changed[5]["candidates"] if c["depth"]["status"] == "evaluated")
        evaluated["depth"]["same_original_starter_absences"][0]["baseline_without_player"] = {}
        with self.assertRaisesRegex(ValueError, "Signing absence baseline mismatch"):
            generation.publish(destination, changed, evidence)
        self.assertEqual(generation.read_current(destination)[0]["generation_id"], first)

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
        self.league_clubs = []
        self.league_nations = []
        self.league_competitions = []
        self.league_tables = []
        self.league_fixtures = []

    def fake_fmsave(self, command, copied_save, *args):
        copied = Path(copied_save)
        self.assertNotEqual(copied, self.source)
        self.assertEqual(copied.read_bytes(), self.source.read_bytes())
        self.copies.append(copied)
        self.commands.append((command, *args))
        if command == "info":
            return json.dumps({"game_date": self.game_date})
        output = Path(args[args.index("-o") + 1])
        if args[0] == "league-tables":
            output.write_text(json.dumps(self.league_tables), encoding="utf-8")
        else:
            rows = {"managed-clubs": self.managed, "clubs": self.league_clubs if "--nation" in args else self.club,
                    "players": self.world, "nations": self.league_nations,
                    "competitions": self.league_competitions, "fixtures": self.league_fixtures}[args[0]]
            write_csv(output, rows)
        return ""

    def process(self, candidates=None, **kwargs):
        self.source.write_bytes(b"invented save bytes " + self.game_date.encode("ascii"))
        candidates = self.candidates if candidates is None else candidates
        write_csv(self.export, candidates or [{"Unique ID": ""}])
        if not candidates:
            self.export.write_text("Unique ID\n", encoding="utf-8")
        with patch.object(watcher, "fmsave", side_effect=self.fake_fmsave):
            return watcher.process(self.db, self.source, CAREER, self.export, **kwargs)

    def dump(self):
        return list(self.db.iterdump())

    def active(self):
        return set(self.db.execute("SELECT player_key, cohort FROM cohort_membership WHERE active=1"))

    def prepare_renderer(self):
        for name in ("score.py", "scoring.py", "formation.py", "tactical_assessment.py", "league_benchmarks.py", "optimal_xi.py", "squad_depth.py", "signing_simulations.py", "template.html", "charts.html", "theme.css"):
            shutil.copyfile(ROOT / name, self.root / name)
        shutil.copytree(ROOT / "weights", self.root / "weights")
        shutil.copytree(ROOT / "formations", self.root / "formations")

    def render(self, *extra):
        result = subprocess.run(
            [sys.executable, str(ROOT / "integrations/rangers/rangers_fm_scoring_bridge.py"),
             "--fm-scoring-root", str(self.root), "--db", str(self.dbpath),
             "--career", CAREER, "--slug", SLUG, *extra],
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

    def test_standalone_bridge_uses_explicit_checkout_and_default_database(self):
        self.process()
        self.prepare_renderer()
        out = self.render()
        expected = {p.name: p.read_bytes() for p in out.glob("*.html")}
        expected_formation = (out / "formation.json").read_bytes()
        expected_assessments = (out / "tactical_assessments.json").read_bytes()
        expected_benchmarks = (out / "league_benchmarks.json").read_bytes()
        expected_xi = (out / "optimal_xi.json").read_bytes()
        expected_depth = (out / "squad_depth.json").read_bytes()
        expected_signings = (out / "signing_simulations.json").read_bytes()
        launcher = self.root / "FMAnalytics"
        launcher.mkdir()
        for name in ("rangers_fm_scoring_bridge.py", "rangers_club.py"):
            shutil.copyfile(ROOT / "integrations/rangers" / name, launcher / name)
        # Model the standalone Windows installation with its database beside
        # the launcher and the scoring module only in the selected checkout.
        standalone_db = launcher / "fm_rangers_scoped.sqlite3"
        copy = sqlite3.connect(standalone_db)
        try:
            self.db.backup(copy)
        finally:
            copy.close()
        before = standalone_db.read_bytes()
        command = [
            sys.executable, str(launcher / "rangers_fm_scoring_bridge.py"),
            "--fm-scoring-root", str(self.root), "--career", CAREER, "--slug", SLUG,
        ]
        result = subprocess.run(command, cwd=launcher, capture_output=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({p.name: p.read_bytes() for p in out.glob("*.html")}, expected)
        self.assertEqual((out / "formation.json").read_bytes(), expected_formation)
        self.assertEqual((out / "tactical_assessments.json").read_bytes(), expected_assessments)
        self.assertEqual((out / "league_benchmarks.json").read_bytes(), expected_benchmarks)
        self.assertEqual((out / "optimal_xi.json").read_bytes(), expected_xi)
        self.assertEqual((out / "squad_depth.json").read_bytes(), expected_depth)
        self.assertEqual((out / "signing_simulations.json").read_bytes(), expected_signings)
        self.assertEqual(standalone_db.read_bytes(), before)

        # An unrelated module beside the launcher must not shadow the selected
        # checkout's scorer. A missing checkout module must fail explicitly.
        (launcher / "scoring.py").write_text("raise AssertionError('wrong scorer')\n", encoding="utf-8")
        (launcher / "formation.py").write_text("raise AssertionError('wrong formation module')\n", encoding="utf-8")
        (launcher / "tactical_assessment.py").write_text("raise AssertionError('wrong assessment module')\n", encoding="utf-8")
        (launcher / "league_benchmarks.py").write_text("raise AssertionError('wrong benchmark module')\n", encoding="utf-8")
        (launcher / "optimal_xi.py").write_text("raise AssertionError('wrong XI module')\n", encoding="utf-8")
        (launcher / "squad_depth.py").write_text("raise AssertionError('wrong depth module')\n", encoding="utf-8")
        (launcher / "signing_simulations.py").write_text("raise AssertionError('wrong signing module')\n", encoding="utf-8")
        result = subprocess.run(command, cwd=launcher, capture_output=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({p.name: p.read_bytes() for p in out.glob("*.html")}, expected)
        self.assertEqual((out / "formation.json").read_bytes(), expected_formation)
        self.assertEqual((out / "tactical_assessments.json").read_bytes(), expected_assessments)
        self.assertEqual((out / "league_benchmarks.json").read_bytes(), expected_benchmarks)
        self.assertEqual((out / "optimal_xi.json").read_bytes(), expected_xi)
        self.assertEqual((out / "squad_depth.json").read_bytes(), expected_depth)
        self.assertEqual((out / "signing_simulations.json").read_bytes(), expected_signings)
        (self.root / "scoring.py").rename(self.root / "scoring.disabled")
        result = subprocess.run(command, cwd=launcher, capture_output=True, encoding="utf-8", errors="replace")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Shared scoring module missing", result.stdout)
        self.assertEqual({p.name: p.read_bytes() for p in out.glob("*.html")}, expected)
        self.assertEqual(standalone_db.read_bytes(), before)

    def test_benchmark_capture_reuses_world_export_and_scopes_aggregate(self):
        from datetime import date, timedelta
        import formation

        self.assertEqual({k: set(v) for k, v in formation.PROFILE_POSITION_CODES.items()}, {k: set(v) for k, v in bridge.POSITION_CODES.items()})

        self.prepare_renderer()
        self.club[0]["nation_id"] = "7"
        self.league_clubs = [{"uid": str(i), "nation_id": "7"} for i in range(100, 112)]
        self.league_nations = [{"nation_id": "7", "database_id": "793"}]
        self.league_competitions = [{"id": "500", "database_id": "9000", "name": ""}]
        self.league_tables = [{"competition_id": "500", "rows": [
            {"club_uid": str(i), "team_slot": 0} for i in range(100, 112)]}]
        self.league_fixtures = [
            {"competition_id": "500", "season_start_year": "2026",
             "date": (date(2026, 8, 1) + timedelta(days=index * 12)).isoformat(),
             "home_club_uid": str(uid) if away else "100", "away_club_uid": "100" if away else str(uid),
             "home_team_slot": 0, "away_team_slot": 0, "stage_id": "500", "round": "", "round_code": ""}
            for index, (away, uid) in enumerate((away, uid) for away in (False, True) for uid in range(101, 112))]
        (self.root / "leagues").mkdir()
        (self.root / "leagues/divisions.toml").write_text('[nations]\n793 = "SCO"\n', encoding="utf-8")
        names = self.root / "competition-names.csv"
        write_csv(names, [{"database_id": "9000", "name": "Scottish Premiership (invented ID)"}])
        for record in self.squad:
            record["team_slot"] = "0"
        for club in range(101, 112):
            for i in range(4):
                keeper = i >= 2
                record = player(1000 + club * 10 + i, f"Unselected league player {club}-{i}", keeper=keeper)
                record.update(club_uid=str(club), team_slot="0")
                for code in formation.FM_POSITION_CODES:
                    record["positions_" + code] = "20" if (code == "gk") == keeper else "1"
                self.world.append(record)
        self.process(benchmark_root=self.root, benchmark_names=names)
        out = self.render()
        path = out / "league_benchmarks.json"
        first = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(first["status"], "available")
        self.assertEqual(first["competition"]["league_nation_code"], "SCO")
        self.assertEqual(first["competition"]["display_name"], "Scottish Premiership (invented ID)")
        self.assertEqual(first["season_start_year"], 2026)
        self.assertEqual(first["reference"]["profiles"]["CB"]["sample_size"], 23)
        self.assertEqual(first["reference"]["profiles"]["GK"]["sample_size"], 23)
        expected_ids = {json.dumps(["rangers", CAREER, watcher.identity(p)], separators=(",", ":"))
                        for p in (self.cb, self.gk, self.target, self.target_gk)}
        self.assertEqual({c["player_id"] for c in first["comparisons"]}, expected_ids)
        defender_id = json.dumps(["rangers", CAREER, watcher.identity(self.cb)], separators=(",", ":"))
        defender = next(c for c in first["comparisons"] if c["player_id"] == defender_id and c["profile"] == "CB")
        native_defender = next(c for c in first["native_comparisons"] if c["player_id"] == defender_id and c["profile"] == "CB" and c["native_position"] == "dc")
        self.assertEqual(native_defender["reference_population"], "native_position")
        self.assertEqual(defender["status"], "available")
        self.assertEqual(defender["attribute_profile_score"], self.expected_score(self.cb, MODEL["outfield"]["CB"]))
        xi = json.loads((out / "optimal_xi.json").read_text(encoding="utf-8"))
        assigned_defender = next(r for r in xi["assignments"] if r["player_id"] == defender_id)
        self.assertEqual(assigned_defender["league_benchmark"]["percentile"], native_defender["percentile"])
        self.assertEqual(assigned_defender["league_benchmark"]["native_position"], "dc")
        depth = json.loads((out / "squad_depth.json").read_text(encoding="utf-8"))
        edge = next(e for row in depth["coverage"] if row["slot_id"] == assigned_defender["slot_id"]
                    for e in row["eligible_players"] if e["player_id"] == defender_id)
        self.assertEqual(edge["league"]["comparison"]["percentile"], native_defender["percentile"])
        self.assertEqual(edge["league"]["comparison"]["contributing_clubs"], first["reference"]["native_profiles"]["CB:dc"]["contributing_clubs"])
        self.assertNotIn("Unselected league player", path.read_text(encoding="utf-8"))
        self.assertNotIn("Unselected league player", str(self.dump()))
        self.assertEqual(sum(c[:2] == ("export", "players") for c in self.commands), 1)
        self.assertTrue(all(not p.parent.exists() for p in self.copies))
        same = path.read_bytes()
        self.render()
        self.assertEqual(path.read_bytes(), same)
        metadata_reads = sum(c[:2] == ("export", "league-tables") for c in self.commands)
        self.process(benchmark_root=self.root, benchmark_names=names)
        self.assertEqual(sum(c[:2] == ("export", "league-tables") for c in self.commands), metadata_reads)
        # An aggregate from the pre-review detector must not bypass the new
        # competition gate even when the save hash and game date are identical.
        old_cache = json.loads(self.db.execute("SELECT aggregate_json FROM career_benchmark WHERE career=?", (CAREER,)).fetchone()[0])
        old_cache.pop("detection_policy")
        self.db.execute("UPDATE career_benchmark SET aggregate_json=? WHERE career=?", (json.dumps(old_cache), CAREER))
        self.db.commit()
        self.render()
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["reason"], "benchmark_detection_requires_refresh")
        self.process(benchmark_root=self.root, benchmark_names=names)
        self.assertEqual(sum(c[:2] == ("export", "league-tables") for c in self.commands), metadata_reads + 1)

        self.game_date = "2027-01-03"
        # Simulate the FM27 export omitting the league table entirely. The
        # fixture-only provenance changes, but the aggregate is still valid.
        self.league_tables = []
        self.process(benchmark_root=self.root, benchmark_names=names)
        self.render()
        later = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(later["game_date"], "2027-01-03")
        self.assertEqual(later["extraction_game_date"], DATE)
        self.assertEqual(later["reference"], first["reference"])
        self.assertEqual(later["detection"]["method"], "automatic_fixture_led")
        self.assertTrue(later["detection"]["evidence"]["league_tables_missing"])
        self.assertIn("competition_inferred_from_fixtures_without_complete_tables", later["warnings"])
        self.assertEqual(later["provenance"]["reference_save_sha256"], first["provenance"]["reference_save_sha256"])
        self.assertTrue(any("reference_extracted_on_earlier_game_date" in c["warnings"] for c in later["comparisons"]))
        evidence = {}
        reports = bridge.build_reports(SimpleNamespace(db=self.dbpath, career=CAREER, formation=None), self.root, provenance=evidence)[:6]
        destination = self.root / "touchline"
        generation.publish(destination, reports, evidence)
        published, _ = generation.read_current(destination)
        self.assertEqual(published["benchmark"]["extraction_game_date"], DATE)
        from copy import deepcopy
        stale = deepcopy(reports)
        stale[2]["extraction_game_date"] = "2026-10-01"
        with self.assertRaisesRegex(ValueError, "Stale benchmark"):
            generation.publish(destination, stale, evidence)
        self.assertEqual(generation.read_current(destination)[0], published)
        self.game_date = "2027-02-01"
        self.process(benchmark_root=self.root, benchmark_names=names)
        self.render()
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["extraction_game_date"], self.game_date)

        # A different career with overlapping IDs has no cached benchmark.
        key = watcher.identity(self.cb)
        watcher.import_selection(self.db, "other-career", self.source, "other", "filter",
                                 {"game_date": DATE}, {key: self.cb}, {key: {"squad"}}, None, ("100", "800"))
        self.render("--career", "other-career", "--slug", "other-benchmark")
        other_path = self.root / "out/other-benchmark/league_benchmarks.json"
        other = json.loads(other_path.read_text(encoding="utf-8"))
        self.assertEqual(other["reason"], "benchmark_not_captured")
        self.assertTrue(all(json.loads(c["player_id"])[1] == "other-career" for c in other["comparisons"]))

    def test_selected_formation_sidecar_preserves_all_dashboard_outputs(self):
        self.process()
        self.prepare_renderer()
        out = self.render()
        default = json.loads((out / "formation.json").read_text(encoding="utf-8"))
        default_assessment = json.loads((out / "tactical_assessments.json").read_text(encoding="utf-8"))
        self.assertEqual(default["name"], "Conventional 4-3-3")
        old_html = {p.name: p.read_bytes() for p in out.glob("*.html") if p.stem not in ("optimal_xi", "squad_depth", "signing_simulations")}
        self.render("--formation", str(self.root / "formations" / "asymmetric-4231.toml"))
        selected = json.loads((out / "formation.json").read_text(encoding="utf-8"))
        assessment = json.loads((out / "tactical_assessments.json").read_text(encoding="utf-8"))
        self.assertNotEqual(assessment["formation"]["sha256"], default_assessment["formation"]["sha256"])
        self.assertEqual(assessment["formation"]["name"], selected["name"])
        right_back = next(s for s in assessment["players"][0]["slots"] if s["slot_id"] == "rb")
        self.assertEqual((right_back["ip"]["position"], right_back["oop"]["position"]), ("dc", "dr"))
        self.assertEqual(selected["name"], "Asymmetric 4-2-3-1")
        self.assertEqual(len(selected["slots"]), 11)
        self.assertEqual({p.name: p.read_bytes() for p in out.glob("*.html") if p.stem not in ("optimal_xi", "squad_depth", "signing_simulations")}, old_html)
        xi = json.loads((out / "optimal_xi.json").read_text(encoding="utf-8"))
        self.assertEqual(xi["formation"], assessment["formation"])
        before = (out / "formation.json").read_bytes()
        before_assessment = (out / "tactical_assessments.json").read_bytes()
        self.render("--formation", str(self.root / "formations" / "asymmetric-4231.toml"))
        self.assertEqual((out / "formation.json").read_bytes(), before)
        self.assertEqual((out / "tactical_assessments.json").read_bytes(), before_assessment)

        # Invalid input must leave the previous valid generated output intact.
        invalid = self.root / "formations" / "invalid.toml"
        invalid.write_text("version = 99\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "integrations/rangers/rangers_fm_scoring_bridge.py"),
             "--fm-scoring-root", str(self.root), "--db", str(self.dbpath),
             "--career", CAREER, "--slug", SLUG, "--formation", str(invalid)],
            cwd=self.root, capture_output=True, encoding="utf-8", errors="replace",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Formation", result.stdout)
        self.assertEqual((out / "formation.json").read_bytes(), before)
        self.assertEqual((out / "tactical_assessments.json").read_bytes(), before_assessment)
        self.assertEqual({p.name: p.read_bytes() for p in out.glob("*.html") if p.stem not in ("optimal_xi", "squad_depth", "signing_simulations")}, old_html)

    def test_tactical_assessment_scoped_identity_availability_and_provenance(self):
        self.target["name"] = self.cb["name"]
        self.cb.update(positions_dl="20", positions_dr="4")
        self.target.update(positions_dr="20", positions_dc="2")
        incoming = player(30, "Fixture Incoming", squad=True)
        incoming.update(on_loan="true", loan_parent_club_uid="200")
        outgoing = player(31, "Fixture Outgoing")
        outgoing.update(on_loan="true", loan_parent_club_uid="100")
        unknown = player(32, "Fixture Unknown", squad=True)
        unknown.update(on_loan="")
        self.world.extend([incoming, outgoing, unknown])
        self.process()
        self.game_date = "2027-01-03"
        self.process()
        # Same numeric identity in a separate career may never leak into this report.
        other = dict(self.cb, name="Other career private name")
        key = watcher.identity(other)
        watcher.import_selection(self.db, "other-career", self.source, "other", "filter",
                                 {"game_date": DATE}, {key: other}, {key: {"squad"}}, None, ("100", "800"))
        before = self.dump()
        self.prepare_renderer()
        out = self.render("--formation", str(self.root / "formations" / "asymmetric-4231.toml"))
        path = out / "tactical_assessments.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["career"], CAREER)
        self.assertEqual(data["game_date"], self.game_date)
        self.assertIsNone(data["observed_role_suitability_source"])
        model_bytes = (self.root / "weights/fm27v2.toml").read_bytes()
        self.assertEqual(data["scoring_model"]["sha256"], hashlib.sha256(model_bytes).hexdigest())
        selected = json.loads((out / "formation.json").read_text(encoding="utf-8"))
        canonical = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.assertEqual(data["formation"]["sha256"], hashlib.sha256(canonical.encode("utf-8")).hexdigest())
        expected = {json.dumps(["rangers", CAREER, watcher.identity(p)], separators=(",", ":"))
                    for p in self.world if p is not self.unselected}
        self.assertEqual({p["player_id"] for p in data["players"]}, expected)
        self.assertEqual(len(data["players"]), 7)
        namesakes = [p for p in data["players"] if p["name"] == self.cb["name"]]
        self.assertEqual(len(namesakes), 2)
        self.assertEqual(len({p["display_name"] for p in namesakes}), 2)
        self.assertTrue(all(p["record_game_date"] == DATE and p["last_seen_game_date"] == self.game_date
                            for p in data["players"]))
        states = {p["name"]: (p["availability"], p["loan_state"]) for p in data["players"]}
        self.assertEqual(states[incoming["name"]], ("available", "incoming"))
        self.assertEqual(states[outgoing["name"]], ("unavailable", "outgoing"))
        self.assertEqual(states[unknown["name"]], ("unknown", "unknown"))
        defender = next(p for p in data["players"] if json.loads(p["player_id"])[2] == watcher.identity(self.cb))
        cb_slot = next(s for s in defender["slots"] if s["slot_id"] == "lcb")
        self.assertEqual(cb_slot["attribute_profile_score"], self.expected_score(self.cb, MODEL["outfield"]["CB"]))
        keeper = next(p for p in data["players"] if p["name"] == self.gk["name"])
        gk_slot = next(s for s in keeper["slots"] if s["slot_id"] == "gk")
        self.assertEqual(gk_slot["attribute_profile_score"], self.expected_score(self.gk, MODEL["gk"]))
        for p in data["players"]:
            self.assertEqual(len(p["slots"]), 11)
            self.assertTrue(all(s["player_id"] == p["player_id"] and s["availability"] == p["availability"]
                                for s in p["slots"]))
        self.assertNotIn(self.unselected["name"], path.read_text(encoding="utf-8"))
        self.assertNotIn(other["name"], path.read_text(encoding="utf-8"))
        xi_path = out / "optimal_xi.json"
        xi = json.loads(xi_path.read_text(encoding="utf-8"))
        assigned = {r["player_id"] for r in xi["assignments"] if r["player_id"]}
        rejected = {r["player_id"] for r in xi["excluded_or_uncertain_players"]}
        self.assertEqual(assigned | rejected, expected)
        self.assertTrue(all(json.loads(key)[1] == CAREER for key in assigned | rejected))
        self.assertIn(json.dumps(["rangers", CAREER, watcher.identity(incoming)], separators=(",", ":")), assigned)
        self.assertNotIn(self.unselected["name"], xi_path.read_text(encoding="utf-8"))
        self.assertNotIn(other["name"], xi_path.read_text(encoding="utf-8"))
        before_xi = xi_path.read_bytes()
        depth_path = out / "squad_depth.json"
        before_depth = depth_path.read_bytes()
        signing_path = out / "signing_simulations.json"
        before_signings = signing_path.read_bytes()
        signings = json.loads(before_signings)
        self.assertEqual(signings["career"], CAREER)
        self.assertEqual({e["player_id"] for e in signings["candidates"]}, {p["player_id"] for p in data["players"] if "target" in p["cohorts"]})
        self.assertNotIn(self.unselected["name"], before_signings.decode("utf-8"))
        self.assertNotIn(other["name"], before_signings.decode("utf-8"))
        depth = json.loads(before_depth)
        self.assertEqual(depth["baseline"], xi)
        for report in (xi, depth, signings):
            for key in ("career", "game_date", "formation", "scoring_model"):
                self.assertEqual(report[key], data[key])
            self.assertEqual(report["eligibility_policy"], xi["eligibility_policy"])
        self.assertEqual(xi["eligibility_policy"]["version"], 2)
        self.assertTrue(data["source_data"]["may_include_unscouted_attributes"])
        self.assertFalse(signings["scenario_assumptions"]["registration_established"])
        for row in xi["assignments"]:
            self.assertEqual(row["selection_position"], next(s["selection_position"] for s in selected["slots"] if s["id"] == row["slot_id"]))
        self.assertNotIn(self.unselected["name"], before_depth.decode("utf-8"))
        self.assertNotIn(other["name"], before_depth.decode("utf-8"))
        for row in depth["coverage"]:
            self.assertTrue(all(json.loads(e["player_id"])[1] == CAREER for e in row["eligible_players"]))
        self.render("--formation", str(self.root / "formations" / "asymmetric-4231.toml"))
        self.assertEqual(xi_path.read_bytes(), before_xi)
        self.assertEqual(depth_path.read_bytes(), before_depth)
        self.assertEqual(signing_path.read_bytes(), before_signings)
        self.render("--formation", str(self.root / "formations" / "asymmetric-4231.toml"), "--signing-depth-limit", "0")
        limited = json.loads(signing_path.read_bytes())
        self.assertEqual(limited["depth_evaluated_count"], 0)
        self.assertEqual({e["player_id"]: e["xi"] for e in limited["candidates"]}, {e["player_id"]: e["xi"] for e in signings["candidates"]})
        self.assertEqual(xi_path.read_bytes(), before_xi)
        self.assertEqual(depth_path.read_bytes(), before_depth)
        self.assertEqual(self.dump(), before)

    def test_watch_signature_tracks_formation_changes(self):
        path = self.root / "chosen.toml"
        path.write_text("invented", encoding="utf-8")
        weights = self.root / "weights.toml"
        before = bridge.signatures(self.dbpath, weights, path)
        path.write_text("different length", encoding="utf-8")
        self.assertNotEqual(bridge.signatures(self.dbpath, weights, path), before)

    def test_xi_policy_cli_and_watch_signature(self):
        self.process()
        self.prepare_renderer()
        policy = self.root / "xi-policy.json"
        policy.write_text('{"version":1,"minimum_familiarity":20}', encoding="utf-8")
        weights = self.root / "weights/fm27v2.toml"
        before = bridge.signatures(self.dbpath, weights, xi_policy=policy)
        out = self.render("--xi-policy", str(policy))
        result = json.loads((out / "optimal_xi.json").read_text(encoding="utf-8"))
        self.assertEqual(result["eligibility_policy"]["minimum_familiarity"], 20)
        policy.write_text('{"version":1,"minimum_familiarity":15,"allow_category_evidence":false}', encoding="utf-8")
        self.assertNotEqual(bridge.signatures(self.dbpath, weights, xi_policy=policy), before)
        self.render("--xi-policy", str(policy))
        result = json.loads((out / "optimal_xi.json").read_text(encoding="utf-8"))
        self.assertFalse(result["eligibility_policy"]["allow_category_evidence"])

    def test_xi_empty_career_is_infeasible_without_legacy_pages(self):
        self.process()
        self.prepare_renderer()
        result = subprocess.run([sys.executable, str(ROOT / "integrations/rangers/rangers_fm_scoring_bridge.py"),
                                 "--fm-scoring-root", str(self.root), "--db", str(self.dbpath),
                                 "--career", "absent-career", "--slug", SLUG], cwd=self.root, capture_output=True, encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No active squad or targets", result.stdout)
        out = self.root / "out" / SLUG
        self.assertEqual({p.name for p in out.iterdir()}, {"optimal_xi.json", "optimal_xi.html", "squad_depth.json", "squad_depth.html", "signing_simulations.json", "signing_simulations.html"})
        xi = json.loads((out / "optimal_xi.json").read_text(encoding="utf-8"))
        self.assertEqual(xi["solver"]["status"], "infeasible")
        self.assertIsNone(xi["game_date"])
        self.assertEqual(xi["excluded_or_uncertain_players"], [])

    def test_frozen_generated_output_parity(self):
        # Multiple outfield and goalkeeper targets exercise candidate ordering.
        self.world.extend([player(20, "Fixture Alternate Defender"),
                           player(21, "Fixture Alternate Keeper", keeper=True)])
        self.candidates.extend([{"Unique ID": "20"}, {"Unique ID": "21"}])
        self.process()
        self.prepare_renderer()
        out = self.render()

        def normalise(value):
            # Python 3.12 changed floating-point sum; allow only tiny
            # platform rounding differences while preserving list order.
            if isinstance(value, float):
                return round(value, 9) or 0.0
            if isinstance(value, dict):
                return {key: normalise(item) for key, item in value.items()}
            if isinstance(value, list):
                return [normalise(item) for item in value]
            return value

        actual = {}
        identified = {}
        expected_ids = {p["name"]: json.dumps(["rangers", CAREER, watcher.identity(p)], separators=(",", ":"))
                        for p in self.world if p is not self.unselected}
        for path in sorted(out.glob("*.html")):
            if path.stem in ("optimal_xi", "squad_depth", "signing_simulations"):
                continue  # new independent view; all original frozen hashes remain unchanged
            body = path.read_text(encoding="utf-8")
            if path.stem == "recruitment":
                payload = self.dashboard(out)
            elif path.stem == "charts":
                payload = json.loads(re.search(r"HOME_DIVISION \} = (.*?);\n", body).group(1))
            else:
                payload = {name: json.loads(re.search(rf"const {name} = (.*?);", body).group(1))
                           for name in ("DATA", "COLS", "WEIGHTS", "WIN", "PTS", "BATCHES")}
                payload["SITE"] = json.loads(re.search(r", SITE = (.*?), PAGES = SITE.pages;", body).group(1))
            canonical = json.dumps(normalise(payload), sort_keys=True, separators=(",", ":"))
            identified[path.stem] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            # The only new fields on the unambiguous fixture are an opaque
            # player ID and the observed name on each historical player row.
            # Verify both before comparing the complete old payload exactly.
            if path.stem in ("squad", "players", "last"):
                for row in payload["DATA"]:
                    self.assertEqual(row.pop("player_id"), expected_ids[row["name"]])
                    for snap in row["history"]:
                        self.assertEqual(snap.pop("name"), row["name"])
            canonical = json.dumps(normalise(payload), sort_keys=True, separators=(",", ":"))
            actual[path.stem] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        # Frozen on feature/rangers-integration before extracting scoring.py.
        self.assertEqual(actual, {
            "charts": "79b44edf144b3e5c39381809432f4030fa25dab665a99f64732b462a91a8b16b",
            "filters": "ac2f7c2c6d77f2446f386fa2f3384586546008efc9ca2e9422a34d30caa624e4",
            "last": "6554706a5fa64909203cb6d832437c139c99828c672af7562fbecb7e33bbf932",
            "last_staff": "1b88049df299a47de4ec81941b84204684cf25a02d4d81edd72b99f642c51dab",
            "players": "af18ac050e71b3ecb41ebb71b937ace806406c2c1e9edbd1f9e2cb283417f130",
            "recruitment": "a420a8f4e2cac3243c8a7637de83d0c8fee5bdde1cd26482e479f241647015d6",
            "squad": "daaf13543eb10be4e043835695a2c1e1f90969e6621ee5eb4679c9c7bc8d4871",
            "staff": "1b88049df299a47de4ec81941b84204684cf25a02d4d81edd72b99f642c51dab",
        })
        self.assertEqual(identified, {
            **{page: digest for page, digest in actual.items() if page not in ("last", "players", "squad")},
            "last": "dac6098d2a963c2d6ed5dfc986533a3028edbc190c5db086699e7736f8eb02d0",
            "players": "b48066a9835d5fe9b3e0edf3985eaaffc31416330420c95c86cb0ef261fff955",
            "squad": "4a1876af70d8193a06ef3c4df0fe1b07c05643cec68c85f3343fa84ffe8d9dc7",
        })

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
                         {"squad", "players", "last", "staff", "last_staff", "charts", "filters", "recruitment", "optimal_xi", "squad_depth", "signing_simulations"})
        xi = json.loads((out / "optimal_xi.json").read_text(encoding="utf-8"))
        self.assertEqual(xi["solver"]["status"], "incomplete")
        self.assertEqual({r["display_name"] for r in xi["assignments"] if r["player_id"]}, {self.cb["name"], self.gk["name"]})
        depth = json.loads((out / "squad_depth.json").read_text(encoding="utf-8"))
        self.assertEqual(depth["baseline"], xi)
        self.assertEqual(len(depth["starter_loss_scenarios"]), 2)
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
        out = self.root / "out" / SLUG
        self.assertEqual({p.name for p in out.iterdir()}, {"optimal_xi.html", "optimal_xi.json", "squad_depth.html", "squad_depth.json", "signing_simulations.json", "signing_simulations.html"})
        xi = json.loads((out / "optimal_xi.json").read_text(encoding="utf-8"))
        self.assertIsNone(next(r for r in xi["assignments"] if r["profile"] == "GK")["player_id"])

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
        target = next(p for p in self.native_data(out, "last") if p["name"] == self.cb["name"])
        self.assertNotEqual(defender["player_id"], target["player_id"])
        self.assertNotEqual(defender["display_name"], target["display_name"])
        self.assertEqual(len(target["history"]), 2)
        self.game_date = "2027-01-03"
        self.process([])
        out = self.render()
        defender_after = next(p for p in self.native_data(out, "squad") if p["player_id"] == defender["player_id"])
        self.assertEqual([h["date"] for h in defender_after["history"]], [DATE, "2027-01-02", "2027-01-03"])
        self.assertEqual(self.native_data(out, "last"), [])

    def test_target_signing_transfer_and_rename_preserve_history(self):
        self.process()
        self.prepare_renderer()
        first = next(p for p in self.native_data(self.render(), "last") if p["name"] == self.target["name"])
        self.game_date = "2027-01-02"
        self.target.update(club_uid="100", club_name="Rangers", name="Renamed Defender", attributes_pace="20")
        self.process()
        out = self.render()
        signed = next(p for p in self.native_data(out, "squad") if p["player_id"] == first["player_id"])
        self.assertEqual(signed["name"], "Renamed Defender")
        self.assertEqual([h["name"] for h in signed["history"]], [first["name"], signed["name"]])
        self.assertEqual([h["club"] for h in signed["history"]], ["Invented FC", "Rangers"])
        self.assertEqual(signed["history"][0]["CB"], first["CB"])
        self.assertAlmostEqual(signed["CB"], self.expected_score(self.target, MODEL["outfield"]["CB"]))
        self.assertNotIn(first["player_id"], {p["player_id"] for p in self.native_data(out, "last")})
        self.game_date = "2027-01-03"
        self.target.update(club_uid="300", club_name="Other Invented FC")
        self.process()
        out = self.render()
        moved = next(p for p in self.native_data(out, "players") if p["player_id"] == first["player_id"])
        self.assertEqual([h["date"] for h in moved["history"]], [DATE, "2027-01-02", "2027-01-03"])
        self.assertEqual(moved["history"][-1]["club"], "Other Invented FC")

    def test_bridge_identity_is_career_scoped(self):
        self.process()
        key = watcher.identity(self.cb)
        watcher.import_selection(self.db, "other-career", self.source, "other", "filter",
                                 {"game_date": DATE}, {key: self.cb}, {key: {"squad"}}, None, ("100", "800"))
        first = next(p for p in bridge.get_database(self.dbpath, CAREER)[0] if p["key"] == key)
        second, = bridge.get_database(self.dbpath, "other-career")[0]
        self.assertEqual(first["key"], second["key"])
        self.assertNotEqual(first["player_id"], second["player_id"])
        self.assertEqual(json.loads(first["player_id"]), ["rangers", CAREER, key])
        self.assertEqual(json.loads(second["player_id"]), ["rangers", "other-career", key])

    def test_native_save_identity_is_save_scoped_and_independent_of_name(self):
        first = native.save_player_id("career-a", self.cb)
        renamed = dict(self.cb, name="Renamed", club_uid="999", club_name="Other FC")
        self.assertEqual(native.save_player_id("career-a", renamed), first)
        self.assertNotEqual(native.save_player_id("career-b", self.cb), first)
        self.assertNotEqual(native.save_player_id("career-a", self.target), first)
        self.assertEqual(native.save_player_id("career-a", {}), "")

    def test_legacy_screenshot_aliases_and_blank_identity_preserve_name_history(self):
        folder = self.root / "observations"
        folder.mkdir()
        attrs = dict.fromkeys(MODEL["outfield"]["CB"], 12)
        write_csv(folder / "2027-01-01_my-club_outfield.csv",
                  [{"Name": "Short Name", "Club": "Rangers", "Age": "25", **attrs}])
        write_csv(folder / "2027-01-02_my-club_outfield.csv",
                  [{"Name": "Full Name", "Player ID": "", "Club": "Rangers", "Age": "25", "Pace": 18}])
        players, files = native.load_players(folder, {"Short Name": "Full Name"})
        self.assertEqual(set(players), {"Full Name"})
        row = native.player_row("Full Name", players["Full Name"], MODEL)
        self.assertNotIn("player_id", row)
        self.assertEqual([h["date"] for h in row["history"]], [DATE, "2027-01-02"])
        self.assertEqual(row["history"][0]["CB"], 12)
        self.assertGreater(row["CB"], 12)
        self.assertEqual(players["Full Name"]["files"], set(files))

    def test_mixed_legacy_and_stable_namesakes_same_date_sources(self):
        folder = self.root / "observations"
        folder.mkdir()
        attrs = dict.fromkeys(MODEL["outfield"]["CB"], 12)
        a, b = "source-a:123", "source-b:123"
        common = {"Name": "Same Name", "Club": "Rangers", "Age": "25"}
        write_csv(folder / "2027-01-01_my-club_outfield.csv",
                  [{**common, **attrs}, {**common, **attrs, "Player ID": a},
                   {**common, **attrs, "Player ID": b, "Pace": 16}])
        write_csv(folder / "2027-01-01_search-secondary_outfield.csv",
                  [{**common, "Player ID": a, "Pace": 20}])
        players, files = native.load_players(folder)
        self.assertEqual(set(players), {"Same Name", ("id", a), ("id", b)})
        self.assertEqual(len(players[("id", a)]["files"]), 2)
        self.assertEqual(len(files), 2)
        rows = [native.player_row(k, p, MODEL) for k, p in players.items()]
        native.label_namesakes(rows)
        self.assertEqual(len({r["display_name"] for r in rows}), 3)
        stable = {r["player_id"]: r for r in rows if "player_id" in r}
        self.assertEqual(stable[a]["history"][0]["attrs"]["Pace"], 20)
        self.assertEqual(stable[b]["history"][0]["attrs"]["Pace"], 16)
        self.assertEqual(len(stable[a]["history"]), 1)
        for row in rows:
            self.assertNotIn("Player ID", row["history"][0]["attrs"])
        selectors = native.player_selectors(players)
        with self.assertRaisesRegex(SystemExit, "ambiguous"):
            native.resolve_players(["Same Name"], players, selectors, strict=True)
        self.assertEqual(native.resolve_players(["id:" + b], players, selectors, strict=True), {("id", b)})

    def test_native_last_batch_selects_exact_namesake_identity(self):
        self.target["name"] = self.cb["name"]
        self.process()
        self.prepare_renderer()
        out = self.render()
        target, = [p for p in self.native_data(out, "last") if p["name"] == self.cb["name"]]
        cfg = self.root / "saves" / SLUG / "save.toml"
        with cfg.open("a", encoding="utf-8") as stream:
            stream.write("\nlast_names = [" + json.dumps("id:" + target["player_id"]) + "]\n")
        result = subprocess.run([sys.executable, "score.py", "--save", SLUG], cwd=self.root,
                                capture_output=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([p["player_id"] for p in self.native_data(out, "last")], [target["player_id"]])

    def test_existing_legacy_csv_survives_identified_refresh(self):
        self.process()
        self.prepare_renderer()
        out = self.render()
        folder = self.root / "saves" / SLUG / "obs"
        legacy = folder / "2026-12-31_my-club_outfield.csv"
        write_csv(legacy, [{"Name": self.cb["name"], "Club": "Rangers", "Age": "26",
                            **dict.fromkeys(MODEL["outfield"]["CB"], 12)}])
        before = legacy.read_bytes()
        self.render()
        squad, = [p for p in self.native_data(out, "squad") if p["name"] == self.cb["name"]]
        old, = [p for p in self.native_data(out, "players") if p["name"] == self.cb["name"]]
        self.assertIn("player_id", squad)
        self.assertNotIn("player_id", old)
        self.assertEqual(old["history"][0]["date"], "2026-12-31")
        self.assertEqual(old["CB"], 12)
        self.assertEqual(legacy.read_bytes(), before)

    def test_public_league_export_drops_private_player_id(self):
        folder = self.root / "saves" / SLUG / "obs"
        folder.mkdir(parents=True)
        source = folder / "2027-01-01_search-invented_outfield.csv"
        write_csv(source, [{"Name": f"Private Name {i}", "Player ID": f"private:{i}",
                            "Club": "Invented FC", "Division": "Invented League", "Age": "25",
                            "Pace": 12} for i in range(native.MIN_DIVISION)])
        leagues = self.root / "leagues"
        with patch.object(native, "ROOT", self.root), patch.object(native, "LEAGUES", leagues):
            native.share_leagues(SLUG)
        shared, = leagues.glob("*.csv")
        with shared.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            self.assertNotIn("Player ID", reader.fieldnames)
            self.assertTrue(all(row["Name"].startswith("Invented FC ") for row in reader))


if __name__ == "__main__":
    unittest.main()
