# R1 — FM27 tactic role ability: evidence and implementation readiness

Later milestone: [R3 reference port and validation report](ROLE_ABILITY_R3.md)
records the subsequently supplied redistribution grant; the R1 findings below
remain the historical review. Independent game-numeric validation is still open.

Review date: 2026-11-22. Integration baseline: `7c018c9f494827c1f09e6bb0354be4584e19ba47`.
Decision: feasible as a research programme, **not yet cleared for a distributed
FM role engine or an operational scoring switch**. R1 adds documentation and
invented, test-only validation utilities. No private save, database, game
installation, upstream executable or production scoring path was used or changed.

## 1. Evidence register and licensing

The following revisions were inspected, not executed. Links are pinned to the
reviewed revisions, not mutable branches.

| ID | Source / revision | Evidence and limits | Licence / use decision |
| --- | --- | --- | --- |
| E1 | [fm-mcp role research](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/docs/format/role-ability.md) | Author reports game-function analysis, FM26 screen checks and FM27 code checks; 50 IP and 39 OOP classifiers. Not an independent numerical oracle. | No licence grant established. Citation and review only. |
| E2 | [IP](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/fm/roleability.go), [OOP](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/fm/oopability.go), [IP tests](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/fm/roleability_test.go), [OOP tests](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/fm/oopability_test.go) | Implementation and upstream fixtures, numerical hypotheses and branch coverage. Matching these is reference agreement only. | No copying, translating, bundling or distributing their code, tables or golden data without clearance. |
| E3 | [fm-mcp tactics research](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/docs/format/tactics.md) | Author reports an FM27 27.0.0 screen check of a nontrivial OOP permutation and instruction decoding; active index explicitly a hypothesis. | Reference only; no parser or mappings imported. |
| E4 | fmsave 0.14.3, `755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b`: [tactics model](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/src/fmsave/models/tactics.py), [reader](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/src/fmsave/readers/tactics.py), [players model](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/src/fmsave/models/players.py), [reader](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/src/fmsave/readers/players.py) | Typed parser, explicitly identifies unconfirmed fields; raw inputs and stored tactic geometry available. | MIT ([licence](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/LICENSE)); optional external adapter, retain notices for any copied material. |
| E5 | [FM-Match-Lab](https://github.com/caiograco289/Fm-Match-Lab/tree/79bdbe4cdd6786b442f21ffecc085361d51c9129), [study 13b](https://github.com/caiograco289/Fm-Match-Lab/blob/79bdbe4cdd6786b442f21ffecc085361d51c9129/docs/studies/13b-value-by-position-random.md), [notices](https://github.com/caiograco289/Fm-Match-Lab/blob/79bdbe4cdd6786b442f21ffecc085361d51c9129/THIRD_PARTY_NOTICES.md) | Game-parser-based tactic import on macOS; paired/randomized match studies estimate performance, not role ability. | MIT for project code, excludes game and derived material. No required dependency. |
| E6 | [integration baseline](https://github.com/lewisthornton/fm-scoring/tree/7c018c9f494827c1f09e6bb0354be4584e19ba47) | Own code audit; exact solver and evidence contracts exist. | MIT, preserve existing licence and user data boundaries. |

At E1–E3 the public repository README and conventional licence paths
`LICENSE`, `LICENSE.md` and `COPYING` were checked; no redistribution grant
was established. A public GitHub repo is not automatically open source
([GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)).
No permission request has been sent on the user's behalf. A later contributor
should ask the author for an explicit compatible grant covering implementation,
tables, fixtures and their provenance; an author grant does not automatically
clear third-party game content. Record the exact grant and scope in the ledger.

Alternative: subject to rights/terms review, independently specify observable
behaviour using lawfully obtained, user-authorized game observations and write
original code from that specification; keep a derivation log and source
separation. A public interface using user-authored roles/observations and an
optional local, non-bundled provider is another option if provider usage is
permitted. Neither is permission to reproduce proprietary game data or turn
unlicensed tables into a new format. UK CDPA 1988 sections 50B and 50BA have
conditional interoperability and observation provisions ([legislation](https://www.legislation.gov.uk/ukpga/1988/48/part/I/chapter/III));
their applicability, game terms, jurisdictions and potential database rights
require review before distribution. This is a development risk assessment,
not a legal opinion. No unlicensed implementation or role tables are included
in R1. Until clearance, only original invented fixtures, structural contracts
and explicitly non-FM experimental scores may be distributed.

## 2. Build matrix (external evidence, not our certification)

| Build / database | Evidence | Decision |
| --- | --- | --- |
| FM26 26.3.2 / 3733 | E1 reports IP code and screen corroboration; OOP behaviour incomplete. | Not FM27; out of scope. |
| FM27 27.0.0 / 3754 | E1 reports IP/OOP code analysis, same classifiers as 26.3.2, different IP pull-up and scale precision. | First proposed target; still unvalidated here. |
| FM27 27.0.0+2486695 | E4 advertises normal parser support. | Parser support does not certify role math. |
| FM27 27.0.1 builds 2494769 / 2503222 | E5 match-engine support; no role numerical verification established. | Require separate build evidence. |
| FM27 27.1.0 / 3756 | E1 repository head mentions byte-layout support for 27.1 saves; E4 0.14.3 includes match-report changes; E5 head commit reports 27.1 support (README build list lags). | No certification of role formula equivalence. |

Record full build string, platform, executable/version fingerprint if lawfully
available, database version, parser version and strict reader diagnostics.
Database version alone cannot establish the scoring implementation of a patch.
Unknown or unsupported model/build combinations must produce unavailable role
scores, never silently use a nearest build. No game build is currently certified
by fm-scoring R1.

## 3. Tactic extraction feasibility

E4's Python `Save.tactics()` yields stored copies per team (including presets
and alternate tactics). Filter using our validated career and managed club/team
identifiers, first-team slot and team ID; not club or tactic names alone. The
stored index is a list position, not a durable tactic ID. `Save.selections()`
holds the selected starters/bench, but does not establish which stored tactic
is active. E3's active index interpretation is tentative; its fallback to the
first tactic or last lineup is unsuitable as proof of current selection.

| Field | Current evidence / handling |
| --- | --- |
| Stored tactic list | Available in E4, per managed team; validate reader completeness and first-team identity. |
| IP and OOP position masks | Available; E4 labels only a subset of position bits. Unknown or multiple ambiguous bits remain unresolved. Mask order is not native position-array order. |
| Side | E4 preserves full masks, including column flags; side mapping must be validated against screen examples, separately per phase. Never infer side from the role name. |
| Exact role | E4 supplies raw role/trail bits, explicitly notes different roles can share them. Not enough for verified role IDs. E3 reports a richer parser; its IDs and disambiguation still need permission and independent checks. |
| IP to OOP correspondence | E4 0.14.3 exposes defending index. Verify eleven distinct indexes 0–10; for IP row i read stored OOP row indexed by i's defending index, not the inverse. Keep the IP slot ID and its player. E3 reports a screen-checked FM27 permutation; our unit fixtures are synthetic only. |
| Current selected tactic | Unresolved; explicit selection in local configuration, no automatic active-tactic assertion. |
| Instructions | E4 raw setting units, labels not independently established. Preserve unknown separately; do not turn them into score modifiers. |

The `.fmf` route is not a necessary dependency. E5 demonstrates import using
the installed game's parser on macOS, not a standalone Windows/Linux parser;
upstream Windows FM Tactics Lab is a distinct project. No portable supported
FM27 `.fmf` reader was verified here. Do not call the tactic parser on arbitrary
files or install game tooling in R1. Use a later optional adapter only after
rights, supported-build and independent parsing checks.

Manual fallback: a user-authored TOML or JSON tactic lists exactly 11 stable
slot IDs, each with explicit selection position and IP/OOP position, side,
phase-specific role ID (or null), optional instructions and evidence source.
Validate one goalkeeper in each phase assigned to the same slot, native
position vocabulary, role offered at that phase/position/side/shape, unique
IDs, complete pairing and finite nonnegative weights with positive sum.
Unsupported roles or ambiguous decoding stay null; they are not inferred from
position. An unresolved tactic may be displayed as a draft but cannot run a
role-based objective for a positively weighted unresolved phase. Provide a
manual confirmation/edit path with provenance, not a purported game observation.

## 4. Input audit and proposed contract

At E6, `rangers_autosave_watcher.py::important` persists selected fields in
`record_json`, hashed into historical `player_versions`; the `BASE_FIELDS`
includes `ability_current`, and prefixes include `attributes_`, `positions_`
and `personality_`, **not `raw_attributes_` or raw foot values**. Blank fields
are omitted. The `current_ability` column is parsed separately. The bridge
normalizes display-scale attributes for the weighted scorer and usages of
`position_evidence` retain individual numeric ratings or bounded categories.
Consequently CA and granular ratings can exist but completeness is per record;
raw attribute precision is not retained even if temporary world exports carry
it. This is a source audit, not a claim about the contents of a live database.

E4 returns 52 non-foot player attributes in both display and raw form plus
both feet separately, and a 15-position array. Raw value 73 and 74 may both
display 15: rounded inputs cannot recover exact values. E4 also notes edited
values beyond the normal scale and records with CA zero. Do not silently clamp,
replace zero with one, treat false as zero, or approximate raw inputs by
multiplying by five. Exact normal-domain inputs are required for first model;
out-of-domain observed values are preserved in evidence but unsupported until
verified. See E1 for role-specific dependencies, which need legitimate
independent definition before R3.

Proposed versioned input object (normalized integers, CSV interpretation in a
separate adapter, preserving source fields and rejected raw values):

| Field | Meaning |
| --- | --- |
| `schema_version` | 1 for proposed raw role observation contract |
| `player_id`, `career`, `record_game_date`, `game_build`, `database_version` | Existing stable identity and record provenance, never display name |
| `source` | Parser/version, record hash/source date, field-level evidence and coverage |
| `attribute_scale` | `raw_1_100` only for exact raw numeric calculation; display scale retained separately |
| `raw_attributes` | Canonical raw attribute map, integers 1–100 or null with reason; all dependencies for requested rating and best-role search |
| `raw_left_foot`, `raw_right_foot` | Separate exact values or null; retain for future evidence, not assumed role modifiers |
| `positions` | All 15 native ratings 1–20 or null; separate category bounds and source metadata |
| `current_ability` | Integer 1–200 or null; zero/edited values unsupported pending validation |
| `display_attributes`, `availability`, `cohorts` | Existing observations, interpreted independently of role scoring |

Role rating needs every attribute required by the requested phase role and
every relevant positional input (including side-dependent neighbours); ability
also needs CA and the complete data for determining the player's best legal
role in that phase. A complete local-role rating does not imply a complete
best-role denominator. No guessing absent data, ignoring unknown candidate
best roles or borrowing from another date. Unknown and zero are distinct.
The test-only preflight in `tests/role_validation.py` conservatively requires
all positions and caller-supplied required attributes; actual role dependency
closure belongs to R3. Raw fields marked edited/unconfirmed must not silently
enter a validated calculation. The normal-domain gate is a proposed policy,
not a claim the game never stores other values.

Future R4: extend the scoped whitelist only after approval, include raw
fields in record hashing, keep old rows unchanged and mark their exact score
unavailable until a subsequent accepted observation supplies data. Existing
chronology, replay, identity and cohort semantics remain authoritative. No
data migration or full-world storage in R1. Python 3.11 scoring remains
stdlib-only; `fmsave` 0.14.3 requires >=3.12 and belongs in the optional
external reader environment as today, not the core or CI dependency.

## 5. Numerical model and objective decisions

E1–E2 distinguish an internal role rating (attribute classification and
positional adjustments) from the ability value scaled relative to the player's
best role and CA; IP and OOP have distinct role catalogues and best-rating
searches. E1 reports role thresholds in IP, no corresponding threshold in
27.0.0 OOP, role/side-specific blending, position penalties and build-specific
rounding/pull-up. These are research claims, not copied specifications or
implemented tables in this PR. Display stars depend on an unresolved additional
assessment. A role rating is neither a measured rating in the save nor a
match outcome, and a calculated ability must not be called an observed star.

Proposed result per phase: `role_rating` and `role_ability` (separate integers
on the documented internal 0–200 scale or null), `role_id`, native position,
side, `missing_inputs`, `reason`, `model_id`, `model_hash`, `game_build`,
`evidence_status`. Preserve intermediate diagnostics for validation (e.g.
best rating, effective familiarity, threshold branch), without exposing them
as new independent scores. A zero value differs from unavailable/null.

CA-scaled ability is attractive for cross-player selection because it has a
common nominal ability scale, but per-player normalization can favour a
higher-CA generalist over a player with higher absolute specialist rating.
Example (invented illustration, not FM output): A has role rating 120 and
ability 105; B has role rating 110 and ability 125. The two objectives reverse
their ranking. Even nominally common units do not show that a one-point
change is equally valuable across roles or to match outcomes. Raw ratings
can also differ systematically across roles because their attribute classes
and position penalties differ. Evaluate distributions, rank reversals,
within-player role ordering, side sensitivity and whole-team assignment
stability on a held-out, diverse cohort (no retuning holdout). Quantify rank
correlation and disagreement by role/position and CA band. Ground any claim
of performance superiority in independently designed paired match studies,
not the role-screen score. E5 provides motivation, not coefficients: its
position experiments use specific tactics and randomized attributes; effects
vary by position, not a validation of role ability. No match tests in R1.

After validation, recommend CA-scaled ability as provisional game-suitability
objective, retain raw rating for comparison; keep GK and outfield objectives
separate. Record objective identifier in every scenario. Combined slot ability
is the normalized weighted mean of the two phase abilities, using equal weights
initially (configuration, not empirically calibrated). Missing positive-weight
phase => null; zero-weight phase doesn't block combining. Do not add another
positional score multiplier, because the reconstruction includes positional
adjustments. Existing strict/relaxed eligibility, threshold, category and
optional weighted-phase gate remain explicit independent selection rules.
Same selected tactic, policy, model and score matrix for XI, depth and all
signings. `fm27v2.toml`, formulas, objective and all operational output remain
as-is until an approved later milestone. No role benchmarks or UI work here.

## 6. Independent validation protocol

Evidence status is per model revision/build and tested coverage, not a global
boolean or inferred from the comparator:

| Status | Required evidence |
| --- | --- |
| `experimental` | Documented hypothesis and invented checks; no independent game confirmation. |
| `reference_matched` | Exact agreement with legally usable pinned reference vectors, labelled upstream-derived, not a game oracle. |
| `game_corroborated` | Independent same-build in-game observations of role lists, ordering (ties allowed), attributes, positions and paired tactic responsibilities. Stars alone cannot support numeric status. |
| `game_numeric_validated` | Independent authorized numeric game output for both rating and ability, full test coverage for claimed supported domain and exact agreement per case. If game exposes only stars/order, this remains blocked. |

Do not promote solely on a passing automated suite, upstream agreement, a
derived formula, star order or repeated results from the same implementation.
An independent observer records expected output before running the candidate;
pin artifacts and capture method, date, full build, role catalogue and model
hash, raw inputs and provenance, roles and phase/side/player correspondence.
Store only authorized non-private numeric excerpts/metadata; avoid publishing
game assets, copyrighted tables, save files or real player records. Keep
private local evidence separate and record only hashes and aggregate checks
where lawful. A future independently sourced numeric oracle requires a
supported, authorized game interface or permission; none was obtained in R1.
Do not require the user to run FM or change their installation for this PR.

Minimum planned coverage (freeze each input and expected output before
implementation; each row needs both phases where applicable):

| Family | Cases and acceptance |
| --- | --- |
| Catalogue | Every supported offered role/position; GK/outfield, forbidden role, duplicate label across phases, shape/side-specific availability; no unknown role is guessed. |
| Attribute classes | Independently verified key/preferable/negative classifications; missing one input, all zero, edited values; no inferred role table. |
| Position effects | All 1–20 ratings; boundary +/-1 around every reported penalty/blend threshold; left/right adjacent evidence swapped, DC same rating but different neighbouring familiarity; missing neighbour; known low versus unknown. |
| Best role and threshold | Multiple possible best roles, ties, missing possible denominator, threshold +/-1, special-case floors, no offered role, exceptional CA. Compare phase-local best search independently. |
| Precision | Boundary values where integer truncation and binary32 versus binary64 differ; independent expected exact integer, including near-integer scale, rounding and operation order. |
| Builds | Separate 27.0.0 and patched-build cases; explicit unknown-build refusal; no FM26 substitution. |
| Tactic | 11 slot permutation with a three-cycle, side flags, wrong team, ambiguous role bits, duplicate/missing indexes, unknown active tactic, manual confirmation; compare save and screen/authorized parser results. |
| Integration (later) | Same model/hash/eligibility across XI/depth/signing, identical inputs in different order, missing data, GK separation, careers, untouched legacy and read-only scoped DB. |

Pass criterion for numeric claims: no missing/duplicate cases, every expected
integer matches exactly per phase, metric, build and model, null results
explicitly match; no tolerance or aggregate error masking. For game ordering,
record a separate comparison (ties allowed) and retain all disagreements,
including unexplained differences between players. Unresolved valid cases
reduce the supported domain or block promotion; they are not erased. The
independent corpus remains a blocker for `game_numeric_validated`.

### Reproducible R1 infrastructure

`tests/role_validation.py` provides test-only normalized-input preflight,
structural OOP permutation checking, exact keyed numeric comparison with
provenance fields, and a binary32 conversion primitive. Its comparison returns
differences, not an evidence status. `tests/test_role_validation.py` exercises
these with invented records and outputs (arbitrary mock rating/ability values,
not FM vectors). Run from checkout:

```
python -m unittest discover -s tests -p test_role_validation.py -v
python -m unittest discover -s tests -v
```

Numeric-case rows use `case_id`, `game_build`, `model_id`, `player_id`,
`slot_id`, `phase`, `role_rating`, `role_ability`, `evidence_kind`, `source`;
the expected and actual rows are independently prepared, with the same case
identity. The source points to the separate evidence ledger. Before admitting
real vectors, extend the ledger with frozen input artifact hash, catalogue
hash, side and role definitions, independent capture method and permissions;
no implied validation from a free-text source field. R1 deliberately does not
implement the numerical reconstruction, a role catalogue or binary save parser.

## 7. Milestone gates

| Stage | Deliverable and acceptance | Blocker / dependency |
| --- | --- | --- |
| R1 | Pinned evidence and licence decision; input audit, proposed contract, original validation utilities and tests; unchanged operational path. | Current readiness is conditional, no licence clearance or independent numeric oracle. |
| R2 | Versioned pure tactic schema and manual import, 11 stable slots/phase pairing, explicit selection position, distinct sides, exact phase-scoped role IDs and offered-role constraints, unknown states, canonical hash and provenance; validate with invented formations and all invalid forms. | Publishing actual catalogue entries requires cleared provenance/permission or independently lawful evidence; use synthetic entries for schema tests until then. No production role math. |
| R3 | Pure stdlib role rating and CA-scaled ability APIs, role lookup and dependency closure, distinct phase calculations, build registry, missing/invalid data, exact integer and float32 tests, coverage and evidence status per build. No production scoring switch. | R2 contract, rights clearance, independently specified model/table evidence and lawful test vectors. `reference_matched` is not `game_numeric_validated`. Do not claim exact reconstruction without independent numeric validation. |
| R4+ | Scoped raw input ingestion and tactic adapters, then optional shared objective, role reference distributions and tactic-first UI in separate approved stages. | R3 acceptance and explicit user approval. |

R2 can review the structural contract with invented catalogue entries while
licensing remains unresolved, but cannot distribute the upstream role tables.
R3 cannot be approved as an exact FM27 scoring model solely from R1. The next
decision is whether to seek the upstream author's grant and a lawful numeric
validation source, or restrict development to an independently observed,
explicitly experimental model. Do not turn the latter into an asserted exact
FM role ability calculation.
