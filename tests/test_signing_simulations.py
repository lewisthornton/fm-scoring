"""Invented single-signing scenarios; no live data or transfers."""
import copy
import json
import unittest

import optimal_xi as xi
import squad_depth as depth
import signing_simulations as signing
from test_optimal_xi import DEFAULT, ASYM, eleven, person
from test_squad_depth import assess


def target(key, codes, **kw):
    return person(key, codes, cohorts=("target",), **kw)


def build(people, shape=DEFAULT, **kwargs):
    return signing.build_signing_simulations(shape, assess(people, shape), optimizer=xi, depth_module=depth, **kwargs)


def candidate(report, key):
    return next(e for e in report["candidates"] if e["player_id"] == key)


class SigningTests(unittest.TestCase):
    def test_audit_examples_require_actual_selection_position(self):
        # Invented players reproducing only the two reported familiarity patterns.
        right = target("wide-midfielder", ["mr"], score=20)
        right["raw"].update(positions_amr=12, positions_mr=18)
        pivot = target("defensive-midfielder", ["dm"], score=18)
        pivot["raw"].update(positions_mc=8, positions_dm=16)
        squad = eleven(DEFAULT)
        result = build(squad + [right, pivot])
        wide, dm = candidate(result, "wide-midfielder"), candidate(result, "defensive-midfielder")
        self.assertNotIn("rw", wide["eligible_slot_ids"])
        self.assertEqual(wide["classification"], "no_demonstrated_improvement")
        self.assertFalse(wide["xi"]["enters_xi"])
        self.assertEqual(wide["xi"]["impact"]["outfield_score_gain"], 0)
        self.assertEqual(dm["eligible_slot_ids"], ["dm"])
        self.assertEqual(dm["xi"]["selected_slot_id"], "dm")
        self.assertEqual(dm["xi"]["impact"]["newly_benched_player_ids"], ["dm"])
        self.assertNotIn("lcm", [c["slot_id"] for c in dm["xi"]["impact"]["changes"]])
        self.assertEqual(dm["classification"], "starting_upgrade")
        self.assertEqual(result["eligibility_policy"]["version"], 2)
        strong_squad = [p if p["player_id"] != "dm" else person("dm", ["dm"], score=20) for p in squad]
        depth_only = candidate(build(strong_squad + [pivot]), "defensive-midfielder")
        self.assertEqual(depth_only["classification"], "depth_improvement")
        self.assertFalse(depth_only["xi"]["enters_xi"])
        cover = next(r for r in depth_only["depth"]["coverage_changes"] if r["slot_id"] == "lcm")
        self.assertNotIn("defensive-midfielder", cover["after_direct_ids"])
    def test_starting_upgrade_and_separate_keeper_domain(self):
        people = eleven(DEFAULT) + [target("new-lb", ["dl"], score=18), target("new-gk", ["gk"], score=17, keeper=True)]
        report = build(people)
        lb, gk = candidate(report, "new-lb"), candidate(report, "new-gk")
        self.assertEqual(lb["classification"], "starting_upgrade")
        self.assertEqual(lb["xi"]["selected_slot_id"], "lb")
        self.assertEqual(lb["xi"]["previous_slot_incumbent_id"], "lb")
        self.assertEqual(lb["xi"]["impact"]["newly_benched_player_ids"], ["lb"])
        self.assertAlmostEqual(lb["xi"]["impact"]["outfield_score_gain"], 6)
        self.assertEqual(lb["xi"]["impact"]["goalkeeper_score_gain"], 0)
        self.assertEqual(gk["xi"]["impact"]["outfield_score_gain"], 0)
        self.assertAlmostEqual(gk["xi"]["impact"]["goalkeeper_score_gain"], 5)
        # Displaced original starter loss is compared with the same player ID.
        same = next(r for r in lb["depth"]["same_original_starter_absences"] if r["removed_player_id"] == "lb")
        self.assertEqual(same["impact"]["filled_slot_gain"], 1)
        self.assertNotIn("lb", [r["removed_player_id"] for r in lb["depth"]["new_xi_starter_loss_scenarios"]])

    def test_cascade_and_independent_exact_solver(self):
        people = [person("left", ["dl"], score=10), person("right", ["dl", "dr"], score=19),
                  person("centre", ["dr", "dc"], score=18), person("centre2", ["dc"], score=18)]
        people += [p for p in eleven(DEFAULT) if p["player_id"] not in ("lb", "rb", "lcb", "rcb")]
        people.append(target("new-cb", ["dc"], score=17))
        data = assess(people)
        before = copy.deepcopy(data)
        report = signing.build_signing_simulations(DEFAULT, data, optimizer=xi, depth_module=depth)
        e = candidate(report, "new-cb")
        self.assertEqual(e["classification"], "starting_upgrade")
        self.assertGreaterEqual(e["xi"]["impact"]["positional_change_count"], 2)
        hyp = signing.hypothetical_assessment(data, "new-cb")
        independent = xi.build_optimal_xi(DEFAULT, hyp)
        self.assertEqual(e["xi"]["assignments"], signing.compact(independent["assignments"]))
        self.assertEqual(data, before)

    def test_completeness_incomplete_and_keeper_vacancy(self):
        people = [person("left", ["dl"]), target("right", ["dr"], score=10), target("gk", ["gk"], keeper=True)]
        report = build(people)
        self.assertEqual(report["baseline"]["totals"]["filled_slots"], 1)
        for e in report["candidates"]:
            self.assertEqual(e["classification"], "completeness_upgrade")
            self.assertEqual(e["xi"]["impact"]["filled_slot_gain"], 1)
        self.assertIsNone(candidate(report, "gk")["xi"]["impact"]["goalkeeper_score_gain"])

    def test_depth_only_shared_cover_and_dependency(self):
        people = eleven(DEFAULT) + [person("utility", ["dl", "dr"], score=10), target("reserve", ["dl"], score=9)]
        e = candidate(build(people), "reserve")
        self.assertEqual(e["classification"], "depth_improvement")
        self.assertFalse(e["xi"]["enters_xi"])
        self.assertEqual(e["xi"]["impact"]["outfield_score_gain"], 0)
        self.assertEqual(e["depth"]["bench_capacity_gain"], 1)
        self.assertIn({"player_id": "utility", "slot_id": "lb"}, e["depth"]["relieved_sole_cover_dependencies"])
        pair = next(r for r in e["depth"]["shared_pair_capacity"] if r["slot_ids"] == ["lb", "rb"])
        self.assertEqual((pair["before_capacity"], pair["after_capacity"]), (1, 2))
        utility = candidate(build(eleven(DEFAULT) + [target("utility", ["dl", "dr"], score=10)]), "utility")
        self.assertEqual(utility["depth"]["bench_capacity_gain"], 1)
        self.assertEqual(sum(r["newly_covered"] for r in utility["depth"]["coverage_changes"]), 2)

    def test_tie_break_not_upgrade_and_no_eligible_evidence(self):
        people = eleven(DEFAULT) + [target("aaa", ["dl"], score=12), target("unfamiliar", [], score=20), target("missing", ["dr"], score=20)]
        people[-1]["attrs"].clear()
        report = build(people)
        tie = candidate(report, "aaa")
        self.assertTrue(tie["xi"]["impact"]["tie_break_only"])
        self.assertFalse(tie["xi"]["impact"]["objective_improved"])
        self.assertEqual(candidate(report, "unfamiliar")["classification"], "no_demonstrated_improvement")
        self.assertEqual(candidate(report, "missing")["classification"], "insufficient_evidence")

    def test_category_phase_and_hypothetical_availability(self):
        p = target("loan", [], score=20, availability="unavailable", loan="outgoing")
        p["raw"].update(positions_dr="", accomplished_positions="DR")
        people = eleven(ASYM) + [p, target("incoming", ["dl"], score=18, loan="incoming"), person("both", ["dc"], cohorts=("target", "squad"))]
        report = build(people, ASYM)
        e = candidate(report, "loan")
        self.assertEqual(e["observed_availability"], "unavailable")
        self.assertEqual(e["observed_loan_state"], "outgoing")
        self.assertEqual(e["scenario_assumed_availability"], "available")
        self.assertEqual(e["eligible_slot_ids"], ["rb"])
        self.assertIn("ip_familiarity_below_threshold", next(r for r in e["xi"]["assignments"] if r["slot_id"] == "rb")["warnings"])
        self.assertEqual(candidate(report, "incoming")["observed_loan_state"], "incoming")
        self.assertEqual(candidate(report, "both")["classification"], "already_in_squad")
        self.assertIsNone(candidate(report, "both")["xi"])
        self.assertEqual(candidate(build(people, ASYM, policy={"minimum_familiarity": 16}), "loan")["eligible_slot_ids"], [])

    def test_benchmark_context_and_stale(self):
        people = eleven(DEFAULT) + [target("new", ["dl"], score=18)]
        data = assess(people)
        benchmark = {"version": 1, "status": "available", "career": "invented", "game_date": "2027-01-01", "scoring_model": data["scoring_model"],
                     "competition": {"id": "100"}, "extraction_game_date": "2026-12-15", "reference": {"profiles": {"FB": {"contributing_clubs": 8}}},
                     "comparisons": [{"player_id": "new", "profile": "FB", "reason": None, "percentile": 90, "warnings": [], "sample_size": 40}]}
        old = copy.deepcopy(benchmark)
        e = candidate(build(people, benchmark=benchmark), "new")
        self.assertEqual(e["league_context"]["FB"]["comparison"]["percentile"], 90)
        stale = candidate(build(people, benchmark=dict(benchmark, extraction_game_date="2026-01-01")), "new")
        self.assertIsNone(stale["league_context"]["FB"]["comparison"])
        self.assertEqual(stale["xi"]["hypothetical"], e["xi"]["hypothetical"])
        self.assertEqual(benchmark, old)

    def test_limit_namesakes_reversed_and_conflicts(self):
        people = eleven(DEFAULT) + [target(str(i), ["dl"], score=10, name="Same") for i in range(30)]
        report = build(people, depth_limit=2)
        self.assertEqual(len(report["candidates"]), 30)
        self.assertEqual(report["depth_evaluated_count"], 2)
        self.assertEqual(report["evaluation_coverage"]["xi_evaluated_count"], 30)
        self.assertEqual(report["evaluation_coverage"]["depth_status_counts"], {"evaluated": 2, "not_evaluated_limit": 28})
        self.assertEqual(sum(e["classification"] == "depth_not_evaluated" for e in report["candidates"]), 28)
        self.assertEqual(json.dumps(report), json.dumps(build(list(reversed(people)), depth_limit=2)))
        self.assertTrue(all(e["xi"]["impact"]["monotonic_objective_verified"] for e in report["candidates"]))
        data = assess(people)
        with self.assertRaises(ValueError):
            signing.validate_players(dict(data, players=data["players"] + [data["players"][0]]))
        malformed = copy.deepcopy(data)
        malformed["players"][0]["player_id"] = '["rangers","other","1"]'
        with self.assertRaises(ValueError):
            signing.validate_players(malformed)
        collision = copy.deepcopy(data)
        for p, key in zip(collision["players"], ('["rangers","invented","1|2|2000-01-01"]', '["rangers","invented","1|3|2001-01-01"]')):
            p["player_id"] = key
            for slot in p["slots"]:
                slot["player_id"] = key
        with self.assertRaisesRegex(ValueError, "Conflicting watcher"):
            signing.validate_players(collision)
        self.assertEqual(build(eleven(DEFAULT))["candidates"], [])
        self.assertIn("Signing", signing.render_html(report).title())


if __name__ == "__main__":
    unittest.main()
