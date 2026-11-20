"""Exact, independent starting-XI assignment over scoped tactical assessments."""
from html import escape
from datetime import date
import hashlib
import json
import math


DEFAULT_POLICY = {"version": 2, "minimum_familiarity": 15, "allow_category_evidence": True,
                  "allow_unknown_availability": False, "mode": "strict", "phase_eligibility": "context_only"}


def eligibility_policy(settings=None):
    if settings is not None and not isinstance(settings, dict):
        raise ValueError("XI policy must be a JSON object")
    policy = {**DEFAULT_POLICY, **(settings or {})}
    if set(policy) != set(DEFAULT_POLICY) or type(policy["version"]) is not int or policy["version"] not in (1, 2):
        raise ValueError("Unsupported XI eligibility policy")
    # Legacy settings retain their thresholds, not the unsafe broad eligibility.
    policy["version"] = 2
    if type(policy["minimum_familiarity"]) is not int or not 1 <= policy["minimum_familiarity"] <= 20:
        raise ValueError("XI minimum familiarity must be an integer from 1 to 20")
    if any(type(policy[k]) is not bool for k in ("allow_category_evidence", "allow_unknown_availability")):
        raise ValueError("XI policy switches must be booleans")
    if policy["mode"] not in ("strict", "relaxed") or policy["phase_eligibility"] not in ("context_only", "require_weighted_phases"):
        raise ValueError("Invalid XI selection mode or phase eligibility rule")
    return policy


def solve_assignment(slot_ids, edges):
    """Exact max-cardinality then max-weight matching; edges[player_id][slot_id]=score.

    DP processes each stable player ID once and stores the best assignment for
    each occupied-slot bitmask. Scores are exact binary rational integers on a
    common denominator; equal scores prefer lexicographically smaller IDs in
    declared slot order, vacancies last. O(players * slots * 2**slots).
    """
    slots = tuple(slot_ids)
    if len(set(slots)) != len(slots):
        raise ValueError("Duplicate assignment slot ID")
    players = sorted(edges)
    index = {slot: i for i, slot in enumerate(slots)}
    ratios = {}
    denominator = 1
    for player in players:
        for slot, score in edges[player].items():
            if slot not in index or type(score) not in (int, float) or not math.isfinite(score):
                raise ValueError("Invalid assignment edge")
            numerator, divisor = score.as_integer_ratio()
            ratios[player, slot] = numerator, divisor
            denominator = max(denominator, divisor)
    vacancy = len(players)
    states = {0: (0, (vacancy,) * len(slots))}
    for rank, player in enumerate(players):
        updated = states.copy()
        for mask, (total, chosen) in states.items():
            for slot in edges[player]:
                i = index[slot]
                bit = 1 << i
                if mask & bit:
                    continue
                numerator, divisor = ratios[player, slot]
                value = total + numerator * (denominator // divisor)
                assignment = chosen[:i] + (rank,) + chosen[i+1:]
                old = updated.get(mask | bit)
                if old is None or value > old[0] or (value == old[0] and assignment < old[1]):
                    updated[mask | bit] = value, assignment
        states = updated
    _, (_, best) = min(states.items(), key=lambda item: (-item[0].bit_count(), -item[1][0], item[1][1]))
    return {slot: players[rank] if rank != vacancy else None for slot, rank in zip(slots, best)}


def confirmed(evidence, policy):
    if not evidence:
        return False
    if evidence.get("status") == "observed":
        return evidence["rating"] >= policy["minimum_familiarity"]
    return (policy["allow_category_evidence"] and evidence.get("status") == "inferred_category"
            and evidence["lower_bound"] >= policy["minimum_familiarity"])


def qualifying_position(slot, evidence, policy):
    position = slot.get("selection_position", slot["positions"][0])
    codes = [position] if policy["mode"] == "strict" else [position] + [c for c in slot["positions"] if c != position]
    return next((code for code in codes if confirmed(evidence["accepted_positions"].get(code), policy)), None)


def exclusion_reasons(player, slot, evidence, policy, *, phase_weights=None):
    reasons = []
    if "squad" not in player["cohorts"]:
        reasons.append("not_active_squad")
    if player["availability"] == "unavailable":
        reasons.append("unavailable")
    elif player["availability"] != "available" and not (player["availability"] == "unknown" and policy["allow_unknown_availability"]):
        reasons.append("unknown_availability")
    if bool(player["keeper"]) != (slot["profile"] == "GK"):
        reasons.append("incompatible_player_type")
    if evidence is None:
        return reasons + ["missing_slot_assessment"]
    score = evidence["attribute_profile_score"]
    if type(score) not in (int, float) or not math.isfinite(score) or evidence["attribute_profile_reason"] is not None:
        reasons.append("incomplete_attribute_profile")
    if qualifying_position(slot, evidence, policy) is None:
        reasons.append("selection_position_familiarity_not_confirmed" if policy["mode"] == "strict" else "accepted_position_familiarity_not_confirmed")
    if policy["phase_eligibility"] == "require_weighted_phases":
        if phase_weights is None:
            raise ValueError("Strict phase eligibility requires formation phase weights")
        for phase in ("ip", "oop"):
            if phase_weights[phase] > 0 and not confirmed(evidence[phase]["familiarity"], policy):
                reasons.append(phase + "_phase_familiarity_not_confirmed")
    return reasons


def benchmark_context(benchmark, assessment):
    if not benchmark or benchmark.get("status") != "available":
        return {}, (benchmark or {}).get("reason", "benchmark_not_available")
    if (benchmark.get("version") != 1 or any(benchmark.get(key) != assessment.get(key) for key in ("career", "game_date"))
            or benchmark.get("scoring_model") != assessment.get("scoring_model")):
        return {}, "benchmark_provenance_mismatch"
    try:
        age = (date.fromisoformat(assessment["game_date"]) - date.fromisoformat(benchmark["extraction_game_date"])).days
    except (KeyError, TypeError, ValueError):
        return {}, "benchmark_date_missing"
    if not 0 <= age < 30:
        return {}, "benchmark_reference_stale"
    return {(item["player_id"], item["profile"]): {**item, "reference_population": "profile_group"} for item in benchmark["comparisons"]}, None


def build_optimal_xi(formation, assessment, benchmark=None, *, policy=None, excluded_player_ids=()):
    """Use already scoped assessments; eligibility and objective are separate from solver."""
    policy = eligibility_policy(policy)
    slots = formation["slots"]
    canonical = json.dumps(formation, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if assessment.get("version") != 1 or assessment["formation"]["sha256"] != hashlib.sha256(canonical.encode("utf-8")).hexdigest():
        raise ValueError("XI requires assessments for this formation")
    players = sorted(assessment["players"], key=lambda p: p["player_id"])
    by_id = {p["player_id"]: p for p in players}
    if len(by_id) != len(players):
        raise ValueError("Duplicate stable player identity")
    removed = set(excluded_player_ids)
    if not removed <= by_id.keys():
        raise ValueError("Unknown hypothetical exclusion player ID")
    players = [p for p in players if p["player_id"] not in removed]
    evidence = {(p["player_id"], s["slot_id"]): s for p in players for s in p["slots"]}
    edges, excluded = {}, []
    for p in players:
        key = p["player_id"]
        rejected = {}
        eligible = {}
        for slot in slots:
            sid = slot["id"]
            item = evidence.get((key, sid))
            reasons = exclusion_reasons(p, slot, item, policy, phase_weights=formation["phase_weights"])
            if reasons:
                rejected[sid] = reasons
            else:
                eligible[sid] = item["attribute_profile_score"]
        if eligible:
            edges[key] = eligible
        excluded.append({"player_id": key, "display_name": p["display_name"], "availability": p["availability"],
                         "loan_state": p["loan_state"], "eligible_slots": list(eligible), "slot_exclusions": rejected})
    gk_slots = [s["id"] for s in slots if s["profile"] == "GK"]
    out_slots = [s["id"] for s in slots if s["profile"] != "GK"]
    def domain(ids):
        return solve_assignment(ids, {p: {s: v for s, v in scores.items() if s in ids} for p, scores in edges.items()})
    chosen = {**domain(gk_slots), **domain(out_slots)}
    selected = {p for p in chosen.values() if p is not None}
    context, context_reason = benchmark_context(benchmark, assessment)
    assignments = []
    for slot in slots:
        sid = slot["id"]
        key = chosen[sid]
        row = {"slot_id": sid, "label": slot["label"], "side": slot["side"], "profile": slot["profile"],
               "selection_position": slot.get("selection_position", slot["positions"][0]), "eligibility_position": None,
               "player_id": key, "display_name": None, "attribute_profile_score": None, "assessment": None,
               "warnings": [], "league_benchmark": None, "league_benchmark_reason": context_reason, "vacancy_reason": None}
        if key is None:
            row["vacancy_reason"] = ("eligible_players_assigned_elsewhere" if any(sid in scores for scores in edges.values())
                                     else "no_eligible_player")
        else:
            p, item = by_id[key], evidence[key, sid]
            row.update(display_name=p["display_name"], attribute_profile_score=edges[key][sid], assessment=item,
                       availability=p["availability"], loan_state=p["loan_state"])
            row["eligibility_position"] = qualifying_position(slot, item, policy)
            if row["eligibility_position"] != row["selection_position"]:
                row["warnings"].append("relaxed_alternative_position_eligibility")
            for phase in ("ip", "oop"):
                fit = item[phase]["familiarity"]
                if not confirmed(fit, policy):
                    row["warnings"].append(phase + ("_familiarity_below_threshold" if fit and fit.get("rating") is not None else "_familiarity_not_confirmed"))
                elif fit["status"] == "inferred_category":
                    row["warnings"].append(phase + "_category_only")
            if p["availability"] != "available":
                row["warnings"].append("unknown_availability_allowed_by_policy")
            comparison = context.get((key, slot["profile"]))
            if comparison is not None:
                row["league_benchmark"] = {**comparison, "competition": benchmark["competition"],
                                           "extraction_game_date": benchmark["extraction_game_date"]}
                row["league_benchmark_reason"] = comparison["reason"]
            elif context_reason is None:
                row["league_benchmark_reason"] = "no_matching_profile_comparison"
        assignments.append(row)
    for entry in excluded:
        entry["selected"] = entry["player_id"] in selected
        entry["reason"] = (None if entry["selected"] else "not_selected_by_optimum" if entry["eligible_slots"] else "no_eligible_slot")
    filled = len(selected)
    return {"version": 1, "career": assessment["career"], "game_date": assessment["game_date"],
            "formation": assessment["formation"], "scoring_model": assessment["scoring_model"], "eligibility_policy": policy,
            "objective": {"name": "uncalibrated attribute-based selection model", "score_units": assessment["attribute_profile_units"],
                          "priorities": ["maximum_filled_slots", "maximum_outfield_score_sum", "maximum_goalkeeper_score", "stable_id_tie_break"]},
            "solver": {"method": "exact_slot_bitmask_dynamic_programming", "status": "complete" if filled == len(slots) else "incomplete" if filled else "infeasible", "filled_slots": filled},
            "assignments": assignments, "outfield_total": math.fsum(r["attribute_profile_score"] for r in assignments if r["profile"] != "GK" and r["player_id"] is not None),
            "goalkeeper_total": next((r["attribute_profile_score"] for r in assignments if r["profile"] == "GK"), None),
            "excluded_or_uncertain_players": [e for e in excluded if not e["selected"] or e["availability"] != "available"],
            "limitations": ["Not a match-outcome prediction or FM role suitability rating.", "Availability reflects squad/loan status, not fitness, injuries, suspension or registration.", "Unknown familiarity is not zero; phase fit and league benchmarks are context only.", "Save-file attributes may include values hidden by in-game scouting knowledge.", "Raw weighted profiles assume comparable marginal units across outfield slots; not calibrated."]}


def render_html(report):
    """Static escaped table, no scripts or external resources."""
    def text(value):
        return escape(str(value)) if value is not None else "—"
    def fit(item):
        if not item:
            return "Unknown"
        if item["rating"] is not None:
            return str(item["rating"])
        if item["lower_bound"] is not None:
            return f'{item["category"]} ({item["lower_bound"]}–{item["upper_bound"]})'
        return "Unknown"
    rows = []
    for row in report["assignments"]:
        a = row["assessment"] or {}
        accepted = ", ".join(f"{k}: {fit(v)}" for k, v in a.get("accepted_positions", {}).items())
        phases = [f"{a[phase]['position'] or 'unspecified'}: {fit(a[phase]['familiarity'])}" if a else "—" for phase in ("ip", "oop")]
        league = (row["league_benchmark"] or {}).get("percentile")
        score = row["attribute_profile_score"]
        cells = [f'{row["label"]} ({row["selection_position"].upper()})', row["display_name"] or "VACANT", row["profile"], f"{score:.2f}" if score is not None else None,
                 accepted, *phases, f"{league:.1f}" if league is not None else None,
                 "; ".join(row["warnings"] + ([row["vacancy_reason"]] if row["vacancy_reason"] else []) + ([row["league_benchmark_reason"]] if row["league_benchmark_reason"] else []) + (row["league_benchmark"] or {}).get("warnings", []))]
        rows.append("<tr>" + "".join(f"<td>{text(c)}</td>" for c in cells) + "</tr>")
    exclusions = []
    for entry in report["excluded_or_uncertain_players"]:
        reasons = sorted({reason for reasons in entry["slot_exclusions"].values() for reason in reasons}) if not entry["eligible_slots"] else []
        exclusions.append(f'<li>{text(entry["display_name"])}: {text(entry["reason"] or "uncertain availability")} — {text(", ".join(reasons) or entry["availability"])}</li>')
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Optimal XI</title>'
            '<style>body{font:16px system-ui;margin:2rem;background:#101923;color:#e8f0f4}table{border-collapse:collapse;width:100%}th,td{padding:.65rem;border-bottom:1px solid #425362;text-align:left}th{background:#233648}a{color:#9cdefa}</style>'
            f'<h1>{text(report["formation"]["name"])} — starting XI</h1><p>{text(report["game_date"])} · {text(report["solver"]["status"])} · {report["solver"]["filled_slots"]}/11 slots</p>'
            '<p>Uncalibrated attribute-based selection model. <a href="optimal_xi.json">Full evidence and exclusions</a> · <a href="squad_depth.html">Squad depth</a> · <a href="recruitment.html">Recruitment</a></p>'
            '<table><thead><tr><th>Slot</th><th>Player</th><th>Profile</th><th>Score</th><th>Accepted familiarity</th><th>IP</th><th>OOP</th><th>League percentile</th><th>Warnings</th></tr></thead><tbody>'
            + "".join(rows) + '</tbody></table><p>Outfield total: ' + text(f'{report["outfield_total"]:.2f}')
            + ' · Goalkeeper score: ' + text(f'{report["goalkeeper_total"]:.2f}' if report["goalkeeper_total"] is not None else None)
            + '</p><h2>Excluded or uncertain players</h2><ul>' + "".join(exclusions) + '</ul><h2>Limitations</h2><ul>'
            + "".join(f'<li>{text(x)}</li>' for x in report['limitations']) + '</ul></html>\n')
