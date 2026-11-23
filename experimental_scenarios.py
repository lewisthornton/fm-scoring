"""Invented-only R5B scenarios over an unchanged R5A matrix and solver."""
from copy import deepcopy
from fractions import Fraction

import experimental_xi as xi
import optimal_xi
import role_ability
import tactic


SIGNING_POLICY = "add_target_preserve_availability"


def _scenario(matrix, *, remove=None, sign=None):
    """Only membership/exclusion changes; no rescoring or evidence substitution."""
    result = deepcopy(matrix)
    if remove is not None:
        if remove not in result["players"]:
            raise ValueError("Unknown absent player")
        result["players"].remove(remove)
        result["rows"] = [r for r in result["rows"] if r["player_id"] != remove]
    if sign is not None:
        rows = [r for r in result["rows"] if r["player_id"] == sign]
        if not rows or any("target" not in r["cohorts"] or "squad" in r["cohorts"] for r in rows):
            raise ValueError("Signing requires a target outside the squad")
        for r in rows:
            r["cohorts"] = sorted(set(r["cohorts"]) | {"squad"})
            r["eligibility_reasons"] = [reason for reason in r["eligibility_reasons"]
                                       if reason != "not_active_squad"]
    result.pop("sha256")
    result["sha256"] = tactic.canonical_sha256(result)
    return result


def _eligible(row, objective):
    return not row["eligibility_reasons"] and row["scores"][objective] is not None


def _coverage(matrix, baseline, objective):
    slots = matrix["tactic"]["slots"]
    starters = {r["player_id"]: r["slot_id"] for r in baseline["assignments"] if r["player_id"] is not None}
    by_slot = {r["slot_id"]: r["player_id"] for r in baseline["assignments"]}
    edges, bench = {}, {}
    coverage = []
    for slot in slots:
        sid = slot["id"]
        eligible = sorted((r for r in matrix["rows"] if r["slot_id"] == sid and _eligible(r, objective)),
                          key=lambda r: (-r["scores"][objective], r["player_id"]))
        for r in eligible:
            key = r["player_id"]
            edges.setdefault(key, {})[sid] = r["scores"][objective]
            if key not in starters:
                bench.setdefault(key, {})[sid] = r["scores"][objective]
        alternatives = [{"player_id": r["player_id"], "score": r["scores"][objective],
                         "baseline_slot_id": starters.get(r["player_id"])} for r in eligible
                        if r["player_id"] != by_slot[sid]]
        direct = [r["player_id"] for r in eligible if r["player_id"] not in starters]
        coverage.append({"slot_id": sid, "domain": "goalkeeper" if slot["selection_position"] == "gk" else "outfield",
                         "starter_id": by_slot[sid], "eligible_player_ids": [r["player_id"] for r in eligible],
                         "alternatives": alternatives, "direct_deputy_ids": direct,
                         "single_player_dependency": len(eligible) == 1,
                         "insufficient_direct_cover": not direct})
    def capacity(keeper, excluded=None):
        ids = [r["slot_id"] for r in coverage if (r["domain"] == "goalkeeper") == keeper]
        result = optimal_xi.solve_assignment(ids, {p: {s: v for s, v in e.items() if s in ids}
                                                   for p, e in bench.items() if p != excluded})
        return sum(p is not None for p in result.values())
    capacities = {"goalkeeper": capacity(True), "outfield": capacity(False)}
    return {"slots": coverage, "bench_matching_capacity": capacities,
            "player_coverage": [{"player_id": p, "eligible_slot_ids": list(e), "baseline_slot_id": starters.get(p)}
                                for p, e in sorted(edges.items())],
            "bench_dependencies": [{"player_id": p, "covered_slot_ids": list(e),
                                    "newly_uncovered_slot_ids": [r["slot_id"] for r in coverage
                                                               if r["direct_deputy_ids"] == [p]],
                                    "capacity_without_player": {"goalkeeper": capacity(True, p),
                                                                "outfield": capacity(False, p)}}
                                   for p, e in sorted(bench.items())]}


def _exact(result, keeper):
    out = [Fraction(r["score"]) for r in result["assignments"]
           if r["slot_id"] != keeper and r["player_id"] is not None]
    gk = next(r["score"] for r in result["assignments"] if r["slot_id"] == keeper)
    return result["filled_slots"], sum(out, Fraction(0)), Fraction(gk) if gk is not None else Fraction(-1)


def _impact(before, after, keeper, *, addition):
    if before["objective"] != after["objective"]:
        raise ValueError("Cannot compare different objectives")
    a, b = _exact(before, keeper), _exact(after, keeper)
    if (addition and b < a) or (not addition and b > a):
        raise AssertionError("Scenario violated optimal objective monotonicity")
    old = {r["player_id"]: r["slot_id"] for r in before["assignments"] if r["player_id"] is not None}
    new = {r["player_id"]: r["slot_id"] for r in after["assignments"] if r["player_id"] is not None}
    pairs = list(zip(before["assignments"], after["assignments"], strict=True))
    changes = [{"slot_id": x["slot_id"], "before_player_id": x["player_id"], "after_player_id": y["player_id"]}
               for x, y in pairs if x["player_id"] != y["player_id"]]
    moved = [{"player_id": p, "from_slot_id": old[p], "to_slot_id": s}
             for p, s in new.items() if p in old and old[p] != s]
    return {"filled_slot_change": b[0] - a[0], "objective_improved": b > a,
            "tie_break_only": a == b and bool(changes),
            # Totals are already available on both XI records. Deltas only
            # compare equal cardinalities, and never combine score domains.
            "outfield_score_change": float(b[1] - a[1]) if a[0] == b[0] and (a[2] >= 0) == (b[2] >= 0) else None,
            "goalkeeper_score_change": float(b[2] - a[2]) if a[0] == b[0] and a[2] >= 0 and b[2] >= 0 else None,
            "changes": changes, "changed_slot_count": len(changes), "moved_starters": moved,
            "positional_change_count": len(moved), "displaced_player_ids": [p for p in old if p not in new],
            "promoted_player_ids": [p for p in new if p not in old],
            "newly_vacant_slot_ids": [x["slot_id"] for x, y in pairs if x["player_id"] is not None and y["player_id"] is None],
            "newly_filled_slot_ids": [x["slot_id"] for x, y in pairs if x["player_id"] is None and y["player_id"] is not None],
            "weaker_slot_ids": [x["slot_id"] for x, y in pairs if x["score"] is not None and y["score"] is not None and y["score"] < x["score"]]}


def _absences(matrix, baseline, objective, keeper):
    cases = []
    for row in baseline["assignments"]:
        p, sid = row["player_id"], row["slot_id"]
        if p is None:
            continue
        revised = xi.optimise(_scenario(matrix, remove=p), objective=objective)
        replacement = next(r for r in revised["assignments"] if r["slot_id"] == sid)
        impact = _impact(baseline, revised, keeper, addition=False)
        cases.append({"removed_player_id": p, "original_assignment": row, "replacement_assignment": replacement,
                      "baseline_matrix_sha256": baseline["matrix_sha256"], "reoptimised": revised, "impact": impact,
                      "baseline_totals": {k: baseline[k] for k in ("filled_slots", "outfield_total", "goalkeeper_total")},
                      "filled_slot_loss": -impact["filled_slot_change"],
                      "outfield_score_loss": None if impact["outfield_score_change"] is None else -impact["outfield_score_change"],
                      "goalkeeper_score_loss": None if impact["goalkeeper_score_change"] is None else -impact["goalkeeper_score_change"]})
    return cases


def build_report(matrix, *, objective, candidate_ids=(), signing_policy=None):
    """Independent one-player counterfactuals; requires an explicit signing policy."""
    ids = list(candidate_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate candidate ID")
    if ids and signing_policy != SIGNING_POLICY:
        raise ValueError("Explicit hypothetical signing policy required")
    if signing_policy is not None and signing_policy != SIGNING_POLICY:
        raise ValueError("Unknown signing policy")
    # Same invented-only boundary as the R5A input builder.
    if not matrix["career"].startswith("invented:") or any(
            r["career"] != matrix["career"] or not r["player_id"].startswith(matrix["career"] + ":")
            or r["source"] != {"kind": "invented_fixture"} for r in matrix["rows"]):
        raise ValueError("Only invented reference fixture matrices permitted")
    if (matrix["model_sha256"] != role_ability.MODEL_SHA256
            or matrix["catalogue_sha256"] != role_ability.CATALOGUE_SHA256
            or matrix["legacy_model_sha256"] != xi.LEGACY_SHA256
            or matrix["tactic_sha256"] != tactic.tactic_sha256(matrix["tactic"])):
        raise ValueError("Unexpected experimental model or tactic provenance")
    for row in matrix["rows"]:
        compatible = (type(row["database_version"]) is int and
                      {"game_build": row["game_build"], "database_version": row["database_version"]}
                      in role_ability.MODEL["supported_builds"])
        if (row["build_compatible"] != compatible or
                (not compatible and any(row["scores"][o] is not None for o in ("role_rating", "role_ability")))):
            raise ValueError("Incompatible build evidence in experimental matrix")
    baseline = xi.optimise(matrix, objective=objective)
    keeper = next(s["id"] for s in matrix["tactic"]["slots"] if s["selection_position"] == "gk")
    coverage = _coverage(matrix, baseline, objective)
    absent = _absences(matrix, baseline, objective, keeper)
    recruits = []
    for p in sorted(ids):
        signed = _scenario(matrix, sign=p)
        revised = xi.optimise(signed, objective=objective)
        impact = _impact(baseline, revised, keeper, addition=True)
        after_depth = _coverage(signed, revised, objective)
        cover_changes = [{"slot_id": a["slot_id"], "before_direct_deputy_ids": a["direct_deputy_ids"],
                          "after_direct_deputy_ids": b["direct_deputy_ids"],
                          "direct_cover_count_change": len(b["direct_deputy_ids"]) - len(a["direct_deputy_ids"]),
                          "eligible_count_change": len(b["eligible_player_ids"]) - len(a["eligible_player_ids"])}
                         for a, b in zip(coverage["slots"], after_depth["slots"], strict=True)]
        resilience = []
        for event in absent:
            removed = event["removed_player_id"]
            new_absence = xi.optimise(_scenario(signed, remove=removed), objective=objective)
            resilience.append({"removed_player_id": removed, "original_slot_id": event["original_assignment"]["slot_id"],
                               "baseline_without_player": event["reoptimised"], "signing_without_player": new_absence,
                               "impact": _impact(event["reoptimised"], new_absence, keeper, addition=True)})
        improved_slots = [c["slot_id"] for c in cover_changes if c["direct_cover_count_change"] > 0]
        resilient_slots = [r["original_slot_id"] for r in resilience if r["impact"]["objective_improved"]]
        capacity_change = {d: after_depth["bench_matching_capacity"][d] - coverage["bench_matching_capacity"][d]
                           for d in coverage["bench_matching_capacity"]}
        improved = bool(improved_slots or resilient_slots or any(v > 0 for v in capacity_change.values()))
        selected = next((r for r in revised["assignments"] if r["player_id"] == p), None)
        recruits.append({"candidate_id": p, "baseline_matrix_sha256": matrix["sha256"],
                         "objective": objective, "signing_policy": signing_policy,
                         "model_sha256": matrix["model_sha256"], "legacy_model_sha256": matrix["legacy_model_sha256"],
                         "enters_xi": selected is not None, "selected_slot_id": selected["slot_id"] if selected else None,
                         "eligible_slot_ids": [r["slot_id"] for r in signed["rows"] if r["player_id"] == p and _eligible(r, objective)],
                         "reoptimised": revised, "impact": impact, "depth": after_depth,
                         "coverage_changes": cover_changes, "depth_improved_slot_ids": improved_slots,
                         "absence_resilience_improved_slot_ids": resilient_slots,
                         "bench_capacity_change": capacity_change, "original_starter_absences": resilience,
                         "depth_improved": improved, "cover_without_xi_improvement": improved and not impact["objective_improved"],
                         "candidate_unavailable_edges": [{"slot_id": r["slot_id"], "eligibility_reasons": r["eligibility_reasons"],
                                                         "score_unavailable_reasons": r["score_unavailable_reasons"][objective]}
                                                        for r in signed["rows"] if r["player_id"] == p and not _eligible(r, objective)]})
    return deepcopy({"version": 1, "experimental_only": True, "objective": objective, "units": xi.OBJECTIVES[objective],
                     "provenance": {k: matrix[k] for k in ("career", "tactic", "tactic_sha256", "catalogue_sha256",
                                                          "model_sha256", "legacy_model_sha256", "eligibility_policy")},
                     "baseline_matrix_sha256": matrix["sha256"], "baseline": baseline, "depth": coverage,
                     "player_build_evidence": [dict(player_id=r["player_id"], game_build=r["game_build"],
                                                   database_version=r["database_version"], build_compatible=r["build_compatible"],
                                                   evidence_status=r["evidence_status"])
                                               for r in matrix["rows"] if r["slot_id"] == keeper],
                     "starter_loss_scenarios": absent, "recruitment_scenarios": recruits,
                     "unavailable_edges": [{"player_id": r["player_id"], "slot_id": r["slot_id"],
                                            "eligibility_reasons": r["eligibility_reasons"],
                                            "score_unavailable_reasons": r["score_unavailable_reasons"][objective],
                                            "game_build": r["game_build"], "database_version": r["database_version"],
                                            "build_compatible": r["build_compatible"], "evidence_status": r["evidence_status"]}
                                           for r in matrix["rows"] if not _eligible(r, objective)],
                     "limitations": ["Invented fixtures only; no game validation or real-save activation.",
                                     "Individual cover is not simultaneous cover; matching capacity counts distinct backups.",
                                     "Missing scores are unavailable, not zero; unequal cardinalities have no score delta.",
                                     "Signing adds squad membership only; availability evidence is unchanged.",
                                     "No fees, wages, registration, fitness or match-performance predictions."]})


def compare_objectives(matrix, *, candidate_ids=(), signing_policy=None):
    """Compare decisions, never numeric totals across objectives."""
    ids = tuple(candidate_ids)
    reports = {o: build_report(matrix, objective=o, candidate_ids=ids, signing_policy=signing_policy)
               for o in xi.OBJECTIVES}
    decisions = [{"candidate_id": p, "objectives": {
        o: {**{k: r[k] for k in ("enters_xi", "selected_slot_id", "depth_improved", "cover_without_xi_improvement")},
            "objective_improved": r["impact"]["objective_improved"], "filled_slot_change": r["impact"]["filled_slot_change"]}
        for o, report in reports.items() for r in report["recruitment_scenarios"] if r["candidate_id"] == p}}
        for p in sorted(ids)]
    return {"experimental_only": True, "baseline_matrix_sha256": matrix["sha256"],
            "reports": reports, "candidate_decisions": decisions}
