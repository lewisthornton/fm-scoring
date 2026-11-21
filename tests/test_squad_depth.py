"""Invented squad depth and exact reoptimisation regression fixtures."""
import copy
import json
import unittest

import formation
import optimal_xi as xi
import scoring
import squad_depth as depth
import tactical_assessment as tactical
from test_optimal_xi import ASYM, DEFAULT, MODEL, eleven, person


def assess(people, shape=DEFAULT):
    return tactical.build_assessments(shape, MODEL, people, codes=formation.FM_POSITION_CODES,
                                      scorer=scoring.weighted, career="invented", formation_source="fixture",
                                      model_sha256="model")


def report(people, shape=DEFAULT, benchmark=None, policy=None):
    return depth.build_squad_depth(shape, assess(people, shape), benchmark, optimizer=xi, policy=policy)


def coverage(result, slot):
    return next(r for r in result["coverage"] if r["slot_id"] == slot)


def scenario(result, player):
    return next(r for r in result["starter_loss_scenarios"] if r["removed_player_id"] == player)


class SquadDepthTests(unittest.TestCase):
    def test_phase_gate_and_relaxed_cover_use_same_predicate(self):
        people = eleven(ASYM) + [person("reserve-rb", ["wbr"], score=10)]
        strict = report(people, ASYM)
        relaxed = report(people, ASYM, policy={"mode": "relaxed"})
        self.assertNotIn("reserve-rb", coverage(strict, "rb")["direct_deputy_ids"])
        self.assertIn("reserve-rb", coverage(relaxed, "rb")["direct_deputy_ids"])
        gated = report(people, ASYM, policy={"mode": "relaxed", "phase_eligibility": "require_weighted_phases"})
        self.assertNotIn("reserve-rb", coverage(gated, "rb")["direct_deputy_ids"])
        self.assertEqual(gated["eligibility_policy"], gated["baseline"]["eligibility_policy"])
    def test_complete_with_direct_replacements_and_distinct_cbs(self):
        people = eleven(DEFAULT) + [person("reserve-" + s["id"], [s["positions"][0]], score=10,
                                          keeper=s["profile"] == "GK") for s in DEFAULT["slots"]]
        result = report(people)
        self.assertEqual(result["summary"]["baseline_filled_slots"], 11)
        self.assertEqual(len(result["starter_loss_scenarios"]), 11)
        self.assertTrue(all(s["filled_slot_loss"] == 0 for s in result["starter_loss_scenarios"]))
        self.assertEqual(coverage(result, "lb")["effective_deputy_id"], "reserve-lb")
        lb = scenario(result, "lb")
        self.assertEqual(lb["changed_slot_count"], 1)
        self.assertEqual(lb["positional_change_count"], 0)
        self.assertEqual(lb["moved_starters"], [])
        self.assertIn("changed slots: 1, repositioned starters: 0", depth.render_html(result))
        self.assertEqual(coverage(result, "lcb")["direct_deputy_ids"], ["reserve-lcb", "reserve-rcb"])
        self.assertEqual(coverage(result, "rcb")["direct_deputy_ids"], ["reserve-lcb", "reserve-rcb"])
        self.assertEqual(result["bench_only_matching_capacity"], 11)
        gk = scenario(result, "gk")
        self.assertAlmostEqual(gk["goalkeeper_score_loss"], 2)
        self.assertEqual(gk["outfield_score_loss"], 0)

    def test_chain_beats_highest_direct_deputy(self):
        people = [person("lb", ["dl"], score=20), person("rb", ["dl", "dr"], score=19),
                  person("cb", ["dr", "dc"], score=18), person("cb2", ["dc"], score=18),
                  person("reserve-cb", ["dc"], score=17), person("direct-lb", ["dl"], score=10)]
        people += [p for p in eleven(DEFAULT) if p["player_id"] not in ("lb", "rb", "lcb", "rcb")]
        result = report(people)
        event = scenario(result, "lb")
        self.assertEqual(coverage(result, "lb")["direct_deputy_ids"], ["direct-lb"])
        self.assertEqual(event["effective_deputy_id"], "rb")
        self.assertEqual(coverage(result, "lb")["effective_deputy_status"], "moved_starter")
        self.assertEqual(event["filled_slot_loss"], 0)
        # Stable CB tie-breaking may also swap the other centre-back.
        self.assertGreaterEqual(len(event["moved_starters"]), 2)
        self.assertEqual(event["positional_change_count"], len(event["moved_starters"]))
        self.assertEqual(event["changed_slot_count"], len(event["changes"]))
        self.assertGreater(event["changed_slot_count"], event["positional_change_count"])
        self.assertEqual({m["player_id"] for m in event["moved_starters"]} & {"rb", "cb"}, {"rb", "cb"})
        self.assertEqual(event["promoted_player_ids"], ["reserve-cb"])
        self.assertGreater(event["reoptimised"]["outfield_total"], result["baseline"]["outfield_total"] - 10)
        self.assertIn("lb", next(v for v in result["versatility"] if v["player_id"] == "rb")["eligible_slot_ids"])

    def test_shared_utility_cover_is_not_simultaneous(self):
        people = eleven(DEFAULT) + [person("utility", ["dl", "dr"], score=10)]
        result = report(people)
        for slot in ("lb", "rb"):
            self.assertEqual(coverage(result, slot)["direct_deputy_ids"], ["utility"])
            self.assertEqual(coverage(result, slot)["cover_type"], "shared_only")
        pair = next(s for s in result["shared_cover"] if s["slot_ids"] == ["lb", "rb"])
        self.assertEqual(pair["simultaneously_coverable_slots"], 1)
        dependency = result["bench_cover_dependencies"][0]
        self.assertEqual(dependency["newly_uncovered_slot_ids"], ["lb", "rb"])
        self.assertEqual(dependency["simultaneous_capacity_without_player"], 0)
        self.assertEqual(result["bench_only_matching_capacity"], 1)

    def test_incomplete_baseline_and_no_keeper(self):
        result = report([person("defender", ["dc"]), person("keeper", ["gk"], keeper=True)])
        self.assertEqual(result["summary"]["baseline_filled_slots"], 2)
        self.assertEqual(len(result["summary"]["baseline_vacant_slot_ids"]), 9)
        self.assertEqual(scenario(result, "keeper")["filled_slot_loss"], 1)
        self.assertIsNone(scenario(result, "keeper")["goalkeeper_score_loss"])
        self.assertIsNone(scenario(result, "keeper")["reoptimised"]["goalkeeper_total"])
        self.assertEqual(scenario(result, "defender")["filled_slot_loss"], 1)
        for event in result["starter_loss_scenarios"]:
            self.assertEqual(event["changed_slot_count"], 1)
            self.assertEqual(event["positional_change_count"], 0)
            self.assertEqual(len(event["newly_vacant_slot_ids"]), 1)
        self.assertEqual(coverage(result, "rcb")["effective_deputy_status"], "baseline_vacant")
        self.assertEqual(report([])["starter_loss_scenarios"], [])

    def test_partial_baseline_change_counts_are_deterministic(self):
        people = [person("lb", ["dl"], score=20), person("rb", ["dl", "dr"], score=19),
                  person("reserve-rb", ["dr"], score=10)]
        result = report(people)
        self.assertEqual(result["summary"]["baseline_filled_slots"], 2)
        lb = scenario(result, "lb")
        self.assertEqual((lb["changed_slot_count"], lb["positional_change_count"]), (2, 1))
        self.assertEqual(lb["moved_starters"], [{"player_id": "rb", "from_slot_id": "rb", "to_slot_id": "lb"}])
        rb = scenario(result, "rb")
        self.assertEqual((rb["changed_slot_count"], rb["positional_change_count"]), (1, 0))
        self.assertEqual(result, report(list(reversed(people))))

    def test_policy_loan_and_category_evidence(self):
        category = person("category", [], score=11)
        category["raw"].update(positions_dr="", accomplished_positions="DR")
        missing = person("missing", ["dr"], score=20)
        missing["attrs"].clear()
        people = eleven(DEFAULT) + [category, missing, person("incoming", ["dr"], score=10, loan="incoming"),
                                    person("outgoing", ["dr"], score=20, availability="unavailable", loan="outgoing"),
                                    person("target", ["dr"], score=20, cohorts=("target",)),
                                    person("unknown", ["dr"], score=10, availability="unknown")]
        result = report(people)
        row = coverage(result, "rb")
        self.assertEqual(row["direct_deputy_ids"], ["category", "incoming"])
        evidence = next(e for e in row["eligible_players"] if e["player_id"] == "category")["assessment"]
        self.assertIsNone(evidence["accepted_positions"]["dr"]["rating"])
        self.assertIsNone(evidence["ip"]["observed_role_suitability"])
        self.assertIn("incomplete_attribute_profile", next(e for e in row["rejected_squad_players"] if e["player_id"] == "missing")["reasons"])
        permissive = report(people, policy={"allow_unknown_availability": True, "minimum_familiarity": 16})
        self.assertEqual(coverage(permissive, "rb")["direct_deputy_ids"], ["incoming", "unknown"])

    def test_asymmetric_phase_warnings_and_independent_solves(self):
        people = eleven(ASYM) + [person("backup-rb", ["dr"], score=10)]
        data = assess(people, ASYM)
        result = depth.build_squad_depth(ASYM, data, optimizer=xi)
        for event in result["starter_loss_scenarios"]:
            independent = xi.build_optimal_xi(ASYM, data, excluded_player_ids=[event["removed_player_id"]])
            self.assertEqual([(a["slot_id"], a["player_id"]) for a in independent["assignments"]],
                             [(a["slot_id"], a["player_id"]) for a in event["assignments"]])
            self.assertEqual(depth.totals(independent), event["reoptimised"])
        rb = scenario(result, "rb")
        self.assertIn("ip_familiarity_below_threshold", next(a for a in rb["assignments"] if a["slot_id"] == "rb")["warnings"])

    def test_benchmarks_and_stale_no_effect_on_assignment(self):
        people = eleven(DEFAULT) + [person("backup-rb", ["dr"], score=10)]
        data = assess(people)
        benchmark = {"version": 1, "status": "available", "career": "invented", "game_date": "2027-01-01",
                     "scoring_model": data["scoring_model"], "competition": {"id": "100"}, "extraction_game_date": "2026-12-15",
                     "reference": {"profiles": {"FB": {"contributing_clubs": 8}}},
                     "comparisons": [{"player_id": p, "profile": "FB", "reason": None, "percentile": percentile,
                                      "sample_size": 40, "season_start_year": 2026, "difference_from_median": 1, "warnings": []}
                                     for p, percentile in (("rb", 80), ("backup-rb", 50))]}
        before = copy.deepcopy(benchmark)
        contextual = report(people, benchmark=benchmark)
        self.assertEqual(benchmark, before)
        row = coverage(contextual, "rb")
        for p in row["eligible_players"]:
            self.assertEqual(p["league"]["comparison"]["contributing_clubs"], 8)
        self.assertEqual(scenario(contextual, "rb")["reoptimised"], scenario(report(people), "rb")["reoptimised"])
        stale = report(people, benchmark=dict(benchmark, extraction_game_date="2026-11-01"))
        self.assertTrue(all(p["league"]["comparison"] is None for p in coverage(stale, "rb")["eligible_players"]))

    def test_namesakes_determinism_provenance_and_no_mutation(self):
        people = [person("b", ["dc"], name="Same"), person("a", ["dc"], name="Same"), person("c", ["dc"], name="Same")]
        data = assess(people)
        baseline = xi.build_optimal_xi(DEFAULT, data)
        before = copy.deepcopy((data, baseline))
        result = depth.build_squad_depth(DEFAULT, data, optimizer=xi, baseline=baseline)
        self.assertEqual((data, baseline), before)
        self.assertEqual(result["baseline"], baseline)
        self.assertEqual(json.dumps(result), json.dumps(report(list(reversed(people)))))
        self.assertEqual(scenario(result, "a")["removed_player_id"], "a")
        with self.assertRaises(ValueError):
            depth.build_squad_depth(DEFAULT, data, optimizer=xi, baseline=dict(baseline, career="other"))
        with self.assertRaises(ValueError):
            xi.build_optimal_xi(DEFAULT, data, excluded_player_ids=["missing"])
        result["baseline"]["assignments"].clear()
        self.assertEqual((data, baseline), before)

    def test_cardinality_before_scores_and_html(self):
        people = eleven(DEFAULT) + [person("reserve-gk", ["gk"], score=1, keeper=True)]
        result = report(people)
        self.assertEqual(result["starter_loss_scenarios"][-1]["removed_player_id"], "gk")
        self.assertTrue(all(s["monotonic_objective_verified"] for s in result["starter_loss_scenarios"]))
        view = depth.render_html(report([person("x", ["dc"], name="<script>bad</script>")]))
        self.assertIn("&lt;script&gt;", view)
        self.assertNotIn("<script>", view)


if __name__ == "__main__":
    unittest.main()
