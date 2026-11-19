# Tactical player assessments (version 1)

The Rangers bridge publishes `out/<slug>/tactical_assessments.json` alongside
`formation.json` after a successful refresh. It covers only active squad and
matched F9 target records from the selected career, including overlapping
memberships once. The formation remains a pure configuration contract.

## Evidence contract

Each of the 15 FM position codes independently retains its
`positions_<code>` field. An exact integer (or integer CSV text) from 1–20
is an observed parser-reported rating. Zero, out-of-range, fractional,
boolean, decimal text or malformed values are unknown. Invalid present
numeric evidence takes precedence over category evidence, so it cannot be
hidden by a fallback. When an exact field is absent or blank,
`natural_positions` and `accomplished_positions` can supply a category.
Tokens are case-insensitive native codes, with ST accepted as an alias for
STC. Conflicting categories are unknown. Natural means 18–20 and accomplished
means 15–17 according to fmsave's classifier. Neither provides an exact rating.

| PositionEvidence field | Type / meaning |
| --- | --- |
| position | string (native code) |
| status | observed / inferred_category / missing |
| rating | integer 1–20 or null |
| category | natural / accomplished / below_accomplished / null |
| lower_bound, upper_bound | integer or null; populated for category-only evidence |
| source | field name, conflicting field names, or null |
| reason | missing_position_rating / invalid_position_rating / conflicting_categories / category_only / null |

Observed means the save parser reports a numeric position rating, without
independent verification against the game UI. The legacy broad recruitment
`position_rating` function retains its existing behaviour.

## Slot calculation

Each slot has the same stable ID in both phases. Accepted positions retain
separate evidence. A phase's position fit is the exact rating for that phase's
configured native position, where observed. Text categories remain bounded
evidence with unknown exact phase fit. An omitted phase has unknown position,
familiarity and fit, and reason phase_position_unspecified.

With complete numeric evidence for every positively weighted phase:

```
combined_position_fit = sum((phase_weight / total_weight) * phase_position_rating)
```

Units are the native 1–20 position-rating scale. Zero-weight phases contribute
nothing and do not block calculation. Missing or category-only evidence in a
positively weighted phase yields null and identifies the missing phases.
Weights are not implicitly redistributed. For example, the asymmetric RB with
DC=2 and DR=20 has fit 0.65×2 + 0.35×20 = 8.3 even when all weighted attributes
equal 20. Two DC slots receive the same DC familiarity evidence.

The attribute-profile score is independently calculated with the shared
weighted scorer using the slot's profile and existing normalized attributes.
It requires all weighted inputs; the goalkeeper/outfield domain follows the
existing bridge keeper classification. Missing inputs produce null. Club
availability and loan state remain separate from the numerical scores.
Position fit is an uncalibrated familiarity calculation, independent of
player eligibility and assignment.

## FM role suitability source review

The supported fmsave [Player and Positions models](https://github.com/rhiever/fmsave/blob/main/src/fmsave/models/players.py)
expose the 15 numeric position ratings and classifier categories. The
[export CLI](https://github.com/rhiever/fmsave/blob/main/src/fmsave/cli.py) has
an optional scouting-position output, whose [scouting implementation](https://github.com/rhiever/fmsave/blob/main/src/fmsave/scouting.py)
computes attribute-based scouting scores. The
[tactics model](https://github.com/rhiever/fmsave/blob/main/src/fmsave/models/tactics.py)
describes positional masks, settings and role bits for tactic slots; role bits
do not identify a measured player suitability rating. No reliable
player-specific role suitability value, scale, phase, position and observation
date contract was found in the supported exports. Both phase
`observed_role_suitability` fields and report `observed_role_suitability_source`
are null. Unknown role evidence is reported explicitly. Custom role labels
are descriptive strings. Future measured evidence can be attached to existing
slot IDs without changing the formation.

## JSON schema

Python TypedDict definitions in `tactical_assessment.py` specify the output.

| Report field | Type / meaning |
| --- | --- |
| version | integer, 1 |
| career | string, active career namespace |
| game_date | date string or null, latest active membership game date |
| formation | name string, version integer, source basename string, SHA-256 of canonical validated formation JSON |
| scoring_model | name string and SHA-256 of exact model file bytes |
| position_evidence_source, position_fit_units, attribute_profile_units | strings |
| observed_role_suitability_source | null |
| players | array of PlayerAssessment, sorted by stable player ID |

Each PlayerAssessment has string player_id, name, display_name and club;
cohorts (sorted string array); availability and loan_state (existing
enum values); keeper (boolean); record_game_date, last_seen_game_date and
game_build (string or null); position_evidence (object keyed by native code);
and slots (array in declared formation order). Record date/build refer to
the last changed player version, while last_seen_game_date refers to current
cohort membership. No wall-clock date is substituted for missing evidence.

Each SlotAssessment contains player_id, slot_id, label, side, profile and
availability strings; accepted_positions keyed by native code; ip and oop
PhaseAssessment; attribute_profile_score (number or null);
attribute_profile_reason (missing_attributes / incompatible_player_type / null);
missing_attributes (string array); combined_position_fit (number or null);
combined_position_fit_reason (missing_numeric_phase_evidence / null);
missing_weighted_phases (phase-name array); and missing_evidence (string array).
PhaseAssessment contains position, side, role (string or null), familiarity
(PositionEvidence or null), position_fit (integer or null),
position_fit_reason (string or null), and observed_role_suitability (null).

The sidecar is deterministic for identical input. Existing recruitment and
native HTML remain unchanged. No player data migration is required.
The future XI optimiser still needs eligibility policies for missing/low
familiarity and availability, an objective respecting the separate metrics,
and a one-player-per-slot assignment solver.
