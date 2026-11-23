# R5B — Experimental squad depth and recruitment

This is a pure invented-fixture extension of [R5A](EXPERIMENTAL_XI_R5A.md).
The operational XI, squad depth, signing reports, R3 arithmetic, build
registry, watcher, launcher, dashboard, database and benchmarks are unchanged.
No actual FM27 save is an input to this experiment.

## Public interface

Construct an invented R5A matrix using `experimental_xi.build_matrix`.
Include any candidate observations in that same matrix with cohort `target`
and without cohort `squad`. Candidates are assessed by R5A but initially
ineligible for selection. The only accepted hypothetical signing policy
is `add_target_preserve_availability`: explicitly add one target to the
squad membership in a detached scenario; remove only the membership
exclusion. Existing availability, positional eligibility, exact phase role
scores, build and input evidence stay as observed. Unknown/unavailable
players remain governed by the existing eligibility policy. No assumption
about transfer feasibility or actual match fitness is made.

```python
from experimental_scenarios import build_report, compare_objectives, SIGNING_POLICY

result = build_report(matrix, objective="role_rating",
                      candidate_ids=["invented:example:target-1"],
                      signing_policy=SIGNING_POLICY)
comparison = compare_objectives(matrix,
                                candidate_ids=["invented:example:target-1"],
                                signing_policy=SIGNING_POLICY)
```

With no candidates, signing policy is optional. Each unique candidate is
evaluated independently against the same baseline, never cumulatively.
An unknown candidate, already-squad player, duplicate candidate or
missing/unknown signing policy is rejected. No external file input or
production report publisher exists. The R5A invented namespace and source
guards are checked, together with pinned model/catalogue and tactic hashes,
matrix integrity and strict numerical build restrictions. These checks
detect inconsistencies, not authenticity or adversarial forgery. Do not
relabel real observations as invented.

## Mathematical contract

The scores and eligible edges originate entirely from R5A. For a chosen
objective, the exact solver maximizes cardinality, then the sum of assigned
outfield values and the goalkeeper value independently, then stable
player IDs in declared slot order. No alternative scoring or assignment
algorithm is introduced. GK and outfield totals remain separate.

Removing a player deletes their rows in a detached matrix; signing
changes only target membership and the corresponding exclusion. All
scenario hashes are recomputed, baseline rows remain unchanged, and each
scenario solves the entire XI again. No phase reweighting is performed.
Objective improvements are compared using exact binary-rational values
of existing scores, matching the solver. Each event retains both XI
totals and assignment sets. Signed score changes (after minus before)
are emitted only at equal cardinality; absence losses have the opposite
sign. A missing GK value does not become zero. Newly vacant/filled slots
and cardinality change are reported independently. A lower raw total
after losing a slot is not a calibrated loss estimate.

### Depth and resilience

- Per-slot alternatives are ordered by individual suitability and ID,
  excluding the selected incumbent; alternatives may be starters elsewhere.
- Direct deputies are eligible nonstarters. One versatile deputy listed
  at several slots is still one player; the existing matching solver
  computes distinct bench-only coverage capacity per domain, not a
  sum of per-slot alternatives.
- Player coverage and deputy-removal capacity diagnose shared cover
  and single-player dependency. A zero capacity means no eligible
  matching, never a fabricated zero score.
- Each baseline starter is removed once. Report the original slot,
  actual replacement there (possibly null), all moved or promoted
  players, changed slots, weaker occupied slots, displaced players,
  newly vacant slots and objective loss only at unchanged cardinality.
- Each signing reports both post-signing coverage and a whole-XI solve.
  For resilience, remove each *same original starter* from the signed
  roster (even if displaced in the new XI), and compare against the
  corresponding original absence. This isolates the candidate's
  counterfactual contribution. No assumption that the direct deputy is
  the optimal replacement.
- Depth improvement means more direct-deputy options at some slot,
  greater domain bench matching capacity or improved same-starter
  absence objective. Slot lists distinguish direct-cover improvement
  from absence resilience. Candidate tie-break-only selections are not
  numerical objective improvements. Coverage is a diagnostic, not a
  guarantee against simultaneous injuries, nor an indication that
  every slot improved.

The report has version 1, experimental flag, objective ID and units,
baseline matrix SHA-256, tactic/catalogue/model/legacy hashes, policy,
per-player build evidence, baseline, depth, absence and recruitment
records, rejected/unavailable edge reasons and limitations. Each scenario
contains the new matrix hash via its reoptimised XI; the baseline hash is
retained separately. The comparison returns all three reports and a
candidate decision table, without computing cross-objective numeric deltas.

## Reproducible invented examples

Run `python -m unittest discover -s tests -p test_experimental_scenarios.py -v`.
The fixtures reuse the R5A asymmetric manual tactic and reference-label
input contract. Raw/display inputs are invented independently and are
not intended to resemble a real player record.

| Scenario | Observed result | Explanation |
| --- | --- | --- |
| Direct striker upgrade | Legacy score 15 to 19, incumbent displaced | Same eligible slot and cardinality, +4 within-model score |
| Eligible backup | Score 14 cannot displace score 15; becomes direct deputy | Adds resilience but not starting objective |
| High-scoring unavailable/wrong-type target | No selection or depth gain | Numeric suitability is not eligibility |
| Left-back removed | Four slot assignments change, three surviving starters move, reserve CB promoted; loss 3 | RB moves left, CB moves right, reserve fills CB; beats low-score direct replacement |
| Versatile CB/DM signing | Four changed slots, three moved starters, +7 outfield score | Strong incumbent pivots remain; incoming CB frees existing CB and RB to move |
| Sole striker absent | One additional vacancy, score loss unavailable | Cardinality has precedence over sum |
| Shared utility deputy | Two covered slots, capacity one; removal reduces capacity to zero | One player cannot cover both simultaneously |
| GK signing | GK 10 to 18, outfield unchanged | Separate keeper domain |
| Missing CA | Rating may remain available, ability does not | No substitution between objectives |
| Unsupported 27.1 build | Both role objective edges unavailable | R3 gate unchanged |

### Recruitment recommendation reversal

The same original striker and three independent candidates:

| Objective | Baseline total (outfield) | Starting-upgrade candidate | New total | Other candidates |
| --- | ---: | --- | ---: | --- |
| fm27v2 | 15 | legacy | 19 | cover only |
| role_rating | 130 | rating | 170 | cover only |
| role_ability | 140 | ability | 180 | cover only |

All have the same native eligibility; the candidate whose absolute role
rating is 170 can lose to the candidate whose absolute rating is 110 but
whose CA-scaled ability is 180. Each number is compared only against
the baseline for its own objective. There is no empirical basis here for
preferring any one of the three.

The asymmetric RB experiment holds both candidates DR-qualified and
below the DC eligibility threshold. With IP-only weights the incumbent's
better familiarity at the IP centre-back role wins; with OOP-only weights
the target's better right-back rating produces a starting upgrade.
No phase weighting is claimed to be match-calibrated.

Independent exhaustive assignment enumeration tests the baseline,
each removal, signing and signing-plus-removal across all three objectives
on a small multi-position fixture. Tests also cover deterministic order,
matrix nonmutation, incomplete scores, unavailable players, GK domain,
explicit policy and scope, and frozen operational XI/depth/signing JSON
hashes (nine decimal places only to account for Python summation rounding,
same convention as existing parity tests).

## R6 readiness and remaining blockers

The experimental reports now provide whole-XI, depth and recruitment
decision contracts suitable for a future read-only prototype against
invented data. Do not integrate them into the operational dashboard yet.
R6 design should preserve separate selected-objective provenance,
vacancies, per-player eligibility/missing reasons, and explicit
experimental labels; avoid duplicating scores in UI view models.
Controlled real-save model activation still requires all R4.5 blockers
to be resolved: exact full executable and verified numeric save DB
identity, independent applicable build-specific numerical evidence,
scope of role catalogue and tactic decoding, exact raw inputs and
deliberate approval of model/eligibility policy. The abstract 27.0.0
reference key is not real-build support. Cross-slot scoring comparability,
phase weights and choice of role rating versus ability remain experimental.
No match, points, goal, transfer price, affordability, registration
or fitness prediction is produced.
