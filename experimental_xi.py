"""R5A in-memory invented/reference fixtures only. No save or report adapters."""
from copy import deepcopy
import math

import formation
import optimal_xi
import role_ability
import scoring
import tactic
import tactical_assessment


LEGACY_SHA256 = "05235aea21929709286e18c1911a512f834dd5f897b59077a79d841efd31e93e"
OBJECTIVES = {
    "fm27v2": "weighted attribute mean (1–20)",
    "role_rating": "phase-weighted absolute reference rating (0–200)",
    "role_ability": "phase-weighted CA-scaled reference ability (0–200)",
}


def build_matrix(config, catalogue, legacy_model, players, *, career, policy=None):
    """Validate raw manual v2 config and score invented scoped observations.

    Each player supplies R3 fields, attrs (display values), keeper, cohorts,
    availability, and optional natural/accomplished category text. No raw
    attribute reconstruction. Explicit invented provenance is mandatory.
    """
    if not isinstance(career, str) or not career.startswith("invented:"):
        raise ValueError("Experimental fixture career required")
    if config.get("source", {}).get("kind") != "manual":
        raise ValueError("Manual fixture tactic required")
    if tactic.canonical_sha256(catalogue) != role_ability.CATALOGUE_SHA256:
        raise ValueError("Pinned R3 catalogue required")
    if tactic.canonical_sha256(legacy_model) != LEGACY_SHA256:
        raise ValueError("Pinned fm27v2 model required")
    validated = tactic.validate_tactic(config, catalogue)
    selection = {"version": 1, "tactic": validated,
                 "tactic_sha256": tactic.tactic_sha256(validated),
                 "catalogue": {"sha256": role_ability.CATALOGUE_SHA256}}
    policy = optimal_xi.eligibility_policy(policy)
    slots = validated["slots"]
    weights = validated["phase_weights"]
    people = sorted(players, key=lambda p: p["player_id"])
    ids = [p["player_id"] for p in people]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate player identity")
    rows = []
    for p in people:
        if (p.get("career") != career or not p["player_id"].startswith(career + ":")
                or p.get("source") != {"kind": "invented_fixture"}):
            raise ValueError("Only career-scoped invented fixture observations permitted")
        if type(p.get("keeper")) is not bool:
            raise ValueError("Explicit keeper classification required")
        raw = {"positions_" + c: v for c, v in p.get("positions", {}).items()}
        raw.update({k: p[k] for k in ("natural_positions", "accomplished_positions") if k in p})
        evidence = tactical_assessment.position_evidence(raw, formation.FM_POSITION_CODES)
        roles = role_ability.assess_tactic(selection, catalogue, p,
                    model_id=role_ability.FM27_MODEL_ID, game_build=p.get("game_build"),
                    database_version=p.get("database_version"))
        groups = {"GK": legacy_model["gk"]} if p["keeper"] else legacy_model["outfield"]
        attrs = {k: v for k, v in p.get("attrs", {}).items()
                 if type(v) in (int, float) and math.isfinite(v) and 1 <= v <= 20}
        scores = scoring.weighted(attrs, groups)
        for slot, role in zip(slots, roles["slots"], strict=True):
            sid = slot["id"]
            profile = slot["legacy_profile"]
            legacy = scores.get(profile)
            # Existing exclusion function includes a legacy score check;
            # separate this objective-specific requirement from eligibility.
            shape = {**slot, "profile": "GK" if slot["selection_position"] == "gk" else profile}
            context = {"accepted_positions": {c: evidence[c] for c in slot["positions"]},
                       "attribute_profile_score": legacy,
                       "attribute_profile_reason": None if legacy is not None else "missing_attributes",
                       **{phase: {"familiarity": evidence.get(slot[phase]["position"])}
                          for phase in tactic.PHASES}}
            reasons = optimal_xi.exclusion_reasons(p, shape, context, policy, phase_weights=weights)
            reasons = [r for r in reasons if r != "incomplete_attribute_profile"]
            rating, missing = role_ability.combine_abilities(
                {phase: role[phase]["role_rating"] for phase in tactic.PHASES}, weights)
            metrics = {"fm27v2": legacy, "role_rating": rating,
                       "role_ability": role["combined_role_ability"]}
            missing_reasons = {
                "fm27v2": [] if legacy is not None else ["missing_or_inapplicable_legacy_profile"],
                "role_rating": [phase + ":" + str(role[phase]["rating_reason"]) for phase in missing],
                "role_ability": [phase + ":" + str(role[phase]["ability_reason"])
                                 for phase in role["missing_weighted_phases"]],
            }
            rows.append({"career": career, "player_id": p["player_id"], "slot_id": sid,
                         "selection_position": slot["selection_position"], "positions": slot["positions"],
                         "position_evidence": context["accepted_positions"],
                         "phase_familiarity": {phase: context[phase]["familiarity"] for phase in tactic.PHASES},
                         "eligibility_position": optimal_xi.qualifying_position(shape, context, policy),
                         "eligibility_reasons": reasons, "availability": p["availability"],
                         "cohorts": sorted(p["cohorts"]), "keeper": p["keeper"],
                         "record_game_date": p.get("record_game_date"), "source": p["source"],
                         "game_build": p.get("game_build"), "database_version": p.get("database_version"),
                         "model_unavailable_reason": roles["model_unavailable_reason"],
                         "build_compatible": type(p.get("database_version")) is int and
                         {"game_build": p.get("game_build"), "database_version": p.get("database_version")}
                         in role_ability.MODEL["supported_builds"],
                         "evidence_status": roles["model"]["evidence_status"] if roles["model_unavailable_reason"] is None else None,
                         "tactic_sha256": selection["tactic_sha256"],
                         "catalogue_sha256": roles["catalogue_sha256"],
                         "model_sha256": roles["model"]["sha256"], "legacy_model_sha256": LEGACY_SHA256,
                         "ip": role["ip"], "oop": role["oop"], "phase_weights": weights,
                         "scores": metrics, "score_unavailable_reasons": missing_reasons})
    matrix = {"version": 1, "experimental_only": True, "career": career,
              "tactic": validated, "tactic_sha256": selection["tactic_sha256"],
              "catalogue_sha256": role_ability.CATALOGUE_SHA256,
              "model_sha256": role_ability.MODEL_SHA256, "legacy_model_sha256": LEGACY_SHA256,
              "eligibility_policy": policy, "players": ids, "rows": rows}
    matrix["sha256"] = tactic.canonical_sha256(matrix)
    return deepcopy(matrix)


def optimise(matrix, *, objective):
    """Explicit objective, maximum cardinality then score; independent GK domain."""
    if objective not in OBJECTIVES:
        raise ValueError("Unknown experimental objective")
    if (matrix.get("experimental_only") is not True or matrix.get("version") != 1
            or matrix.get("sha256") != tactic.canonical_sha256({k: v for k, v in matrix.items() if k != "sha256"})):
        raise ValueError("Invalid experimental matrix")
    slots = matrix["tactic"]["slots"]
    ids = [s["id"] for s in slots]
    lookup = {(r["player_id"], r["slot_id"]): r for r in matrix["rows"]}
    if len(lookup) != len(matrix["rows"]) or set(lookup) != {(p, s) for p in matrix["players"] for s in ids}:
        raise ValueError("Incomplete or duplicate matrix entries")
    edges = {}
    for (p, s), row in lookup.items():
        score = row["scores"][objective]
        if not row["eligibility_reasons"] and score is not None:
            edges.setdefault(p, {})[s] = score
    gk = [s["id"] for s in slots if s["selection_position"] == "gk"]
    out = [s for s in ids if s not in gk]
    def domain(keys):
        return optimal_xi.solve_assignment(keys, {p: {s: v for s, v in e.items() if s in keys}
                                                  for p, e in edges.items()})
    chosen = domain(gk) | domain(out)
    assignments = []
    for s in ids:
        p = chosen[s]
        assignments.append({"slot_id": s, "player_id": p,
                            "score": edges[p][s] if p is not None else None,
                            "vacancy_reason": None if p is not None else
                            "eligible_players_assigned_elsewhere" if any(s in e for e in edges.values())
                            else "no_eligible_player_with_objective_score"})
    count = sum(p is not None for p in chosen.values())
    return {"objective": objective, "units": OBJECTIVES[objective], "matrix_sha256": matrix["sha256"],
            "experimental_only": True, "filled_slots": count,
            "status": "complete" if count == len(ids) else "incomplete" if count else "infeasible",
            "assignments": assignments,
            "outfield_total": math.fsum(r["score"] for r in assignments if r["slot_id"] in out and r["score"] is not None),
            "goalkeeper_total": next(r["score"] for r in assignments if r["slot_id"] in gk)}


def compare(matrix):
    """Compare assignments, never subtract scores from different objectives."""
    results = {key: optimise(matrix, objective=key) for key in OBJECTIVES}
    baseline = results["fm27v2"]["assignments"]
    changes = {key: [{"slot_id": a["slot_id"], "legacy_player": b["player_id"],
                      "objective_player": a["player_id"]} for a, b in zip(value["assignments"], baseline)
                     if a["player_id"] != b["player_id"]] for key, value in results.items()}
    return {"experimental_only": True, "matrix_sha256": matrix["sha256"],
            "results": results, "changes_from_legacy": changes}
