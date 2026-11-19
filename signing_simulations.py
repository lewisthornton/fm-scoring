"""Read-only, single-candidate counterfactuals over existing scoped assessments."""
import copy
from fractions import Fraction
from html import escape
import hashlib
import json


DEFAULT_DEPTH_LIMIT = 12
ASSUMPTIONS = ["Exactly one target is added to a local hypothetical squad; no actual transfer occurs.",
               "Squad membership and selection availability are assumed only for that candidate in the scenario.",
               "Observed club, loan, attributes and familiarity are unchanged; interest, price, registration and fitness are unknown."]


def validate_players(assessment):
    players = {}
    namespace = set()
    uids, unique_ids = set(), set()
    for p in assessment["players"]:
        key = p["player_id"]
        if not isinstance(key, str) or not key.strip() or key in players:
            raise ValueError("Duplicate or malformed signing player identity")
        # Production bridge identities are JSON arrays; pure clients may use
        # opaque nonempty IDs scoped to the supplied assessment.
        if key.lstrip().startswith("["):
            try:
                parts = json.loads(key)
            except ValueError as exc:
                raise ValueError("Malformed scoped signing identity") from exc
            if (not isinstance(parts, list) or len(parts) != 3 or parts[:2] != ["rangers", assessment["career"]]
                    or not isinstance(parts[2], str) or not parts[2].strip()):
                raise ValueError("Conflicting scoped signing identity")
            canonical = tuple(parts)
            if canonical in namespace:
                raise ValueError("Duplicate scoped signing identity")
            namespace.add(canonical)
            fields = parts[2].split("|")
            if len(fields) != 3 or not fields[0].strip():
                raise ValueError("Malformed watcher player key")
            uid, unique, _ = fields
            if uid in uids or (unique and unique in unique_ids):
                raise ValueError("Conflicting watcher player identities")
            uids.add(uid)
            if unique:
                unique_ids.add(unique)
        if len({s["slot_id"] for s in p["slots"]}) != len(p["slots"]) or any(s["player_id"] != key for s in p["slots"]):
            raise ValueError("Conflicting signing slot identity")
        players[key] = p
    return players


def hypothetical_assessment(assessment, candidate_id):
    """Detached roster with exactly one target added; preserve observation metadata."""
    players = validate_players(assessment)
    p = players.get(candidate_id)
    if p is None or "target" not in p["cohorts"] or "squad" in p["cohorts"]:
        raise ValueError("Signing requires an active target outside the squad")
    candidate = copy.deepcopy(p)
    candidate["cohorts"] = sorted(set(candidate["cohorts"]) | {"squad"})
    candidate["availability"] = "available"
    for slot in candidate["slots"]:
        slot["availability"] = "available"
    return {**copy.deepcopy({k: v for k, v in assessment.items() if k != "players"}),
            "players": sorted([copy.deepcopy(q) for q in players.values() if "squad" in q["cohorts"]] + [candidate], key=lambda q: q["player_id"])}


def totals(result):
    return {"filled_slots": result["solver"]["filled_slots"], "outfield_total": result["outfield_total"], "goalkeeper_total": result["goalkeeper_total"]}


def objective(rows, slots):
    scores = [(slots[r["slot_id"]], Fraction(r["attribute_profile_score"])) for r in rows if r["player_id"] is not None]
    return len(scores), sum((v for p, v in scores if p != "GK"), Fraction(0)), next((v for p, v in scores if p == "GK"), Fraction(-1))


def comparison(before, after, slots):
    first = {r["slot_id"]: r for r in before}
    second = {r["slot_id"]: r for r in after}
    old = {r["player_id"]: r["slot_id"] for r in before if r["player_id"] is not None}
    new = {r["player_id"]: r["slot_id"] for r in after if r["player_id"] is not None}
    a, b = objective(before, slots), objective(after, slots)
    tie = lambda rows: tuple((r["player_id"] is None, r["player_id"] or "") for r in rows)
    if b < a or (b == a and tie(after) > tie(before)):
        raise AssertionError("Adding a player worsened the optimal objective")
    changes = [{"slot_id": sid, "before_player_id": first[sid]["player_id"], "after_player_id": second[sid]["player_id"]} for sid in slots if first[sid]["player_id"] != second[sid]["player_id"]]
    moved = [{"player_id": key, "from_slot_id": old[key], "to_slot_id": sid} for key, sid in new.items() if key in old and old[key] != sid]
    return {"filled_slot_gain": b[0] - a[0], "outfield_score_gain": float(b[1] - a[1]),
            "goalkeeper_score_gain": float(b[2] - a[2]) if a[2] >= 0 and b[2] >= 0 else None,
            "objective_improved": b > a, "tie_break_only": b == a and bool(changes),
            "changes": changes, "changed_slot_count": len(changes), "moved_starters": moved, "positional_change_count": len(moved),
            "newly_benched_player_ids": [key for key in old if key not in new],
            "newly_filled_slot_ids": [sid for sid in slots if first[sid]["player_id"] is None and second[sid]["player_id"] is not None],
            "vacant_slot_ids": [sid for sid in slots if second[sid]["player_id"] is None], "monotonic_objective_verified": True}


def compact(rows):
    return [{k: r[k] for k in ("slot_id", "player_id", "attribute_profile_score", "warnings", "vacancy_reason", "league_benchmark_reason")} for r in rows]


def depth_effects(before, after, original_absences, slots, formation, roster, benchmark, optimizer, policy):
    old = {r["slot_id"]: r for r in before["coverage"]}
    new = {r["slot_id"]: r for r in after["coverage"]}
    cover = []
    for sid in slots:
        a, b = old[sid], new[sid]
        cover.append({"slot_id": sid, "before_direct_ids": a["direct_deputy_ids"], "after_direct_ids": b["direct_deputy_ids"],
                      "new_direct_ids": [p for p in b["direct_deputy_ids"] if p not in a["direct_deputy_ids"]],
                      "direct_count_gain": b["direct_cover_count"] - a["direct_cover_count"],
                      "before_cover_type": a["cover_type"], "after_cover_type": b["cover_type"],
                      "newly_covered": not a["direct_deputy_ids"] and bool(b["direct_deputy_ids"]),
                      "new_independent_cover": a["cover_type"] == "shared_only" and bool(b["exclusive_direct_deputy_ids"])})
    old_pairs = {tuple(r["slot_ids"]): r["simultaneously_coverable_slots"] for r in before["shared_cover"]}
    new_pairs = {tuple(r["slot_ids"]): r["simultaneously_coverable_slots"] for r in after["shared_cover"]}
    pair_changes = []
    for pair in sorted(old_pairs.keys() | new_pairs.keys()):
        a = old_pairs.get(pair, sum(bool(old[s]["direct_deputy_ids"]) for s in pair))
        b = new_pairs.get(pair, sum(bool(new[s]["direct_deputy_ids"]) for s in pair))
        pair_changes.append({"slot_ids": list(pair), "before_capacity": a, "after_capacity": b})
    old_sole = {(r["player_id"], sid) for r in before["bench_cover_dependencies"] for sid in r["newly_uncovered_slot_ids"]}
    new_sole = {(r["player_id"], sid) for r in after["bench_cover_dependencies"] for sid in r["newly_uncovered_slot_ids"]}
    relieved = [{"player_id": p, "slot_id": sid} for p, sid in sorted(old_sole - new_sole) if new[sid]["direct_cover_count"] > 1]
    old_dependencies = {r["player_id"]: r for r in before["bench_cover_dependencies"]}
    new_dependencies = {r["player_id"]: r for r in after["bench_cover_dependencies"]}
    dependency_changes = [{"player_id": key,
                           "capacity_loss_before": before["bench_only_matching_capacity"] - old_dependencies[key]["simultaneous_capacity_without_player"],
                           "capacity_loss_after": after["bench_only_matching_capacity"] - new_dependencies[key]["simultaneous_capacity_without_player"]}
                          for key in sorted(old_dependencies.keys() & new_dependencies.keys())]
    after_absences = {r["removed_player_id"]: r for r in after["starter_loss_scenarios"]}
    absences = []
    for event in original_absences:
        key = event["removed_player_id"]
        other = after_absences.get(key)
        if other is None:
            xi = optimizer.build_optimal_xi(formation, roster, benchmark, policy=policy, excluded_player_ids=(key,))
            rows, outcome = compact(xi["assignments"]), totals(xi)
        else:
            rows, outcome = other["assignments"], other["reoptimised"]
        impact = comparison(event["assignments"], rows, slots)
        absences.append({"removed_player_id": key, "baseline_without_player": event["reoptimised"],
                         "signing_without_player": outcome, "impact": impact, "assignments": rows})
    capacity_gain = after["bench_only_matching_capacity"] - before["bench_only_matching_capacity"]
    improved = (capacity_gain > 0 or any(r["direct_count_gain"] > 0 or r["new_independent_cover"] for r in cover)
                or bool(relieved) or any(r["after_capacity"] > r["before_capacity"] for r in pair_changes)
                or any(r["capacity_loss_after"] < r["capacity_loss_before"] for r in dependency_changes)
                or any(r["impact"]["objective_improved"] for r in absences))
    return {"status": "evaluated", "improved": improved, "coverage_changes": cover, "shared_pair_capacity": pair_changes,
            "bench_capacity_before": before["bench_only_matching_capacity"], "bench_capacity_after": after["bench_only_matching_capacity"],
            "bench_capacity_gain": capacity_gain, "relieved_sole_cover_dependencies": relieved, "common_bench_dependency_changes": dependency_changes,
            "same_original_starter_absences": absences,
            "new_xi_starter_loss_scenarios": after["starter_loss_scenarios"]}


def build_signing_simulations(formation, assessment, benchmark=None, *, optimizer, depth_module, policy=None,
                              baseline=None, baseline_depth=None, depth_limit=DEFAULT_DEPTH_LIMIT, observations=None):
    if type(depth_limit) is not int or depth_limit < 0:
        raise ValueError("Signing depth limit must be a nonnegative integer")
    players = validate_players(assessment)
    policy = optimizer.eligibility_policy(policy)
    baseline = baseline if baseline is not None else optimizer.build_optimal_xi(formation, assessment, benchmark, policy=policy)
    baseline_depth = baseline_depth if baseline_depth is not None else depth_module.build_squad_depth(formation, assessment, benchmark, optimizer=optimizer, policy=policy, baseline=baseline)
    provenance = {k: assessment[k] for k in ("career", "game_date", "formation", "scoring_model")}
    provenance["eligibility_policy"] = policy
    if any(baseline.get(k) != v or baseline_depth.get(k) != v for k, v in provenance.items()) or baseline_depth["baseline"] != baseline:
        raise ValueError("Signing baseline provenance mismatch")
    slots = {s["id"]: s["profile"] for s in formation["slots"]}
    canonical = json.dumps(formation, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if assessment.get("version") != 1 or assessment["formation"]["sha256"] != hashlib.sha256(canonical.encode("utf-8")).hexdigest():
        raise ValueError("Signing assessment formation mismatch")
    if list(slots) != [r["slot_id"] for r in baseline["assignments"]]:
        raise ValueError("Signing baseline slot order mismatch")
    context, context_reason = optimizer.benchmark_context(benchmark, assessment)
    candidates, pending = [], []
    for key, p in sorted(players.items()):
        if "target" not in p["cohorts"]:
            continue
        entry = {"player_id": key, "display_name": p["display_name"], "observed_club": p["club"],
                 "observed_availability": p["availability"], "observed_loan_state": p["loan_state"],
                 "observed_cohorts": p["cohorts"], "record_game_date": p["record_game_date"], "last_seen_game_date": p["last_seen_game_date"],
                 "game_build": p["game_build"], "observations": (observations or {}).get(key),
                 "observed_slot_evidence": p["slots"], "scenario_assumed_availability": None,
                 "classification": "already_in_squad" if "squad" in p["cohorts"] else None,
                 "xi": None, "depth": {"status": "not_applicable"}, "eligible_slot_ids": [], "rejected_slots": []}
        candidates.append(entry)
        if entry["classification"]:
            continue
        roster = hypothetical_assessment(assessment, key)
        hyp = next(q for q in roster["players"] if q["player_id"] == key)
        entry["scenario_assumed_availability"] = "available"
        for slot in formation["slots"]:
            evidence = next((s for s in hyp["slots"] if s["slot_id"] == slot["id"]), None)
            reasons = optimizer.exclusion_reasons(hyp, slot, evidence, policy)
            if reasons:
                entry["rejected_slots"].append({"slot_id": slot["id"], "reasons": reasons})
            else:
                entry["eligible_slot_ids"].append(slot["id"])
        entry["league_context"] = {profile: depth_module.league_context(benchmark, context, context_reason, key, profile) for profile in dict.fromkeys(slots.values())}
        xi = optimizer.build_optimal_xi(formation, roster, benchmark, policy=policy)
        if any(xi[k] != v for k, v in provenance.items()):
            raise ValueError("Signing scenario provenance mismatch")
        impact = comparison(baseline["assignments"], xi["assignments"], slots)
        chosen = next((a for a in xi["assignments"] if a["player_id"] == key), None)
        entry["xi"] = {"baseline": totals(baseline), "hypothetical": totals(xi), "impact": impact,
                       "enters_xi": chosen is not None, "selected_slot_id": chosen["slot_id"] if chosen else None,
                       "previous_slot_incumbent_id": next(a["player_id"] for a in baseline["assignments"] if a["slot_id"] == chosen["slot_id"]) if chosen else None,
                       "assignments": compact(xi["assignments"])}
        if impact["objective_improved"] and not chosen:
            raise AssertionError("Unselected signing improved XI objective")
        if impact["filled_slot_gain"]:
            entry["classification"] = "completeness_upgrade"
        elif impact["objective_improved"]:
            entry["classification"] = "starting_upgrade"
        elif not entry["eligible_slot_ids"]:
            relevant = [s for s in p["slots"] if (s["profile"] == "GK") == p["keeper"]]
            unknown = not relevant or any(s["attribute_profile_score"] is None or any(e["status"] == "missing" for e in s["accepted_positions"].values()) for s in relevant)
            entry["classification"] = "insufficient_evidence" if unknown else "no_demonstrated_improvement"
            entry["depth"] = {"status": "not_applicable_no_eligible_slot"}
        else:
            entry["classification"] = "depth_not_evaluated"
        if entry["eligible_slot_ids"]:
            entry["depth"] = {"status": "not_evaluated_limit"}
            pending.append(entry)
    def rank(entry):
        impact = entry["xi"]["impact"] if entry["xi"] else {}
        group = {"completeness_upgrade": 0, "starting_upgrade": 1, "depth_improvement": 2, "depth_not_evaluated": 3,
                 "no_demonstrated_improvement": 4, "insufficient_evidence": 5, "already_in_squad": 6}[entry["classification"]]
        keeper = players[entry["player_id"]]["keeper"]
        gain = impact.get("goalkeeper_score_gain") if keeper else impact.get("outfield_score_gain")
        d = entry["depth"]
        return (group, -impact.get("filled_slot_gain", 0), keeper if group in (0, 1) else False,
                -(gain or 0) if group in (0, 1) else 0,
                -sum(a["impact"]["filled_slot_gain"] > 0 for a in d.get("same_original_starter_absences", [])),
                -d.get("bench_capacity_gain", 0), -sum(r["newly_covered"] for r in d.get("coverage_changes", [])), entry["player_id"])
    for entry in sorted(pending, key=rank)[:depth_limit]:
        roster = hypothetical_assessment(assessment, entry["player_id"])
        xi = optimizer.build_optimal_xi(formation, roster, benchmark, policy=policy)
        after = depth_module.build_squad_depth(formation, roster, benchmark, optimizer=optimizer, policy=policy, baseline=xi)
        entry["depth"] = depth_effects(baseline_depth, after, baseline_depth["starter_loss_scenarios"], slots, formation, roster, benchmark, optimizer, policy)
        if entry["classification"] == "depth_not_evaluated":
            entry["classification"] = "depth_improvement" if entry["depth"]["improved"] else "no_demonstrated_improvement"
    candidates.sort(key=rank)
    return copy.deepcopy({"version": 1, **provenance, "objective": baseline["objective"], "baseline": {"xi_file": "optimal_xi.json", "depth_file": "squad_depth.json", "totals": totals(baseline)},
                          "assumptions": ASSUMPTIONS, "depth_limit": depth_limit, "depth_evaluated_count": sum(e["depth"]["status"] == "evaluated" for e in candidates),
                          "ranking_rationale": "Completeness before starting upgrades; outfield and goalkeeper grouped separately; depth-only gains ordered by rescued absence count, bench capacity, newly covered slots, then stable ID. Unevaluated depth is explicit.",
                          "player_directory": {key: p["display_name"] for key, p in sorted(players.items())},
                          "candidates": candidates, "limitations": ["Uncalibrated attribute-based selection; no predicted match wins or role suitability.", "No transfer feasibility, fees, registration or affordability assumptions beyond hypothetical selection availability.", "Depth shortlist is bounded; no conclusion about unanalysed depth."]})


def render_html(report):
    def esc(v):
        return escape(str(v)) if v is not None else "—"
    def score(v):
        return f"{v:+.2f}" if v is not None else "—"
    def name(key):
        return esc(report["player_directory"].get(key, key)) if key is not None else "VACANT"
    rows = []
    for e in report["candidates"]:
        xi = e["xi"] or {}
        impact = xi.get("impact", {})
        d = e["depth"]
        selected = xi.get("selected_slot_id")
        league = next((s["profile"] for s in e["observed_slot_evidence"] if s["slot_id"] == selected), None)
        if league is None:
            league = next((s["profile"] for s in e["observed_slot_evidence"] if s["slot_id"] in e["eligible_slot_ids"]), None)
        context = (e.get("league_context", {}).get(league) or {}).get("comparison") or {}
        details = [f'Slot {esc(c["slot_id"])}: {name(c["before_player_id"])} → {name(c["after_player_id"])}' for c in impact.get("changes", [])]
        if impact.get("tie_break_only"):
            details.append("Equal objective; assignment changed by stable-ID tie-break only.")
        details += [f'{esc(r["slot_id"])}: {esc(", ".join(r["reasons"]))}' for r in e["rejected_slots"]]
        details += [f'{esc(r["slot_id"])}: {esc(", ".join(r["warnings"]))}' for r in xi.get("assignments", []) if r["warnings"]]
        details += [f'Depth {esc(r["slot_id"])}: direct count change {r["direct_count_gain"]:+d}' for r in d.get("coverage_changes", []) if r["direct_count_gain"]]
        details += [f'Without {name(r["removed_player_id"])}: +{r["impact"]["filled_slot_gain"]} filled slots, outfield {score(r["impact"]["outfield_score_gain"])}, GK {score(r["impact"]["goalkeeper_score_gain"])}' for r in d.get("same_original_starter_absences", []) if r["impact"]["objective_improved"]]
        outcome = xi.get("hypothetical", {})
        cells = [esc(e["display_name"]), esc(e["observed_club"]), esc(e["classification"]), esc(selected), esc(impact.get("filled_slot_gain")), score(impact.get("outfield_score_gain")), score(impact.get("goalkeeper_score_gain")),
                 esc(f'{outcome["filled_slots"]}/11; outfield {outcome["outfield_total"]:.2f}, GK {outcome["goalkeeper_total"]}' if outcome else None), esc(d["status"]), esc(d.get("bench_capacity_gain")), esc(f'{league}: {context["percentile"]:.1f}' if context.get("percentile") is not None else None),
                 '<details><summary>Evidence and changes</summary><ul>' + ''.join(f'<li>{v}</li>' for v in details) + '</ul></details>']
        rows.append('<tr>' + ''.join(f'<td>{v}</td>' for v in cells) + '</tr>')
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Signing simulations</title><style>body{font:16px system-ui;margin:2rem;background:#101923;color:#e8f0f4}table{border-collapse:collapse;width:100%}td,th{padding:.6rem;border-bottom:1px solid #425362;text-align:left}a{color:#9cdefa}</style>'
            '<h1>Single-signing simulations</h1><p><a href="optimal_xi.html">Optimal XI</a> · <a href="squad_depth.html">Squad depth</a> · <a href="recruitment.html">Recruitment</a> · <a href="signing_simulations.json">Full data</a></p>'
            f'<p>Baseline: {report["baseline"]["totals"]["filled_slots"]}/11 filled · outfield {report["baseline"]["totals"]["outfield_total"]:.2f} · GK {esc(report["baseline"]["totals"]["goalkeeper_total"])} · detailed depth evaluated: {report["depth_evaluated_count"]} (limit {report["depth_limit"]})</p>'
            '<table><thead><tr><th>Target</th><th>Club</th><th>Classification</th><th>XI slot</th><th>Slots gained</th><th>Outfield gain</th><th>GK gain</th><th>Resulting XI</th><th>Depth status</th><th>Bench capacity gain</th><th>League percentile</th><th>Details</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table><ul>' + ''.join(f'<li>{esc(v)}</li>' for v in report["assumptions"] + report["limitations"]) + '</ul></html>\n')
