# R5A — Experimental tactic-driven XI optimisation

This is an offline experiment, not a Rangers integration. Read alongside
[R3](ROLE_ABILITY_R3.md), [R4](ROLE_ABILITY_R4.md) and
[R4.5](ROLE_ABILITY_BUILD_VALIDATION.md). No watcher, dashboard, database,
production report or existing solver is changed.

## Contracts

`experimental_xi.build_matrix(config, catalogue, legacy_model, players,
career=..., policy=...)` accepts a raw, manual v2 tactic, the pinned R3
catalogue, the pinned parsed fm27v2 model and invented observations only.
It validates roles/geometry using R2 and computes both phase assessments
using R3. The input career must begin with `invented:`; player IDs must
begin with that exact career and a colon, and each player must declare
`source={"kind":"invented_fixture"}`. This is a scope guard, not a means
to authenticate data; do not relabel real observations. There is no file,
SQLite, save-parser, launcher or dashboard entry point. The abstract
27.0.0/3754 R3 key is only a reference model test domain, never an alias
for a real build. Full build strings remain unsupported.

Each observation has R3 fields (raw attributes, positions, CA, build
and DB), plus display-scale `attrs`, explicit `keeper`, `cohorts` and
`availability`. Exact position inputs also drive the established
eligibility helper; optional natural/accomplished category text can
establish eligibility but never supplies exact numeric role inputs.
Raw and display-scale observations remain independent; neither is imputed
from the other.

The matrix is deterministic, versioned, career-scoped and rectangular
(all players x all 11 stable slots, including ineligible pairs for audit).
Each row includes eligibility reasons and qualifying native position,
accepted position evidence, phase familiarity, role IDs and R3 phase
diagnostics, three separate scores and missing reasons, build/model gate,
evidence provenance and hashes. Its canonical content digest detects
accidental alteration, not adversarial forgery. The legacy model hash is
of normalized TOML data, not the file-byte hash in operational reports.

`optimise(matrix, objective=...)` requires one explicit objective.
`compare(matrix)` runs all three, returning separate totals, vacancies
and slot changes relative to legacy. Neither has a fallback path.

## Objective and eligibility semantics

| Objective ID | Slot objective | Units |
| --- | --- | --- |
| fm27v2 | Existing weighted positional attribute mean | 1–20 |
| role_rating | Weighted arithmetic mean of absolute IP/OOP role ratings | Reference rating, 0–200 |
| role_ability | Existing R3 weighted arithmetic mean of CA-scaled IP/OOP ability | Reference ability, 0–200 |

For each role objective the provisional phase aggregation is
`sum(w_phase * score_phase) / sum(w_phase)`. A missing positively
weighted phase makes that metric unavailable; weight zero ignores its
absence. This uses R3's exact aggregation helper for both metrics.
Absolute rating retains R3 position adjustments; ability adds the
reference best-role and CA-dependent scaling. Neither is multiplied by
another familiarity penalty. No cross-objective normalization.

Use the existing XI eligibility policy and exclusions (squad membership,
availability, keeper type, confirmed native familiarity, optional weighted
phase familiarity, and strict/relaxed position alternatives). The legacy
attribute-profile completeness check belongs only to the legacy objective;
a role-score edge does not require unrelated display attributes. A missing
legacy profile in a tactic is therefore a legacy vacancy, not a role gate.
Role availability alone does not establish eligibility. Native selection
position and phase roles are separate; contextual phase unfamiliarity is
retained as evidence under the default policy.

For each objective, use the existing exact slot-bitmask DP unchanged,
independently for GK and outfield. Priorities: maximize filled slots,
maximize assigned outfield sum, separately maximize keeper score, then
stable player ID tie-break in declared slot order. One player can fill at
most one slot; keeper classification prevents intersection of domains.
Vacancies are explicit. Totals are within-objective only: zero outfield
total means no assigned outfield contribution, not a zero score imputation.

## Reproducible comparison

Run `python -m unittest discover -s tests -p test_experimental_xi.py -v`.
The fixture function `comparison_fixture()` creates three invented
strikers and one keeper; the display and raw inputs deliberately differ
to isolate the three scoring mechanisms, not to simulate a real FM record.
Using the asymmetric manual tactic and IP/OOP weights 0.65/0.35:

| Invented striker | fm27v2 | IP rating | OOP rating | Combined rating | IP ability | OOP ability | Combined ability |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| legacy | 19 | 90 | 90 | 90 | 110 | 108 | 109.3 |
| rating | 14 | 170 | 170 | 170 | 120 | 120 | 120 |
| ability | 12 | 110 | 110 | 110 | 180 | 180 | 180 |

| Objective | ST selected | GK selected | Outfield total | GK total | Filled |
| --- | --- | --- | ---: | ---: | ---: |
| fm27v2 | legacy | keeper | 19 | 12 | 2/11 |
| role_rating | rating | keeper | 170 | 100 | 2/11 |
| role_ability | ability | keeper | 180 | 150 | 2/11 |

The remaining nine slots are vacant. Both role objectives replace the
legacy striker, but the keeper stays fixed. The rating striker's larger
absolute score does not beat the ability striker's greater CA-scaled score.
This illustrates why CA scaling need not preserve absolute rankings.
It is not evidence of superior tactical results.

An additional right-back fixture has two DR-qualified candidates;
one has DC familiarity 14 and the other 1, neither qualifies for CB
under the default threshold. IP-only prefers the former (inverted
centre-back responsibility); OOP-only prefers the latter (right-back),
holding filled cardinality constant. Other tests cover full XI,
unresolved phase, zero weights, missing CA, raw/display completeness,
unavailable or target-only players, unsupported build, identity and
matrix determinism, legacy parity, and independent exhaustive enumeration
of the multi-eligible small assignment case.

## R5B readiness and blockers

The matrix and objective contracts can be reused for invented-only
depth scenarios and recruitment experiments after approval. R5B must
keep eligibility/metric scopes explicit and reoptimise the whole XI
against a baseline using the same objective, weights, policy, catalogue,
tactic and build evidence. A missing score must never be treated as
zero improvement or a fallback to another model. No signing simulation
or depth implementation is included here.

Real-save activation remains blocked by R4.5: verified full executable
and numeric DB identity, applicable build-specific numerical evidence,
raw evidence completeness, and manual confirmed role placement are
required. Cross-slot comparability of absolute rating and CA-normalized
ability is a modelling assumption, not a calibrated match-performance
measure. Phase weights are provisional, not empirical. R5A offers
no match-win, expected-goal or points prediction, no independent game
validation, and no evidence-backed reason to choose one default objective
for operational use.
