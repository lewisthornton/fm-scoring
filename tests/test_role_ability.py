"""R3: invented player inputs and authorised upstream numerical references."""
import copy
import json
from pathlib import Path
import unittest

import role_ability as ra
import tactic


ROOT = Path(__file__).resolve().parents[1]
FORMATION = ROOT / "formations"
CATALOGUE = tactic.load_catalogue(FORMATION / "fm27-role-catalogue.toml")
ATTRIBUTES = sorted({a for r in CATALOGUE["roles"].values() for group in
                     ("key_attributes", "preferable_attributes", "negative_attributes") for a in r[group]})
OPTIONS = {"model_id": ra.FM27_MODEL_ID, "game_build": "27.0.0", "database_version": 3754}

# Authorised reference fixture's ordered fields (Napas/fm-mcp player.go).
REFERENCE_POSITIONS = "gk sw dl dc dr dm ml mc mr aml amc amr stc wbl wbr".split()
REFERENCE_ATTRIBUTES = ("crossing dribbling finishing heading long_shots marking off_the_ball passing penalties tackling "
    "vision handling aerial_reach command_of_area communication kicking throwing anticipation decisions one_on_ones "
    "positioning reflexes first_touch technique left_foot right_foot flair corners teamwork work_rate long_throws "
    "eccentricity rushing_out tendency_to_punch acceleration free_kicks strength stamina pace jumping_reach leadership "
    "dirtiness balance bravery consistency aggression agility important_matches injury_proneness versatility natural_fitness "
    "determination composure concentration").split()


def player(value=50, ca=150, positions=None):
    return {"schema_version": 1, "player_id": "invented:1", "career": "invented",
            "record_game_date": "2027-01-01", "game_build": "27.0.0", "database_version": 3754,
            "attribute_scale": "raw_1_100", "raw_attributes": dict.fromkeys(ATTRIBUTES, value),
            "positions": dict.fromkeys(REFERENCE_POSITIONS, 1) | (positions or {}), "current_ability": ca}


def evaluate(p, key, position, side="centre", **options):
    return ra.evaluate_role(p, CATALOGUE, key, key.split(".")[0], position, side,
                            **(OPTIONS | options))


def selection(config, catalogue=CATALOGUE):
    valid = tactic.validate_tactic(config, catalogue)
    return {"version": 1, "tactic": valid, "tactic_sha256": tactic.tactic_sha256(valid),
            "catalogue": {"sha256": tactic.canonical_sha256(catalogue)}}


def real_tactic():
    """Invented geometry from R2, explicit reference role IDs, never inferred."""
    config = tactic.read_toml(FORMATION / "synthetic-asymmetric.toml")
    config["id"] = "reference-example"
    keys = {"gk": ("goalkeeper", "goalkeeper"), "lb": ("wing_back", "full_back"),
            "lcb": ("centre_back", "centre_back"), "rcb": ("ball_playing_centre_back", "centre_back"),
            "rb": ("wide_centre_back", "holding_full_back"),
            "ldm": ("defensive_midfielder", "defensive_midfielder"),
            "rdm": ("central_midfielder", "screening_defensive_midfielder"),
            "lw": ("attacking_midfielder", "wide_midfielder"), "am": ("advanced_playmaker", "central_midfielder"),
            "rw": ("winger", "wide_midfielder"), "st": ("centre_forward", "centre_forward")}
    for slot in config["slots"]:
        for phase, key in zip(tactic.PHASES, keys[slot["id"]]):
            slot[phase]["role_id"] = phase + "." + key
    return config


class RoleAbilityTests(unittest.TestCase):
    def test_catalogue_counts_and_all_supported_placements_uniform_oracle(self):
        roles = CATALOGUE["roles"]
        self.assertEqual(sum(k.startswith("ip.") for k in roles), 50)
        self.assertEqual(sum(k.startswith("oop.") for k in roles), 39)
        self.assertEqual(sum(bool(r["placements"]) for r in roles.values()), 79)
        self.assertEqual(sum(len(r["placements"]) for r in roles.values()), 209)
        self.assertEqual(tactic.canonical_sha256(CATALOGUE), ra.CATALOGUE_SHA256)
        p = player(50, positions=dict.fromkeys(REFERENCE_POSITIONS, 20))
        # Analytic synthetic oracle: all three class means = 50 and p=20;
        # rating=100, best=100, CA=150 exceeds every applicable threshold.
        for key, role in roles.items():
            for place in role["placements"]:
                with self.subTest(key=key, place=place):
                    r = evaluate(p, key, place["position"], place["side"], centre_back_count=3)
                    self.assertEqual((r["role_rating"], r["best_role_rating"], r["role_ability"]), (100, 100, 150))
        for key, role in roles.items():
            if not role["placements"]:
                self.assertEqual(evaluate(p, key, "stc")["rating_reason"], "unsupported_role_placement")

    def test_reference_key_preferable_negative_and_penalty_boundaries(self):
        # Upstream TestRoleRatingWeighsKeyPreferableAndNegativeAttributes.
        p = player(50, positions={"gk": 20})
        self.assertEqual(evaluate(p, "ip.goalkeeper", "gk")["role_rating"], 100)
        q = copy.deepcopy(p)
        for attr in CATALOGUE["roles"]["ip.goalkeeper"]["key_attributes"]:
            q["raw_attributes"][attr] = 80
        self.assertEqual(evaluate(q, "ip.goalkeeper", "gk")["role_rating"], 141)
        q = copy.deepcopy(p)
        q["raw_attributes"]["eccentricity"] = 100
        self.assertEqual(evaluate(q, "ip.goalkeeper", "gk")["role_rating"], 87)
        # Independently derived preferable mean only: (16*50+4*80+3*50)/23*2.
        q = copy.deepcopy(p)
        for attr in CATALOGUE["roles"]["ip.goalkeeper"]["preferable_attributes"]:
            q["raw_attributes"][attr] = 80
        self.assertEqual(evaluate(q, "ip.goalkeeper", "gk")["role_rating"], 110)
        for pos, expected in {20:100, 18:98, 15:95, 14:85, 13:83, 12:80, 11:64, 1:24}.items():
            self.assertEqual(evaluate(player(positions={"gk": pos}), "ip.goalkeeper", "gk")["role_rating"], expected)

    def test_reference_side_blends_and_false_nine(self):
        # Upstream TestRoleRatingBlendsTheNeighbouringPosition.
        p = player(positions={"dc": 14, "dl": 10, "dr": 20})
        for side, want in (("left", 85), ("right", 97)):
            r = evaluate(p, "ip.overlapping_centre_back", "dc", side, centre_back_count=3)
            self.assertEqual(r["role_rating"], want)
        self.assertEqual(evaluate(p, "ip.overlapping_centre_back", "dc", "right", centre_back_count=2)["rating_reason"], "unconfirmed_formation_context")
        for st, amc, expected in ((12,20,96),(12,14,56),(12,1,80),(11,20,64)):
            self.assertEqual(evaluate(player(positions={"stc":st,"amc":amc}), "ip.false_nine", "stc")["role_rating"], expected)

    def test_reference_fm27_scale_and_pull_up(self):
        # Upstream TestRoleRulesScale and TestRoleAbility (FM27 branch only).
        for r, b, ca, expected in ((105,150,90,63),(7,12,108,62),(121,132,150,137),(140,132,150,150)):
            self.assertEqual(ra.scale_ability(r,b,ca), expected)
        p = player(positions={"aml":20,"amr":14})
        for attr in CATALOGUE["roles"]["ip.inside_forward"]["key_attributes"]:
            p["raw_attributes"][attr] = 70
        for key, pos, side, expected in (("ip.inside_forward","aml","left",150),
                                         ("ip.inside_forward","amr","right",135), ("ip.winger","aml","left",143)):
            r = evaluate(p,key,pos,side)
            self.assertEqual(r["best_role_rating"],132)
            self.assertEqual(r["role_ability"],expected)

    def test_reference_oop_and_thresholds(self):
        # Upstream TestOutOfPossessionAbility and TestRoleAbilityHalvesUnderTheRoleThreshold.
        p = player(ca=60, positions={"dc":20})
        self.assertEqual(evaluate(p,"oop.centre_back","dc")["role_ability"],60)
        self.assertEqual(evaluate(p,"oop.full_back","dl","left")["role_ability"],19)
        p["positions"]["dl"] = 16
        self.assertEqual(evaluate(p,"oop.full_back","dl","left")["role_ability"],58)
        for ca, want in ((1,0),(70,35),(79,39),(80,80),(90,90)):
            r = evaluate(player(ca=ca, positions={"dc":20}),"ip.advanced_centre_back","dc")
            self.assertEqual(r["role_ability"],want)
        for key, pos, side, adj, expected in (
            ("oop.pressing_full_back","dl","left","wbl",97),
            ("oop.pressing_full_back","dr","right","wbr",97),
            ("oop.wide_centre_back","dc","left","dl",97),
            ("oop.wide_centre_back","dc","right","dr",97),
            ("oop.stopping_wide_centre_back","dc","left","dl",97),
            ("oop.covering_wide_centre_back","dc","right","dr",97),
            ("oop.wide_covering_defensive_midfielder","dm","left","wbl",97),
            ("oop.wide_covering_defensive_midfielder","dm","right","wbr",97),
            ("oop.tracking_wide_midfielder","ml","left","wbl",97),
            ("oop.tracking_wide_midfielder","mr","right","wbr",97),
            ("oop.pressing_wing_back","wbl","left","ml",97),
            ("oop.pressing_wing_back","wbr","right","mr",97),
            ("oop.wide_covering_central_midfielder","mc","left","ml",97),
            ("oop.wide_covering_central_midfielder","mc","right","mr",97),
            ("oop.tracking_winger","aml","left","ml",97),
            ("oop.tracking_winger","amr","right","mr",97),
            ("oop.dropping_defensive_midfielder","dm","centre","dc",97),
            ("oop.pressing_defensive_midfielder","dm","centre","mc",97),
            ("oop.tracking_attacking_midfielder","amc","centre","mc",97),
            ("oop.pressing_central_midfielder","mc","centre","amc",97),
            ("oop.inside_outlet_winger","aml","left","amc",97),
            ("oop.tracking_centre_forward","stc","centre","amc",97),
            ("oop.splitting_outlet_attacking_midfielder","amc","left","aml",97),
            ("oop.splitting_outlet_attacking_midfielder","amc","right","amr",97),
            ("oop.splitting_outlet_centre_forward","stc","left","aml",97),
            ("oop.splitting_outlet_centre_forward","stc","right","amr",97)):
            self.assertEqual(evaluate(player(positions={pos:14,adj:20}),key,pos,side)["role_rating"],expected)

    def test_reference_ip_other_blends_and_best_threshold(self):
        for key, pos, side, adjacent in (("ip.inside_full_back","dl","left","dc"),
                ("ip.inside_forward","aml","left","amc"), ("ip.playmaking_winger","amr","right","amc"),
                ("ip.inside_winger","ml","left","amc"), ("ip.advanced_centre_back","dc","centre","dm")):
            p = player(positions={pos:14,adjacent:20})
            self.assertEqual(evaluate(p,key,pos,side)["position_evidence"]["effective_rating"],17)
        # Upstream TestBestRoleRating: a low AWB rating cannot be the best.
        p = player(10,positions={"wbl":20})
        for attr in CATALOGUE["roles"]["ip.advanced_wing_back"]["key_attributes"]:
            p["raw_attributes"][attr] = 12
        self.assertEqual(evaluate(p,"ip.advanced_wing_back","wbl","left")["best_role_rating"],22)

    def test_all_offered_ip_threshold_boundaries(self):
        for key, pos, side, threshold in (
                ("ip.free_role","amc","centre",100), ("ip.wide_forward","aml","left",100),
                ("ip.box_to_box_playmaker","dm","left",100), ("ip.advanced_centre_back","dc","centre",80),
                ("ip.false_nine","stc","centre",80), ("ip.playmaking_winger","aml","left",80),
                ("ip.half_back","dm","centre",60), ("ip.advanced_wing_back","wbl","left",60)):
            for ca in (threshold-1, threshold, threshold+1):
                with self.subTest(key=key, ca=ca):
                    r = evaluate(player(ca=ca,positions={pos:20}),key,pos,side)
                    self.assertEqual(r["role_rating"],100)
                    self.assertEqual(r["role_ability"],ca//2 if ca<threshold else ca)

    def test_best_search_ties_no_best_and_missing_dependency(self):
        p = player(positions={"gk":9})
        r = evaluate(p,"ip.goalkeeper","gk")
        self.assertEqual((r["role_rating"],r["best_role_rating"],r["role_ability"]),(56,0,56))
        p["positions"]["gk"] = 20
        r = evaluate(p,"ip.goalkeeper","gk")
        self.assertGreater(len(r["best_role_ties"]),1)
        del p["positions"]["mc"]
        r = evaluate(p,"ip.goalkeeper","gk")
        self.assertEqual(r["role_rating"],100)
        self.assertIsNone(r["role_ability"])
        self.assertEqual(r["ability_reason"],"best_role_search_incomplete")
        p["positions"]["mc"] = 20
        del p["raw_attributes"]["passing"]  # needed by alternative roles, not OOP GK
        r = evaluate(p,"oop.goalkeeper","gk")
        # OOP MC roles do not require Passing; IP GK's denominator does.
        self.assertEqual(r["role_rating"],100)
        self.assertIsNotNone(r["role_ability"])
        r = evaluate(p,"ip.goalkeeper","gk")
        self.assertEqual(r["role_rating"],100)
        self.assertIsNone(r["role_ability"])

    def test_strict_inputs_and_invalid_values(self):
        p = player(positions={"gk":20})
        del p["current_ability"]
        r = evaluate(p,"ip.goalkeeper","gk")
        self.assertEqual(r["role_rating"],100)
        self.assertIsNone(r["role_ability"])
        self.assertEqual(r["ability_reason"],"current_ability_unavailable")
        for value, reason in ((None,"missing"),(0,"unsupported_value"),(101,"unsupported_value"),(True,"invalid_type"),(50.0,"invalid_type"),("50","invalid_type")):
            q = player(positions={"gk":20})
            q["raw_attributes"]["handling"] = value
            r = evaluate(q,"ip.goalkeeper","gk")
            self.assertIsNone(r["role_rating"])
            self.assertIn({"field":"raw_attributes.handling","reason":reason},r["rating_input_issues"])
        p = player(positions={"gk":20})
        p["attribute_scale"] = "display_1_20"
        self.assertIsNone(evaluate(p,"ip.goalkeeper","gk")["role_rating"])
        p = player(positions={"dc":14})
        del p["positions"]["dr"]
        p["position_categories"] = {"dr":"natural"}
        r = evaluate(p,"ip.wide_centre_back","dc","right",centre_back_count=3)
        self.assertIsNone(r["role_rating"])
        self.assertIn({"field":"positions.dr","reason":"category_only"},r["rating_input_issues"])
        p["positions"]["dc"] = 11
        self.assertIsNotNone(evaluate(p,"ip.wide_centre_back","dc","right",centre_back_count=3)["role_rating"])

    def test_build_model_catalogue_and_unknown_roles_fail_closed(self):
        p = player(positions={"gk":20})
        for build, db in (("27.1.0",3756),("27.0.1",3754),("27.0.0+2486695",3754),("27.0.0",3756),("26.3.2",3733)):
            self.assertEqual(evaluate(p,"ip.goalkeeper","gk",game_build=build,database_version=db)["rating_reason"],"unsupported_game_build")
        self.assertEqual(evaluate(p,"ip.goalkeeper","gk",model_id="unknown")["rating_reason"],"unknown_model")
        self.assertEqual(evaluate(p,"ip.unknown","gk")["rating_reason"],"unknown_or_wrong_phase_role")
        p["game_build"] = "27.1.0"
        self.assertEqual(evaluate(p,"ip.goalkeeper","gk")["rating_reason"],"observation_build_mismatch")
        synthetic = tactic.load_catalogue(FORMATION / "synthetic-role-catalogue.toml")
        selected = tactic.select_tactic(FORMATION / "tactic-registry.example.toml",FORMATION / "synthetic-role-catalogue.toml","synthetic-433")
        result = ra.assess_tactic(selected,synthetic,p,**OPTIONS)
        self.assertEqual(result["model_unavailable_reason"],"unsupported_catalogue_origin")
        self.assertTrue(all(s["combined_role_ability"] is None for s in result["slots"]))
        corrupted = copy.deepcopy(CATALOGUE)
        corrupted["roles"]["ip.goalkeeper"]["key_attributes"].append("imaginary")
        r = ra.evaluate_role(player(),corrupted,"ip.goalkeeper","ip","gk","centre",**OPTIONS)
        self.assertEqual(r["rating_reason"],"model_catalogue_mismatch")

    def test_tactic_assessment_missing_weighted_phase_and_hashes(self):
        p = player(positions=dict.fromkeys(REFERENCE_POSITIONS,20))
        config = real_tactic()
        selected = selection(config)
        result = ra.assess_tactic(selected,CATALOGUE,p,**OPTIONS)
        self.assertEqual(len(result["slots"]),11)
        self.assertEqual(result,ra.assess_tactic(selected,CATALOGUE,p,**OPTIONS))
        json.dumps(result,allow_nan=False)
        self.assertTrue(all(s["combined_role_ability"] == 150 for s in result["slots"]))
        self.assertTrue(all(s["ip"]["model_sha256"] == ra.MODEL_SHA256 for s in result["slots"]))
        config["slots"][0]["oop"] = {"position":"gk","side":"centre","role_status":"ambiguous","role_reason":"invented"}
        out = ra.assess_tactic(selection(config),CATALOGUE,p,**OPTIONS)
        self.assertIsNone(out["slots"][0]["combined_role_ability"])
        self.assertEqual(out["slots"][0]["missing_weighted_phases"],["oop"])
        config["phase_weights"] = {"ip":1,"oop":0}
        self.assertEqual(ra.assess_tactic(selection(config),CATALOGUE,p,**OPTIONS)["slots"][0]["combined_role_ability"],150)
        selected["tactic_sha256"] = "wrong"
        with self.assertRaises(ValueError):
            ra.assess_tactic(selected,CATALOGUE,p,**OPTIONS)

    def test_provisional_aggregation_and_zero_are_not_missing(self):
        self.assertEqual(ra.combine_abilities({"ip":100,"oop":140},{"ip":0.65,"oop":0.35}),(114.0,[]))
        self.assertEqual(ra.combine_abilities({"ip":0,"oop":140},{"ip":1,"oop":1}),(70.0,[]))
        self.assertEqual(ra.combine_abilities({"ip":0,"oop":None},{"ip":1,"oop":0}),(0.0,[]))
        self.assertEqual(ra.combine_abilities({"ip":100,"oop":None},{"ip":1,"oop":1}),(None,["oop"]))

    def test_reference_26_golden_rating_and_best_only(self):
        # The supplied golden file uses FM26 ability rules; FM27 ability is NOT
        # compared with those expectations. Documented rating/best rules match.
        # Exclude cases outside R3's supported input/placement domain explicitly.
        players, compared, unsupported_placement, unsupported_input = {}, 0, 0, 0
        bits = {r["role_bit"]:(key,r) for key,r in CATALOGUE["roles"].items() if key.startswith("ip.")}
        for line in (ROOT / "tests/fixtures/role_ability_reference_26.txt").read_text(encoding="utf-8").splitlines():
            f = line.split()
            if not f or f[0] == "#":
                continue
            if f[0] == "p":
                p = player(ca=int(f[2]), positions=dict(zip(REFERENCE_POSITIONS,map(int,f[3:18]))))
                p["raw_attributes"] = dict(zip(REFERENCE_ATTRIBUTES,map(int,f[18:])))
                players[f[1]] = p
                continue
            p = players[f[1]]
            key, role = bits[int(f[2],16)]
            pos = "stc" if f[3] == "ST" else f[3].lower()
            side = ("left" if pos in tactic.LEFT else "right" if pos in tactic.RIGHT else "centre") if f[4] == "-" else f[4]
            r = evaluate(p,key,pos,side,centre_back_count=3)
            if {"position":pos,"side":side} not in role["placements"]:
                unsupported_placement += 1
                self.assertEqual(r["rating_reason"],"unsupported_role_placement")
                continue
            if not all(1 <= v <= 100 for v in p["raw_attributes"].values()):
                unsupported_input += 1
                self.assertIsNone(r["role_rating"])
                self.assertIsNone(r["role_ability"])
                continue
            compared += 1
            with self.subTest(case=line):
                self.assertEqual((r["role_rating"],r["best_role_rating"]),(int(f[5]),int(f[6])))
        self.assertEqual((compared, unsupported_placement, unsupported_input),(51,100,3))

    def test_rating_and_ability_rank_reversal(self):
        a = evaluate(player(80,ca=90,positions={"gk":20}),"ip.goalkeeper","gk")
        b = evaluate(player(50,ca=140,positions={"gk":20}),"ip.goalkeeper","gk")
        self.assertGreater(a["role_rating"],b["role_rating"])
        self.assertLess(a["role_ability"],b["role_ability"])


if __name__ == "__main__":
    unittest.main()
