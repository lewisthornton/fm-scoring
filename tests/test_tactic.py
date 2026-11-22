"""R2: only invented role definitions and temporary configuration files."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import formation
import tactic


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "formations"
CATALOGUE = FIXTURES / "synthetic-role-catalogue.toml"
REGISTRY = FIXTURES / "tactic-registry.example.toml"


def parsed(name):
    return tomllib.loads((FIXTURES / name).read_text(encoding="utf-8"))


def synthetic():
    return parsed("synthetic-asymmetric.toml")


def slot(config, identifier):
    return next(row for row in config["slots"] if row["id"] == identifier)


def imported():
    """Normalized future adapter input, not an actual fmsave export."""
    config = synthetic()
    rows = copy.deepcopy(config["slots"])
    for i, row in enumerate(rows):
        row["defending_index"] = i
        for phase in tactic.PHASES:
            part = row[phase]
            part.pop("role_id")
            part["role_status"] = "unknown"
            part["role_reason"] = "not decoded"
            part["raw_role_token"] = f"invented-{i}-{phase}"
    # Non-self-inverse cycle: IP slots 1, 4, 9 defend in stored rows 4, 9, 1.
    for i, dest in [(1, 4), (4, 9), (9, 1)]:
        rows[i]["defending_index"] = dest
    return {"source": {"kind": "save_import", "reference": "invented parser output", "career": "career-a",
                       "club_id": "club-a", "team_id": "team-a", "game_build": "invented-build",
                       "parser_version": "invented-parser", "save_sha256": "a" * 64, "stored_index": 2},
            "team_slot": 0, "name": "Invented stored tactic", "slots": rows}


class TacticTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = tactic.load_catalogue(CATALOGUE)

    def validate(self, config):
        return tactic.validate_tactic(config, self.catalogue)

    def adapt(self, snapshot):
        return tactic.adapt_save_tactic(snapshot, {"career": "career-a", "club_id": "club-a", "team_id": "team-a"},
                                        self.catalogue, tactic_id="imported", weights={"ip": 1, "oop": 1})

    def test_complete_tactics_distinct_slots_and_phases(self):
        for identifier in ("synthetic-433", "synthetic-asymmetric"):
            report = tactic.select_tactic(REGISTRY, CATALOGUE, identifier)
            self.assertEqual(report["configuration_status"], "configured")
            self.assertEqual(len({row["id"] for row in report["tactic"]["slots"]}), 11)
            self.assertFalse(report["role_scoring_available"])
            self.assertEqual(report["catalogue"]["origin"], "synthetic")
            self.assertEqual(slot(report["tactic"], "gk")["oop"]["role_id"], "oop.alpha")
        normal = self.validate(synthetic())
        rb = slot(normal, "rb")
        self.assertEqual((rb["selection_position"], rb["ip"]["position"], rb["oop"]["position"]), ("dr", "dc", "dr"))
        self.assertEqual(rb["ip"]["role_id"], "ip.triangle")
        self.assertEqual(slot(normal, "lcb")["ip"]["side"], "left")
        self.assertEqual(slot(normal, "rcb")["ip"]["side"], "centre")
        self.assertEqual(slot(normal, "rcb")["oop"]["side"], "right")
        self.assertEqual(slot(normal, "lb")["ip"]["instruction_source"], "user_defined")

    def test_missing_duplicate_and_extra_slots(self):
        for edit in (lambda c: c["slots"].pop(), lambda c: c["slots"].append(copy.deepcopy(c["slots"][0])),
                     lambda c: c["slots"][1].update(id="gk"), lambda c: c["slots"][1].pop("id")):
            config = synthetic()
            edit(config)
            with self.assertRaises(ValueError):
                self.validate(config)

    def test_bad_selection_and_phase_geometry(self):
        mutations = [lambda c: slot(c, "lb").update(selection_position="fake"),
                     lambda c: slot(c, "lb").update(side="right"),
                     lambda c: slot(c, "lb").update(positions=["wbl"]),
                     lambda c: slot(c, "lb")["ip"].update(position="unknown"),
                     lambda c: slot(c, "lb")["oop"].update(side="right"),
                     lambda c: slot(c, "gk")["oop"].update(side="left"),
                     lambda c: slot(c, "gk").update(selection_position="dc", legacy_profile="CB"),
                     lambda c: slot(c, "gk")["ip"].update(position="dc", role_id="ip.base", side="left"),
                     lambda c: slot(c, "lb").pop("oop"),
                     lambda c: slot(c, "lb").update(legacy_profile="9")]
        for edit in mutations:
            config = synthetic()
            edit(config)
            with self.assertRaises(ValueError):
                self.validate(config)

    def test_role_namespace_and_placement_constraints(self):
        for role in ("oop.base", "ip.nonexistent", "ip.alpha", "ip.triangle"):
            config = synthetic()
            slot(config, "lb")["ip"]["role_id"] = role
            with self.subTest(role=role), self.assertRaises(ValueError):
                self.validate(config)
        config = synthetic()
        slot(config, "rb")["ip"]["side"] = "left"
        with self.assertRaisesRegex(ValueError, "not offered"):
            self.validate(config)
        # Triangle is configured for three IP centre-backs, not two.
        config = synthetic()
        slot(config, "lcb")["ip"] = {"position": "mc", "side": "left", "role_status": "user_defined", "role_id": "ip.link"}
        with self.assertRaisesRegex(ValueError, "formation context"):
            self.validate(config)
        self.assertEqual(self.catalogue["roles"]["ip.alpha"]["label"], self.catalogue["roles"]["oop.alpha"]["label"])

    def test_catalogue_invalid_definitions_and_unsupported_origin(self):
        changes = [lambda c: c.update(origin="game_observed"), lambda c: c.update(version=True),
                   lambda c: c["roles"].append(copy.deepcopy(c["roles"][0])),
                   lambda c: c["roles"][0].update(id="alpha"),
                   lambda c: c["roles"][0].update(placements=[{"position": "dl", "side": "right"}]),
                   lambda c: c["roles"][0].update(min_centre_backs=4, max_centre_backs=3),
                   lambda c: c["roles"][0].update(weights={"pace": 1})]
        for edit in changes:
            config = parsed(CATALOGUE.name)
            edit(config)
            with self.assertRaises(ValueError):
                tactic.validate_catalogue(config)

    def test_phase_weights_and_schema_versions(self):
        for weights in ({"ip": 0, "oop": 0}, {"ip": -1, "oop": 1}, {"ip": float("nan"), "oop": 1},
                        {"ip": float("inf"), "oop": 0}, {"ip": True, "oop": 1}, {"ip": 1}):
            config = synthetic()
            config["phase_weights"] = weights
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                self.validate(config)
        for v in (1, 3, True, "2"):
            config = synthetic()
            config["version"] = v
            with self.assertRaises(ValueError):
                self.validate(config)

    def test_unknown_ambiguous_and_unsupported_roles_remain_null(self):
        for status in ("unknown", "ambiguous", "unsupported"):
            config = synthetic()
            slot(config, "lb")["oop"] = {"position": "dl", "side": "left", "role_status": status,
                                               "role_reason": "invented unresolved evidence", "raw_role_token": "oop.base"}
            normalized = self.validate(config)
            part = slot(normalized, "lb")["oop"]
            self.assertIsNone(part["role_id"])
            self.assertEqual(part["role_status"], status)
            slot(config, "lb")["oop"]["role_id"] = "oop.base"
            with self.assertRaises(ValueError):
                self.validate(config)
        config = synthetic()
        slot(config, "lb")["oop"] = {"role_status": "unknown", "role_reason": "unknown role", "geometry_reason": "unknown position or side"}
        self.assertIsNone(slot(self.validate(config), "lb")["oop"]["position"])
        slot(config, "lb")["oop"].pop("geometry_reason")
        with self.assertRaises(ValueError):
            self.validate(config)

    def test_manual_role_cannot_claim_game_observation(self):
        config = synthetic()
        slot(config, "lb")["ip"]["role_status"] = "game_observed"
        with self.assertRaises(ValueError):
            self.validate(config)
        config = synthetic()
        slot(config, "lb")["ip"]["raw_role_token"] = "ip.rim"
        with self.assertRaises(ValueError):
            self.validate(config)

    def test_hash_canonical_and_source_separate(self):
        config = synthetic()
        first = self.validate(config)
        config["source"]["reference"] = "another invented reference"
        reordered = dict(reversed(list(config.items())))
        self.assertEqual(tactic.tactic_sha256(first), tactic.tactic_sha256(self.validate(reordered)))
        config["phase_weights"]["ip"] = 1
        self.assertNotEqual(tactic.tactic_sha256(first), tactic.tactic_sha256(self.validate(config)))
        config = synthetic()
        config["slots"].reverse()
        self.assertNotEqual(tactic.tactic_sha256(first), tactic.tactic_sha256(self.validate(config)))
        raw = parsed(CATALOGUE.name)
        raw["roles"].reverse()
        for role in raw["roles"]:
            role["placements"].reverse()
        self.assertEqual(tactic.canonical_sha256(self.catalogue), tactic.canonical_sha256(tactic.validate_catalogue(raw)))

    def test_unknown_phase_weight_and_source_file_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / "synthetic-433.toml"
            raw = (FIXTURES / file.name).read_text(encoding="utf-8")
            file.write_text(raw, encoding="utf-8")
            registry = root / "registry.toml"
            registry.write_text('version=1\n[tactics]\nsynthetic-433="synthetic-433.toml"\n', encoding="utf-8")
            first = tactic.select_tactic(registry, CATALOGUE, "synthetic-433")
            file.write_text(raw + "\n# comment\n", encoding="utf-8")
            second = tactic.select_tactic(registry, CATALOGUE, "synthetic-433")
            self.assertEqual(first["tactic_sha256"], second["tactic_sha256"])
            self.assertNotEqual(first["tactic"]["source"]["file_sha256"], second["tactic"]["source"]["file_sha256"])
            draft = raw.replace('oop = {position = "gk", side = "centre", role_status = "user_defined", role_id = "oop.alpha"}',
                                'oop = {position = "gk", side = "centre", role_status = "unknown", role_reason = "invented"}')
            file.write_text(draft, encoding="utf-8")
            selected = tactic.select_tactic(registry, CATALOGUE, "synthetic-433")
            self.assertEqual(selected["configuration_status"], "draft")
            self.assertEqual(selected["unresolved_weighted_phases"], [{"slot_id": "gk", "phase": "oop"}])
            file.write_text(draft.replace("oop = 0.5", "oop = 0"), encoding="utf-8")
            selected = tactic.select_tactic(registry, CATALOGUE, "synthetic-433")
            self.assertEqual(selected["configuration_status"], "configured")
            self.assertFalse(selected["role_scoring_available"])

    def test_v1_loading_preserves_legacy_geometry_and_labels(self):
        old = formation.validate_formation(parsed("asymmetric-4231.toml"), tactic.LEGACY_PROFILES)
        report = tactic.select_tactic(REGISTRY, CATALOGUE, "legacy-asymmetric")
        projected = report["tactic"]
        self.assertEqual(projected["input_version"], 1)
        self.assertEqual(projected["phase_weights"], old["phase_weights"])
        self.assertEqual(report["configuration_status"], "draft")
        self.assertEqual(len(report["unresolved_weighted_phases"]), 22)
        for legacy, new in zip(old["slots"], projected["slots"]):
            self.assertEqual(legacy["id"], new["id"])
            self.assertEqual(legacy["profile"], new["legacy_profile"])
            for phase in tactic.PHASES:
                self.assertEqual(legacy[phase]["position"], new[phase]["position"])
                self.assertEqual(legacy[phase]["role"], new[phase]["role_label"])
                self.assertIsNone(new[phase]["role_id"])
        self.assertEqual(formation.VERSION, 1)

    def test_adapter_explicit_permutation_and_team_provenance(self):
        data = imported()
        normal = self.adapt(data)
        self.assertEqual(normal["source"]["team_id"], "team-a")
        self.assertEqual([r["id"] for r in normal["slots"]], [r["id"] for r in data["slots"]])
        self.assertEqual([normal["slots"][i]["oop"]["raw_role_token"] for i in (1, 4, 9)],
                         ["invented-4-oop", "invented-9-oop", "invented-1-oop"])
        self.assertTrue(all(s[p]["role_id"] is None for s in normal["slots"] for p in tactic.PHASES))
        for key in ("career", "club_id", "team_id"):
            conflicting = imported()
            conflicting["source"][key] = "other"
            with self.assertRaisesRegex(ValueError, "expected managed first team"):
                self.adapt(conflicting)
        data["team_slot"] = 1
        with self.assertRaises(ValueError):
            self.adapt(data)

    def test_bad_permutations_and_unverified_role_id(self):
        for value in (None, True, "4", 11, -1, 0):
            data = imported()
            data["slots"][1]["defending_index"] = value
            with self.assertRaisesRegex(ValueError, "permutation"):
                self.adapt(data)
        data = imported()
        data["slots"][1]["ip"].update(role_status="user_defined", role_id="ip.rim")
        with self.assertRaises(ValueError):
            self.adapt(data)

    def test_explicit_selection_stable_and_no_first_entry_fallback(self):
        expected = tactic.select_tactic(REGISTRY, CATALOGUE, "synthetic-asymmetric")
        self.assertEqual(expected, tactic.select_tactic(REGISTRY, CATALOGUE, "synthetic-asymmetric"))
        with self.assertRaises(ValueError):
            tactic.select_tactic(REGISTRY, CATALOGUE, "missing")
        with self.assertRaises(ValueError):
            tactic.select_tactic(REGISTRY, CATALOGUE, None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("synthetic-433.toml", "synthetic-asymmetric.toml"):
                (root / name).write_bytes((FIXTURES / name).read_bytes())
            registry = root / "index.toml"
            registry.write_text('version=1\n[tactics]\nsynthetic-asymmetric="synthetic-asymmetric.toml"\nsynthetic-433="synthetic-433.toml"\n', encoding="utf-8")
            self.assertEqual(expected, tactic.select_tactic(registry, CATALOGUE, "synthetic-asymmetric"))

    def test_invalid_refresh_and_replace_failure_keep_previous_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example = root / "synthetic-433.toml"
            example.write_bytes((FIXTURES / example.name).read_bytes())
            registry = root / "registry.toml"
            registry.write_text('version=1\n[tactics]\nsynthetic-433="synthetic-433.toml"\n', encoding="utf-8")
            output = root / "selected_tactic.json"
            report = tactic.publish_selection(registry, CATALOGUE, "synthetic-433", output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)
            before = output.read_bytes()
            with patch.object(tactic.os, "replace", side_effect=OSError("invented error")), self.assertRaises(OSError):
                tactic.publish_selection(registry, CATALOGUE, "synthetic-433", output)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(list(root.glob(".tactic-*.tmp")), [])
            example.write_text("version = 2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                tactic.publish_selection(registry, CATALOGUE, "synthetic-433", output)
            self.assertEqual(output.read_bytes(), before)

    def test_cli_smoke_requires_explicit_id_and_protects_operational_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "selected_tactic.json"
            command = [sys.executable, str(ROOT / "tactic.py"), "--registry", str(REGISTRY), "--catalogue", str(CATALOGUE), "--output", str(output)]
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(output.exists())
            ok = subprocess.run(command + ["--select", "synthetic-433"], capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["selected_id"], "synthetic-433")
            protected = Path(tmp) / "formation.json"
            protected.write_bytes(b"existing operational output")
            with self.assertRaisesRegex(ValueError, "operational report"):
                tactic.publish_selection(REGISTRY, CATALOGUE, "synthetic-433", protected)
            self.assertEqual(protected.read_bytes(), b"existing operational output")
