"""Scoped, hypothetical squad vulnerability analysis using the exact XI solver."""
from fractions import Fraction
from html import escape
from itertools import combinations
import copy


def exact_objective(xi):
    """Match the solver's comparisons without floating-point sum roundoff."""
    outfield = sum((Fraction(a["attribute_profile_score"]) for a in xi["assignments"]
                    if a["player_id"] is not None and a["profile"] != "GK"), Fraction(0))
    keeper = xi["goalkeeper_total"]
    return xi["solver"]["filled_slots"], outfield, Fraction(keeper) if keeper is not None else Fraction(-1)


def tie_vector(xi):
    # Stable player IDs in declared slot order, with vacancies last.
    return tuple((a["player_id"] is None, a["player_id"] or "") for a in xi["assignments"])


def totals(xi):
    return {"filled_slots": xi["solver"]["filled_slots"], "outfield_total": xi["outfield_total"],
            "goalkeeper_total": xi["goalkeeper_total"]}


def league_context(benchmark, context, reason, key, profile):
    item = context.get((key, profile))
    if item is None:
        return {"comparison": None, "reason": reason or "no_matching_profile_comparison"}
    distribution = (benchmark.get("reference") or {}).get("profiles", {}).get(profile, {})
    return {"comparison": {**item, "competition": benchmark["competition"],
                            "extraction_game_date": benchmark["extraction_game_date"],
                            "contributing_clubs": distribution.get("contributing_clubs")}, "reason": item["reason"]}


def build_squad_depth(formation, assessment, benchmark=None, *, optimizer, policy=None, baseline=None):
    """No I/O; one baseline and one exact solve per starter, no mutation of inputs.

    The optimizer module is injected by the selected-checkout bridge. Eligible
    edge records are shared by reference to (slot_id, player_id) in scenarios.
    """
    policy = optimizer.eligibility_policy(policy)
    if baseline is None:
        baseline = optimizer.build_optimal_xi(formation, assessment, benchmark, policy=policy)
    provenance = {k: assessment[k] for k in ("career", "game_date", "formation", "scoring_model")}
    provenance["eligibility_policy"] = policy
    def validate(result):
        if any(result[k] != value for k, value in provenance.items()):
            raise ValueError("XI scenario provenance mismatch")
        if [a["slot_id"] for a in result["assignments"]] != [s["id"] for s in formation["slots"]]:
            raise ValueError("XI scenario formation slot order mismatch")
    validate(baseline)
    slots = formation["slots"]
    players = sorted(assessment["players"], key=lambda p: p["player_id"])
    initial = {a["slot_id"]: a for a in baseline["assignments"]}
    starter_slots = {a["player_id"]: a["slot_id"] for a in baseline["assignments"] if a["player_id"] is not None}
    if len(starter_slots) != baseline["solver"]["filled_slots"]:
        raise ValueError("Invalid baseline assignment")
    context, context_reason = optimizer.benchmark_context(benchmark, assessment)
    coverage, bench_slots, eligible_slots = [], {}, {}
    for slot in slots:
        sid = slot["id"]
        eligible, rejected = [], []
        for p in players:
            key = p["player_id"]
            evidence = next((s for s in p["slots"] if s["slot_id"] == sid), None)
            reasons = optimizer.exclusion_reasons(p, slot, evidence, policy)
            if reasons:
                # Keep slot-specific evidence for scoped squad players; target
                # exclusions already appear in the baseline report.
                if "squad" in p["cohorts"]:
                    rejected.append({"player_id": key, "availability": p["availability"], "reasons": reasons,
                                     "missing_evidence": evidence["missing_evidence"] if evidence else ["missing_slot_assessment"]})
                continue
            eligible_slots.setdefault(key, []).append(sid)
            if key not in starter_slots:
                bench_slots.setdefault(key, []).append(sid)
            eligible.append({"player_id": key, "display_name": p["display_name"], "availability": p["availability"],
                             "loan_state": p["loan_state"], "baseline_slot": starter_slots.get(key),
                             "attribute_profile_score": evidence["attribute_profile_score"],
                             "assessment": evidence, "league": league_context(benchmark, context, context_reason, key, slot["profile"])})
        eligible.sort(key=lambda e: (-e["attribute_profile_score"], e["player_id"]))
        bench = [e["player_id"] for e in eligible if e["player_id"] not in starter_slots]
        coverage.append({"slot_id": sid, "label": slot["label"], "profile": slot["profile"],
                         "starter_id": initial[sid]["player_id"], "eligible_players": eligible,
                         "direct_deputy_ids": bench, "direct_cover_count": len(bench), "rejected_squad_players": rejected})
    by_slot = {r["slot_id"]: r for r in coverage}
    for key, sid in starter_slots.items():
        if not any(e["player_id"] == key and e["attribute_profile_score"] == initial[sid]["attribute_profile_score"]
                   for e in by_slot[sid]["eligible_players"]):
            raise ValueError("Baseline contains an ineligible assignment")
    for row in coverage:
        row["exclusive_direct_deputy_ids"] = [p for p in row["direct_deputy_ids"] if len(bench_slots[p]) == 1]
        row["shared_direct_deputy_ids"] = [p for p in row["direct_deputy_ids"] if len(bench_slots[p]) > 1]
        row["cover_type"] = ("none" if not row["direct_deputy_ids"] else "exclusive" if not row["shared_direct_deputy_ids"]
                             else "shared_only" if not row["exclusive_direct_deputy_ids"] else "mixed")

    # Bench-only matching capacity is a diagnostic, not a substitute selection
    # objective or a multi-injury simulation. Zero weights count slots only.
    bench_edges = {p: {sid: 0 for sid in ids} for p, ids in bench_slots.items()}
    def simultaneous(ids, removed=None):
        selected = optimizer.solve_assignment(ids, {p: {s: 0 for s in ids if s in edges} for p, edges in bench_edges.items() if p != removed})
        return sum(p is not None for p in selected.values())
    overlaps = []
    for a, b in combinations(coverage, 2):
        common = sorted(set(a["direct_deputy_ids"]) & set(b["direct_deputy_ids"]))
        if common:
            ids = [a["slot_id"], b["slot_id"]]
            overlaps.append({"slot_ids": ids, "shared_player_ids": common, "simultaneously_coverable_slots": simultaneous(ids)})
    versatility = [{"player_id": key, "display_name": p["display_name"], "baseline_slot": starter_slots.get(key),
                    "eligible_slot_ids": eligible_slots[key],
                    "sole_direct_cover_slot_ids": [sid for sid in bench_slots.get(key, []) if by_slot[sid]["direct_cover_count"] == 1]}
                   for p in players for key in [p["player_id"]] if len(eligible_slots.get(key, [])) > 1]
    all_slots = [s["id"] for s in slots]
    capacity = simultaneous(all_slots)
    bench_dependencies = [{"player_id": key, "direct_cover_slot_ids": ids,
                           "newly_uncovered_slot_ids": [sid for sid in ids if by_slot[sid]["direct_cover_count"] == 1],
                           "simultaneous_capacity_without_player": simultaneous(all_slots, key)}
                          for key, ids in sorted(bench_slots.items())]
    scenarios = []
    for slot in slots:
        sid = slot["id"]
        incumbent = initial[sid]
        removed = incumbent["player_id"]
        if removed is None:
            by_slot[sid].update(effective_deputy_id=None, effective_deputy_status="baseline_vacant", maintains_completeness=None)
            continue
        result = optimizer.build_optimal_xi(formation, assessment, benchmark, policy=policy, excluded_player_ids=(removed,))
        validate(result)
        before_objective, after_objective = exact_objective(baseline), exact_objective(result)
        if after_objective > before_objective or (after_objective == before_objective and tie_vector(result) < tie_vector(baseline)):
            raise AssertionError("Removing a player improved the optimal objective")
        after = {a["slot_id"]: a for a in result["assignments"]}
        if any(a["player_id"] == removed for a in after.values()):
            raise AssertionError("Excluded starter appeared in scenario")
        changes = [{"slot_id": s["id"], "before_player_id": initial[s["id"]]["player_id"],
                    "after_player_id": after[s["id"]]["player_id"]} for s in slots
                   if initial[s["id"]]["player_id"] != after[s["id"]]["player_id"]]
        promoted = [a["player_id"] for a in result["assignments"] if a["player_id"] is not None and a["player_id"] not in starter_slots]
        moved = [{"player_id": a["player_id"], "from_slot_id": starter_slots[a["player_id"]], "to_slot_id": a["slot_id"]}
                 for a in result["assignments"] if a["player_id"] in starter_slots and starter_slots[a["player_id"]] != a["slot_id"]]
        newly_vacant = [s["id"] for s in slots if initial[s["id"]]["player_id"] is not None and after[s["id"]]["player_id"] is None]
        loss = baseline["solver"]["filled_slots"] - result["solver"]["filled_slots"]
        outfield_loss = baseline["outfield_total"] - result["outfield_total"]
        keeper_loss = (baseline["goalkeeper_total"] - result["goalkeeper_total"]
                       if baseline["goalkeeper_total"] is not None and result["goalkeeper_total"] is not None else None)
        deputy = after[sid]["player_id"]
        by_slot[sid].update(effective_deputy_id=deputy, effective_deputy_status="vacant" if deputy is None else
                            "moved_starter" if deputy in starter_slots else "promoted_bench", maintains_completeness=loss == 0)
        scenarios.append({"removed_player_id": removed, "removed_display_name": incumbent["display_name"], "original_slot_id": sid,
                          "domain": "goalkeeper" if slot["profile"] == "GK" else "outfield", "baseline": totals(baseline),
                          "reoptimised": totals(result), "filled_slot_loss": loss, "additional_vacancy": loss > 0,
                          "outfield_score_loss": outfield_loss, "goalkeeper_score_loss": keeper_loss,
                          "effective_deputy_id": deputy, "changes": changes, "changed_slot_count": len(changes),
                          "positional_change_count": len(moved),
                          "promoted_player_ids": promoted, "moved_starters": moved, "newly_vacant_slot_ids": newly_vacant,
                          "assignments": [{"slot_id": a["slot_id"], "player_id": a["player_id"],
                                           "attribute_profile_score": a["attribute_profile_score"], "warnings": a["warnings"],
                                           "vacancy_reason": a["vacancy_reason"], "league_benchmark_reason": a["league_benchmark_reason"]}
                                          for a in result["assignments"]], "monotonic_objective_verified": True})
    # Cardinality first, then same-domain score loss. Different score domains
    # deliberately grouped rather than compared or added to one another.
    order = {s["id"]: i for i, s in enumerate(slots)}
    scenarios.sort(key=lambda s: (-s["filled_slot_loss"], s["domain"] != "outfield",
                                 -(s["outfield_score_loss"] if s["domain"] == "outfield" else s["goalkeeper_score_loss"] or 0),
                                 order[s["original_slot_id"]], s["removed_player_id"]))
    report = {"version": 1, **provenance, "objective": baseline["objective"], "baseline": baseline,
              "coverage": coverage, "starter_loss_scenarios": scenarios, "shared_cover": overlaps, "versatility": versatility,
              "bench_only_matching_capacity": capacity, "bench_cover_dependencies": bench_dependencies,
              "summary": {"baseline_filled_slots": baseline["solver"]["filled_slots"],
                          "baseline_vacant_slot_ids": [s["id"] for s in slots if initial[s["id"]]["player_id"] is None],
                          "no_direct_cover_slot_ids": [r["slot_id"] for r in coverage if not r["direct_deputy_ids"]],
                          "no_effective_replacement_slot_ids": [r["slot_id"] for r in coverage if r["effective_deputy_status"] == "vacant"],
                          "cannot_maintain_completeness_slot_ids": [r["slot_id"] for r in coverage if r["maintains_completeness"] is False]},
              "limitations": ["Attribute-based vulnerability diagnostics, not match performance or injury forecasts.",
                              "Direct cover is potential individual cover; overlapping deputies cannot fill multiple slots simultaneously.",
                              "Score losses are separate by domain; a vacancy takes precedence over numerical scores. Within equal vacancy loss, outfield and goalkeeper scenarios are grouped separately.",
                              "Availability reflects squad and loan status, not match-day eligibility; missing evidence remains unknown."]}
    return copy.deepcopy(report)


def render_html(report):
    """Compact static view with expandable scenario changes."""
    def esc(value):
        return escape(str(value)) if value is not None else "—"
    def score(value):
        return f"{value:.2f}" if value is not None else "—"
    players = {e["player_id"]: e["display_name"] for row in report["coverage"] for e in row["eligible_players"]}
    slots = {r["slot_id"]: r["label"] for r in report["coverage"]}
    def name(key):
        return esc(players.get(key, key)) if key is not None else "VACANT"
    scenarios = {s["original_slot_id"]: s for s in report["starter_loss_scenarios"]}
    rows = []
    for row in report["coverage"]:
        s = scenarios.get(row["slot_id"])
        deputies = [f'{name(e["player_id"])} ({score(e["attribute_profile_score"])})' + (" — uncertain availability" if e["availability"] != "available" else "") for e in row["eligible_players"] if e["player_id"] in row["direct_deputy_ids"]]
        def league(key):
            edge = next((e for e in row["eligible_players"] if e["player_id"] == key), None)
            if edge is None:
                return "—"
            comparison = edge["league"]["comparison"] or {}
            percentile = comparison.get("percentile")
            if percentile is None:
                return esc(edge["league"]["reason"] or "Unknown")
            warning = ", ".join(comparison.get("warnings", []))
            return esc(f'{percentile:.1f}th · n={comparison.get("sample_size")} · {comparison.get("contributing_clubs")} clubs' + (f' · {warning}' if warning else ""))
        cells = [esc(row["label"]), name(row["starter_id"]), league(row["starter_id"]),
                 f'{row["direct_cover_count"]}: ' + (", ".join(deputies) or "None"), name(row["effective_deputy_id"]),
                 league(row["effective_deputy_id"]), esc(row["cover_type"]), esc(s["filled_slot_loss"] if s else None)]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    details = []
    for s in report["starter_loss_scenarios"]:
        changes = "".join(f'<li>{esc(slots[c["slot_id"]])}: {name(c["before_player_id"])} → {name(c["after_player_id"])}</li>' for c in s["changes"])
        warnings = "".join(f'<li>{esc(slots[a["slot_id"]])}: {esc(", ".join(a["warnings"]))}</li>' for a in s["assignments"] if a["warnings"])
        details.append(f'<details><summary>{name(s["removed_player_id"])} — {esc(slots[s["original_slot_id"]])}: {s["filled_slot_loss"]} filled slots lost; changed slots: {s["changed_slot_count"]}, repositioned starters: {s["positional_change_count"]}; outfield loss {score(s["outfield_score_loss"])}, GK loss {score(s["goalkeeper_score_loss"])}</summary><ul>{changes}{warnings}</ul></details>')
    shared = "".join(f'<li>{esc(" / ".join(slots[x] for x in r["slot_ids"]))}: {", ".join(name(p) for p in r["shared_player_ids"])} — simultaneous capacity {r["simultaneously_coverable_slots"]}/2</li>' for r in report["shared_cover"])
    uncertain = "".join(f'<li>{esc(e["display_name"])} — {esc(e["availability"])}: {esc(e["reason"] or "uncertain availability")}</li>'
                        for e in report["baseline"]["excluded_or_uncertain_players"] if not e["eligible_slots"] or e["availability"] != "available")
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Squad depth</title>'
            '<style>body{font:16px system-ui;margin:2rem;background:#101923;color:#e8f0f4}table{border-collapse:collapse;width:100%}th,td{padding:.65rem;border-bottom:1px solid #425362;text-align:left}th{background:#233648}a{color:#9cdefa}details{padding:.5rem}</style>'
            f'<h1>{esc(report["formation"]["name"])} — squad depth</h1><p>{esc(report["game_date"])} · baseline {report["summary"]["baseline_filled_slots"]}/11</p>'
            '<p><a href="optimal_xi.html">Optimal XI</a> · <a href="squad_depth.json">Full evidence and exclusions</a></p>'
            '<table><thead><tr><th>Slot</th><th>Starter</th><th>Starter league percentile</th><th>Direct bench cover</th><th>Effective deputy</th><th>Deputy league percentile</th><th>Cover type</th><th>Slots lost</th></tr></thead><tbody>'
            + "".join(rows) + '</tbody></table><h2>Starter-loss vulnerabilities</h2>' + "".join(details)
            + '<h2>Shared cover</h2><ul>' + shared + '</ul><p>Bench-only simultaneous capacity: ' + str(report["bench_only_matching_capacity"])
            + '/11 slots.</p><h2>Excluded or uncertain players</h2><ul>' + uncertain + '</ul><h2>Limitations</h2><ul>'
            + "".join(f'<li>{esc(note)}</li>' for note in report["limitations"]) + '</ul></html>\n')
