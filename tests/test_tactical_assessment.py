"""Evidence-based tactical assessment tests using invented players only."""
import json
import tomllib
import unittest
from pathlib import Path

import formation
import scoring
import tactical_assessment as tactical


ROOT = Path(__file__).resolve().parents[1]
MODEL = tomllib.loads((ROOT / "weights/fm27v2.toml").read_text(encoding="utf-8"))
CODES = formation.FM_POSITION_CODES
PROFILES = set(MODEL["outfield"]) | {"GK"}
DEFAULT = formation.load_formation(ROOT / "formations/default.toml", MODEL)
ASYMMETRIC = formation.load_formation(ROOT / "formations/asymmetric-4231.toml", MODEL)


def invented_player(raw, *, keeper=False, availability="available", identifier="career-a:123"):
    attributes = {name: 20 for profile in [MODEL["gk"], *MODEL["outfield"].values()] for name in profile}
    return {
        "player_id": identifier, "raw": {"name": "Invented Namesake", **raw},
        "name": "Invented Namesake", "club": "Rangers", "cohorts": {"squad"},
        "attrs": attributes, "keeper": keeper, "availability": availability,
        "loan_state": "permanent", "record_game_date": "2027-01-01",
        "last_seen_game_date": "2027-01-03", "game_build": "invented",
    }


def assess(player, tactic=DEFAULT):
    evidence = tactical.position_evidence(player["raw"], CODES)
    return {s["slot_id"]: s for s in tactical.assess_player(tactic, MODEL, player, evidence, scorer=scoring.weighted)}


class TacticalAssessmentTests(unittest.TestCase):
    def test_left_and_right_are_independent_and_centre_back_code_is_shared(self):
        player = invented_player({"positions_dl": "20", "positions_dr": "4", "positions_wbl": "19",
                                  "positions_wbr": "1", "positions_dc": "17"})
        slots = assess(player)
        self.assertEqual(slots["lb"]["accepted_positions"]["dl"]["rating"], 20)
        self.assertEqual(slots["lb"]["accepted_positions"]["wbl"]["rating"], 19)
        self.assertEqual(slots["rb"]["accepted_positions"]["dr"]["rating"], 4)
        self.assertEqual(slots["rb"]["accepted_positions"]["wbr"]["rating"], 1)
        self.assertEqual(slots["lb"]["combined_position_fit"], 20)
        self.assertEqual(slots["rb"]["combined_position_fit"], 4)
        self.assertEqual(slots["lcb"]["ip"]["familiarity"], slots["rcb"]["ip"]["familiarity"])
        self.assertEqual(slots["lcb"]["combined_position_fit"], 17)
        self.assertNotEqual(slots["lcb"]["slot_id"], slots["rcb"]["slot_id"])

    def test_asymmetric_right_back_uses_exact_phase_positions_separate_from_attributes(self):
        player = invented_player({"positions_dr": 20, "positions_wbr": 19, "positions_dc": 2})
        slot = assess(player, ASYMMETRIC)["rb"]
        self.assertEqual(slot["accepted_positions"]["dr"]["rating"], 20)
        self.assertEqual(slot["ip"]["position"], "dc")
        self.assertEqual(slot["ip"]["position_fit"], 2)
        self.assertEqual(slot["oop"]["position_fit"], 20)
        self.assertAlmostEqual(slot["combined_position_fit"], 8.3)
        self.assertEqual(slot["attribute_profile_score"], 20)
        self.assertIsNone(slot["ip"]["observed_role_suitability"])
        self.assertIsNone(slot["oop"]["observed_role_suitability"])

    def test_category_fallback_is_bounded_and_never_treated_as_exact(self):
        raw = {"natural_positions": "DL; ST", "accomplished_positions": "DR;DC", "positions_dc": "16"}
        evidence = tactical.position_evidence(raw, CODES)
        self.assertEqual(evidence["dl"], {
            "position": "dl", "status": "inferred_category", "rating": None, "category": "natural",
            "lower_bound": 18, "upper_bound": 20, "source": "natural_positions", "reason": "category_only",
        })
        self.assertEqual((evidence["dr"]["lower_bound"], evidence["dr"]["upper_bound"]), (15, 17))
        self.assertEqual(evidence["stc"]["category"], "natural")
        self.assertEqual(evidence["dc"]["status"], "observed")
        self.assertEqual(evidence["dc"]["rating"], 16)
        slot = assess(invented_player(raw))["lb"]
        self.assertIsNone(slot["ip"]["position_fit"])
        self.assertIsNone(slot["combined_position_fit"])
        self.assertEqual(slot["missing_weighted_phases"], ["ip", "oop"])

    def test_invalid_inputs_and_conflicting_categories_are_unknown(self):
        for value in (0, 21, -1, True, 18.5, 18.0, "18.5", "18.0", "NaN", "inf", "abc", [], {}):
            with self.subTest(value=value):
                item = tactical.position_evidence({"positions_dl": value, "natural_positions": "DL"}, CODES)["dl"]
                self.assertEqual(item["status"], "missing")
                self.assertIsNone(item["rating"])
                self.assertEqual(item["reason"], "invalid_position_rating")
        missing = tactical.position_evidence({}, CODES)["dl"]
        self.assertEqual(missing["reason"], "missing_position_rating")
        conflict = tactical.position_evidence({"natural_positions": "DL", "accomplished_positions": "DL"}, CODES)["dl"]
        self.assertEqual(conflict["reason"], "conflicting_categories")
        fallback = tactical.position_evidence({"positions_dl": "", "natural_positions": "DL"}, CODES)["dl"]
        self.assertEqual(fallback["status"], "inferred_category")

    def test_complete_incomplete_profiles_and_keeper_domain(self):
        player = invented_player({"positions_dc": 20})
        self.assertEqual(assess(player)["lcb"]["attribute_profile_score"], 20)
        del player["attrs"]["Pace"]
        slot = assess(player)["lcb"]
        self.assertIsNone(slot["attribute_profile_score"])
        self.assertIn("Pace", slot["missing_attributes"])
        self.assertEqual(slot["attribute_profile_reason"], "missing_attributes")
        self.assertEqual(slot["combined_position_fit"], 20)
        self.assertEqual(assess(player)["gk"]["attribute_profile_reason"], "incompatible_player_type")
        keeper = invented_player({"positions_gk": 20}, keeper=True)
        self.assertEqual(assess(keeper)["gk"]["attribute_profile_score"], 20)
        self.assertIsNone(assess(keeper)["lcb"]["attribute_profile_score"])

    def test_weighted_missing_evidence_and_zero_weight_phases(self):
        player = invented_player({"positions_dr": 20})
        slot = assess(player, ASYMMETRIC)["rb"]
        self.assertIsNone(slot["combined_position_fit"])
        self.assertEqual(slot["combined_position_fit_reason"], "missing_numeric_phase_evidence")
        self.assertEqual(slot["missing_weighted_phases"], ["ip"])
        config = tomllib.loads((ROOT / "formations/asymmetric-4231.toml").read_text(encoding="utf-8"))
        config["phase_weights"] = {"ip": 0, "oop": 3}
        weights = formation.validate_formation(config, PROFILES)
        slot = assess(player, weights)["rb"]
        self.assertEqual(slot["combined_position_fit"], 20)
        self.assertIsNone(slot["ip"]["position_fit"])
        self.assertEqual(slot["missing_weighted_phases"], [])
        del config["slots"][4]["ip"]
        slot = assess(player, formation.validate_formation(config, PROFILES))["rb"]
        self.assertEqual(slot["combined_position_fit"], 20)
        self.assertEqual(slot["ip"]["position_fit_reason"], "phase_position_unspecified")
        config["phase_weights"]["ip"] = 1
        slot = assess(player, formation.validate_formation(config, PROFILES))["rb"]
        self.assertIsNone(slot["combined_position_fit"])
        self.assertEqual(slot["missing_weighted_phases"], ["ip"])

    def test_availability_and_observed_role_suitability_are_independent(self):
        for availability, loan in (("available", "incoming"), ("unavailable", "outgoing"), ("unknown", "unknown")):
            player = invented_player({"positions_dr": 20, "positions_dc": 18,
                                      "role_suitability": 20, "roles_ip": 20}, availability=availability)
            player["loan_state"] = loan
            slot = assess(player, ASYMMETRIC)["rb"]
            self.assertEqual(slot["availability"], availability)
            self.assertAlmostEqual(slot["combined_position_fit"], 18.7)
            self.assertIsNone(slot["ip"]["observed_role_suitability"])
            self.assertIn("observed_role_suitability:unsupported_source", slot["missing_evidence"])

    def test_report_is_deterministic_with_namesakes_and_career_scoped_ids(self):
        players = [invented_player({"positions_dc": 18}, identifier="career-b:123"),
                   invented_player({"positions_dc": 16}, identifier="career-a:123")]
        kwargs = {"codes": CODES, "scorer": scoring.weighted, "career": "fixture",
                  "formation_source": "default.toml", "model_sha256": "invented-hash"}
        first = tactical.build_assessments(DEFAULT, MODEL, players, **kwargs)
        second = tactical.build_assessments(DEFAULT, MODEL, list(reversed(players)), **kwargs)
        self.assertEqual(json.dumps(first, allow_nan=False), json.dumps(second, allow_nan=False))
        self.assertEqual([p["player_id"] for p in first["players"]], ["career-a:123", "career-b:123"])
        self.assertEqual(first["game_date"], "2027-01-03")
        self.assertEqual(first["players"][0]["record_game_date"], "2027-01-01")
        self.assertEqual([s["slot_id"] for s in first["players"][0]["slots"]], [s["id"] for s in DEFAULT["slots"]])
        self.assertEqual(len(first["players"][0]["position_evidence"]), 15)
        self.assertIsNone(first["observed_role_suitability_source"])


if __name__ == "__main__":
    unittest.main()
