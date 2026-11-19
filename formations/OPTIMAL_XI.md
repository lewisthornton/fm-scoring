# Optimal starting XI (version 1)

The bridge publishes `optimal_xi.json` and `optimal_xi.html` alongside the existing formation, tactical assessment and league benchmark files. Open the latter HTML directly from `out/<slug>/`; it is a static, escaped positional table with the selected formation's slot order, accepted familiarity, IP/OOP evidence, league percentile, warnings, vacancies and exclusion summary. Existing dashboards are not changed.

## Eligibility policy

Default policy (version 1):

```json
{"version": 1, "minimum_familiarity": 15, "allow_category_evidence": true, "allow_unknown_availability": false}
```

Optional `--xi-policy path/to/policy.json` on the bridge overrides these settings. A partial object uses defaults; unknown fields or invalid values are rejected. Watch mode also monitors the policy file. No persistent player-data migration is required. A player must be in the active squad (overlap with target is fine), available, in the correct GK/outfield domain, have a complete weighted profile score and at least one accepted native position with an observed rating meeting the minimum or a category lower bound meeting it. Category evidence is never converted to a point rating. Target-only and unavailable players cannot be enabled by policy; unknown availability is excluded unless explicitly enabled and then flagged. Availability describes squad/loan status, not injury, suspension, fitness or registration eligibility.

IP and OOP positions are not eligibility gates. Their independent evidence and the combined positional fit are carried unchanged; low or unknown phase familiarity is flagged. Observed FM role suitability stays null. No new attributes, weighting or recruitment ranking is introduced.

## Exact objective and solver

This is an **uncalibrated attribute-based selection model**. Maximise the number of filled slots first; then maximise the sum of outfield profile scores, and independently choose the best eligible goalkeeper. Scores are the existing `fm27v2` weighted attribute means (1–20), not match probabilities, GK points or win indices. Report totals separately. Neither familiarity nor league percentile adds to the objective. Repeated CB slots remain distinct.

`solve_assignment(slot_ids, edges)` takes stable ordered slot IDs and a mapping `player_id -> {slot_id: score}` of feasible edges. It returns every slot mapped to one stable ID or null. It processes each sorted player once, retaining the best assignment for each occupied slot bitmask. For a given mask, higher total dominates; if tied, compare the vector of stable player IDs in declared slot order lexicographically, vacancy last. Finally prefer greater cardinality before score and tie-break. Because future options depend only on occupied slots and unprocessed players, discarding dominated states is exact. Binary floating point edge values are summed as exact integers on a common power-of-two denominator, avoiding rounding-driven tie-breaks. Runtime O(P × S × 2^S), memory O(S × 2^S); S=10 for outfield and S=1 for GK. No external package or player-permutation enumeration.

`build_optimal_xi(formation, assessment, benchmark=None, *, policy=None)` checks the assessment formation hash, constructs edges with eligibility reasons, calls the independent solver by domain and returns the report. This separation permits later policies, depth or signing scenarios to reuse the matching engine without changing the default objective. No such scenarios are implemented here.

## Report schema

- `version`, `career`, `game_date`, `formation` and `scoring_model`: identities/hashes copied from the scoped assessment.
- `eligibility_policy`: effective settings; `objective`: name, priorities and units; `solver`: method, filled count and `complete` (11), `incomplete` (1–10) or `infeasible` (0).
- `assignments`: one row per declared slot in order. Each has stable ID, label, side, profile, nullable player ID/name/score, availability and loan state when selected, full original slot `assessment` including accepted and phase evidence, warnings, optional league comparison and nullable vacancy reason (`no_eligible_player` or `eligible_players_assigned_elsewhere`).
- `outfield_total`: sum of selected outfield contributions, zero if none; `goalkeeper_total`: selected GK score or null.
- `excluded_or_uncertain_players`: stable ID/name, availability, loan state, eligible slot IDs, per-slot rejection reason lists, selected flag, and reason (`no_eligible_slot`, `not_selected_by_optimum`, or null for selected uncertain players). This includes scoped target-only records but no unselected world data.
- `limitations`: interpretation and observation limits.

League context is joined by stable player ID and profile only after checking career, observation game date, model hash and reference date (0–29 days old). Missing, stale or insufficient evidence leaves nullable percentile/delta and an explicit reason. No alternative league is used. A cached earlier reference within the allowed interval retains its original extraction date and warnings.

The bridge writes the XI even when legacy rendering subsequently rejects incomplete GK scoring or a target-only cohort; existing legacy error and output behaviour is preserved. An entirely absent scoped career in an existing database publishes an infeasible XI with null game date, then raises the existing no-active-data error rather than inventing observations. A valid XI is not necessarily match-day eligible or tactically optimal because the current attribute model is provisional.

## Verification

Invented unit fixtures exercise both formations, duplicate CB slots, multi-slot assignment, greedy counterexamples, category bounds, missing data, GK domain, availability/cohorts, stable IDs and benchmark context. An independent exhaustive oracle enumerates small random graphs and verifies exact cardinality, score and tie-breaking. Integration fixtures verify the separate outputs, unchanged frozen native/recruitment hashes, scoped SQLite read-only behaviour, alternate career isolation, incomplete GK, policy switches and standalone checkout module loading.
