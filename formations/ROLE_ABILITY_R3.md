# R3 — Experimental FM27 tactical role ability reference port

Review date 2026-11-22. Base integration commit
`9b48f0dcec4dbdd2b876d56acf51048ea2410ad7` (R1 and R2 merged).
This milestone is a pure Python reference implementation and **not** an
operational model switch. Nothing in `score.py`, the watcher, bridge, optimiser,
depth, simulations or benchmark algorithm imports the new numerical library.
Existing weights, schemas, generated reports and databases are unchanged.

## Source and permission

See [third-party attribution and the maintainer-supplied grant](THIRD_PARTY_ROLE_ABILITY.md).
The user represented that permission to publish and redistribute the reference
implementation was granted by the author, and supplied unrestricted grant
wording in response to an explicit redistribution-scope question. We preserved
that wording and attribution; no upstream MIT declaration is asserted. The
reference work is pinned to `Napas/fm-mcp` commit
`4f19a3f0d1130e47d604173a78ff01642f538d52`. R1's independent game-numeric
validation gate remains unresolved. The licence evidence is distinct from
technical evidence and rights in the game itself.

## Catalogue and tactic contract

`fm27-role-catalogue.toml` is a reference-derived catalogue v1 normalized by
the existing R2 `tactic.validate_catalogue`. It carries stable phase-qualified
IDs, English reference labels, original classifier bit, all three attribute
classes, explicit position/side placements, phase-local centre-back count
constraints, source revision and model version. The numerical port accepts
only the pinned canonical catalogue hash:

`51488bd5bbab4c0420c0c3408b969b271e7ee49d748a5e71cc002cad91147689`

All 50 IP and 39 OOP classifiers from the source are retained. Of these, 40 IP
and all 39 OOP have offered positions; there are 118 IP and 91 OOP explicit
position/side placements (209 total). Ten IP classifiers have no offered
position in the reference masks: `complete_forward`, `ball_winning_midfielder`,
`defensive_winger`, `anchor`, `no_nonsense_full_back`, `enganche`, `regista`,
`wide_target_forward`, `mezzala` and `segundo_volante`. They are recorded but
cannot be selected/scored. SW has no offered roles in either phase. Labels
are upstream's English names, some of which it notes are inferred; no claim
of localized labels or independent UI confirmation. Role bits are not inferred
from a save's raw tokens. Role ID is the phase prefix and normalized name.

Documented context constraints are interpreted conservatively: wide/overlapping
IP DC roles need a side and at least three DC slots in that phase. Wide OOP DC
roles, the specified DM/MC roles requiring a side, and splitting OOP outlets
at AMC/ST require left or right. Flank positions imply the matching side.
The code validates the R2 exact placement; it never converts a role to a
different position. The upstream research notes that some caller context
and third-argument interpretation remain open. No extra formation/duty or
instruction modifiers are invented. The best-role denominator uses the
reference's unsided offered-role search, NOT these tactic context constraints.

R2's synthetic catalogue is unchanged and cannot be scored by this model.
R2 legacy labels stay unresolved. A manual v2 tactic can use the new catalogue
by explicitly specifying IDs such as `ip.inside_full_back` and
`oop.holding_full_back`, with their correct phase positions and sides. Manual
assignment remains `user_defined`, not purported game-observed role identity.
The R2 selection envelope still sets `role_scoring_available=false` (its
operational flag); R3 consumes it as a validated configuration, not activation.
No automatic save-tactic parsing, game-observed role mapping or UI added.

## Exact compatibility registry

| Concern | Support |
| --- | --- |
| Numerical model | `fm27-role-ability-r3`, version 1, `fm27-2700-reference-v1` |
| Exact reference release/database pair | `game_build="27.0.0"`, `database_version=3754` only |
| Catalogue | `fm27-reference-2700`, version 1, hash above |
| Model descriptor SHA-256 | `f6049ec4cb93184b3bc9349d5d6f800e5d6e3f6bbac76b37ed6ee2c9f3a53e17` |
| Evidence | `reference_matched` for the checked reference vectors; `independently_game_validated=false` |
| Parser | No parser dependency; fmsave compatibility unrelated to numerical support |

The release label is the upstream numerical evidence label, not proof that
every executable with that marketing version implements the same functions.
R1 distinguishes parser-supported `27.0.0+2486695` and match-engine-tested
27.0.1/27.1 builds from reference formula validation. The explicit registry
rejects build suffixes and patch versions, including 27.0.1 and 27.1.0, and
database 3756; do not truncate a parser build string to get support. Later
build/version mappings require evidence before extending this registry. FM26
is not supported. The model hash is a canonical manifest hash binding the
arithmetic version, source revision, exact supported build pair and catalogue
hash; bump the model/arithmetic version for any numerical change. It is not a
hash of a running game executable. Unknown model, wrong origin, different
catalogue hash, unknown build or mismatch between observation and requested
build yields null instead of fallback. A hash is not independent attestation.

## Input contract and dependency closure

The pure scorer accepts the R1 normalized player record. No file format or
database conversion occurs here. Key numerical fields:

| Field | Requirement |
| --- | --- |
| `schema_version` | Integer 1 |
| `game_build`, `database_version` | Exact matching requested pair |
| `attribute_scale` | Literal `raw_1_100` |
| `raw_attributes` | Exact integer values 1–100 keyed by canonical snake-case field names in catalogue |
| `positions` | Native position codes with exact integer ratings 1–20 |
| `position_categories` | Optional separate category evidence; never a substitute for an exact rating |
| `current_ability` | Exact integer 1–200 for role ability |
| `player_id`, `career`, `record_game_date` | Stable identity and observation provenance; player ID required for tactic assessment |

Null/absent values are `missing`, category-only positions `category_only`,
malformed types (including bool, float and numeric strings) `invalid_type`,
out-of-domain values `unsupported_value`, wrong scale `unsupported_scale`.
Explicit invalid numeric data does not become category fallback. Observed raw
zero or edited values outside normal domains are unsupported, not clamped.
No exact value is reconstructed from display attributes. A legitimate calculated
ability of zero (e.g. threshold halving) is returned as integer zero, not null.

A rating requires only the three attribute classes of that role and the base
position; neighbour(s) are required conditionally when the relevant blend
branch applies. An ability additionally requires CA and the complete best-role
search within that phase. All offered position ratings must be exact to know
which candidate roles enter the search (SW has no offered roles and is not an
independent requirement). Only attributes and neighbours used by possible
candidates at positions >=10 are required. A missing alternative candidate
input invalidates the denominator; do not ignore it, even if another known
rating looks stronger. Rating can still be available when ability is not.
CA is required even when a complete search proves the best rating is zero.

## Numerical port

`role_ability.py` ports the pinned reference's FM27 branch. Key, preferable
and negative means use relative weights 16, 4 and 3, with the negative values
transformed to `max(100 - value, 1)`; only nonempty classes contribute.
Explicit IEEE binary32 rounding boundaries match the Go arithmetic before
integer truncation. Position familiarity adjustments use the reference's
pieces at ratings 12 and 15; applicable roles blend a neighbouring position
as documented (including side and False Nine special handling). Position
penalty is applied to the raw rating once. No additional multiplier exists.

The phase-local strongest rating is calculated over the reference's offered
positions rated at least 10. IP best thresholds differ from the final ability
thresholds. Ties return all equivalent role/position pairs deterministically.
The best search uses unsided roles (wide centre-back chooses the higher full-back
rating without a side); the requested role uses the exact slot side. OOP uses
its own groups, position blending and best search, without IP thresholds.
For 27.0.0 the reference moves a lower rating towards the best at every
position rating, then scales onto the CA axis with a float32 ratio and
product. IP threshold halving is applied after this scale; no OOP halving.
The pinned reference bypasses scaling/halving if no best rating exists and
returns the rating; R3 requires complete evidence and exact CA before doing so.
The FM26 pull-up condition and float64 scale implementation are deliberately
not accepted. See pinned source and R1 for detailed research limitations.

## Pure API and output

```python
import tactic
import role_ability
from pathlib import Path

catalogue = tactic.load_catalogue(Path("formations/fm27-role-catalogue.toml"))
# selected is a validated R2 selection envelope using this catalogue.
# player is a scoped R1 normalized observation as above.
report = role_ability.assess_tactic(
    selected, catalogue, player,
    model_id="fm27-role-ability-r3", game_build="27.0.0", database_version=3754,
)
```

`evaluate_role(player, catalogue, role_id, phase, position, side, *, model_id,
game_build, database_version, centre_back_count=None)` is the single-role
interface; context-restricted roles require an explicitly supplied count.
`assess_tactic` verifies the selection's tactic/catalogue hashes, keeps all
eleven IDs in declared order and evaluates both phases independently. It caches
the two phase denominators within the report. Each phase emits position, side,
role ID/status, `role_rating`, `role_ability`, best rating/ties, base and
effective positional evidence, neighbour evidence and penalty, separate
rating/ability input issues and failure reasons, model ID/hash and evidence
status. `role_rating` and `role_ability` are separate nullable integers.
The top-level report includes identity, career/date/build, tactic/catalogue
hashes, model manifest/hash and weights. `model_unavailable_reason` is null
only when model compatibility is confirmed; individual role metrics may still
be null. An unavailable phase cannot acquire an invented role or score.

Failure reasons include `unknown_model`, `unsupported_catalogue_origin`,
`model_catalogue_mismatch`, `unsupported_game_build`,
`observation_build_mismatch`, `unsupported_observation_schema`,
`unresolved_role_or_geometry`, `unknown_or_wrong_phase_role`,
`unsupported_role_placement`, `unconfirmed_formation_context`,
`rating_inputs_unavailable`, `role_rating_unavailable`,
`best_role_search_incomplete`, `current_ability_unavailable`. Invalid selection
hashes or invalid API position/phase tokens raise ValueError (structurally
invalid request rather than missing player evidence). Evidence status denotes
the model's tested level, not that an individual unavailable value is validated.

Combined ability uses the configured normalized weighted mean of the two
CA-scaled values (default R2 examples 50/50, or explicit weights). A missing
positive-weight phase yields null and its name in `missing_weighted_phases`;
zero-weight phases cannot obstruct the combination. This is provisional
modelling, not part of the FM reference formula. Report no match outcome claim.

## Validation results and limits

All tests use invented player observations. Author-published synthetic
references are used with the supplied permission. No game, private save,
backend Go service or live parser was executed in this environment.

| Evidence | Verified |
| --- | --- |
| Synthetic-tested | Analytic uniform-attribute oracle for all 209 allowed placements (both phases, raw rating, best rating, ability), distinct roles/sides and GK; input and build rejection; deterministic slot assessments; phase-weight handling; ranking reversal. |
| Reference-matched | Exact documented reference test examples for class weighting, position penalty, IP blending, all 26 OOP blend cases, threshold and phase scaling/pull-up including binary32 one-point boundaries; best-search and no-best examples. |
| Reference golden | The pinned upstream file contains 154 cases and 44 invented input records; its final ability expectations use FM26 rules. 51 cases are within R3's strict input/placement domain and match **both rating and best rating exactly**. 100 request unoffered or context-disallowed placements and are verified unavailable; 3 contain unsupported raw inputs and are verified unavailable. No numeric mismatches among the 51 applicable cases. FM26 final ability expectations deliberately not compared to FM27. No golden expectation altered. |
| Independently game-validated | No independent authorised numeric game oracle. **Not established.** |

`reference_matched` is a claim about these checked vectors, not an assertion
that every possible input or role exactly reproduces the installed game. The
Go reference itself was not executed; the portable tests compare to its
published expected values and synthetic mathematical invariants. No real
save examples, stars or rankings were used as a numeric oracle. Real game
validation, build patch equivalence, context interpretation, and display
star mapping all remain open. No known mismatching applicable reference
vector was suppressed; excluded cases have separate explicit counts and
assertions. Numeric mismatches discovered later must be retained and resolved.

Run `python -m unittest discover -s tests -p test_role_ability.py -v` and
`python -m unittest discover -s tests -v`. The existing Windows/Ubuntu
Python 3.11/3.12 CI matrix requires no added dependencies.

## Objective choice and R4 contract

Two invented natural keepers illustrate the difference: A has all raw
attributes 80 and CA 90, B has all raw attributes 50 and CA 140; both GK 20.
For IP Goalkeeper the reference port returns A rating 144, best 160, ability
85; B rating 100, best 100, ability 140. An attribute-specialist ranking
and CA-scaled ranking therefore disagree. CA incorporates overall player
quality and per-player normalization; it does not calibrate marginal match
outcomes. Combined IP/OOP CA units offer a consistent nominal scale but
different phase denominators, role thresholds, distributions and side effects
can change rank across slots. Equal phase weighting assumes neither phase is
favoured, not observed time in possession or goal/point effect. A weighted
mean is not a calibrated win or xG objective. Retain both metrics, compare
assignment reversals and distributions on authorized independent data, and
provisionally prefer CA-scaled combined ability only for an explicitly
approved game-role suitability objective after validation. Keep goalkeeper
and outfield totals separate, selection eligibility unchanged, and do not add
familiarity penalties twice. No change to current exact solver or operational
objective in R3.

R4 may extend scoped ingestion, only after approval:

- Preserve raw 1–100 attributes on original scale under `raw_attributes_`
  names; canonicalize spelling to catalogue names (e.g. `one_on_ones`,
  `command_of_area`, `rushing_out`) via an independently checked parser map.
  Do not substitute display values or fabricate CA/position values.
- Preserve `ability_current`, all 15 granular `positions_` values with
  explicit missing/invalid evidence, categories separately, raw foot values
  for possible future use, stable career/player/record source, date, exact
  game/database version and parser provenance. Record hash must include new
  fields; old history remains intact and unavailable when precision absent.
- Read managed first-team tactics only with independently confirmed team
  identity, source save hash, parser version, tactic ID/name/selection,
  11 paired phase positions/sides, exact role IDs only where verified,
  defending permutation, instructions and provenance. Unknown stays unknown.
  Reuse R2 adapter; explicit selection remains necessary.
- Build a separate non-operational assessment report first, bind model,
  catalogue, tactic, player observation and career provenance. Do not alter
  existing `formation.json`, `tactical_assessments.json`, or other production
  output contracts until a later approved integration.
- Do not persist the full world. Preserve chronology, scoped SQLite history,
  cohorts, availability, legacy launch and all current scoring output.

R4 does not receive automatic permission to switch scoring. Independently
validated model/build evidence and explicit integration approval remain required.
