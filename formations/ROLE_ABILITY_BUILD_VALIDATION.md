# R4.5 — FM27 build evidence and numerical validation

Reviewed 2026-11-22, integration base `43e6e890b0a91f519e843bf81dbb5f0857ef6ee9`.
Read alongside [R1](ROLE_ABILITY_R1.md), [R3](ROLE_ABILITY_R3.md) and
[R4](ROLE_ABILITY_R4.md). This is an offline research milestone. No runtime
registry, player capture, scoring defaults, formulas or report contracts change.

## Decision register

| Exact build or release key | Numeric save DB | Evidence status | Basis |
| --- | --- | --- | --- |
| 27.0.0 (R3 release-only key) | 3754 | reference_matched | R3 reference examples and golden tests, not a verified executable identity |
| 27.0.0+2486695 | unknown | unsupported | fmsave registered reader layouts |
| 27.0.0+2493426 | 3754 | unsupported | upstream save/container and 27.0.0 release-family research; no independently verified exact-build numeric vectors |
| 27.0.1+2494687 | unknown | unsupported | fmsave mentoring/training reader evidence |
| 27.0.1+2494769 | unknown | unsupported | Match Lab engine observations |
| 27.0.1+2503222 | unknown | unsupported | Match Lab hotfix engine observations |
| 27.1.0+2505117 | 3756 | unsupported | upstream save loading tests, not role scoring tests |
| 27.0.1, 27.1.0 or any other unlisted pair | unknown | unsupported | insufficient exact-pair evidence |

No actual build in this register reaches `game_numeric_validated` or
`game_corroborated` for role ability. The R3 abstract key preserves its
existing reference-matched status; it is not an alias for every 27.0.0
binary. No registry extension is proposed. Numeric DB unknown is not a
wildcard. The offline lookup never authorises scoring.

## Pinned source evidence

- Authorised [Napas/fm-mcp revision 4f19a3f](https://github.com/Napas/fm-mcp/tree/4f19a3f0d1130e47d604173a78ff01642f538d52)
  is both the R3 pin and the latest main revision observed in this review.
  Permission and attribution remain as recorded in [R3 notices](THIRD_PARTY_ROLE_ABILITY.md).
- [PR 54](https://github.com/Napas/fm-mcp/pull/54) introduces FM27.1 save
  reading. Changed-file evidence includes game loading, save versions,
  tests and tactics parsing; not the role classifier, role table or numerical
  role files below. Absence of code changes is not proof of unchanged game code.
- [Role research](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/docs/format/role-ability.md)
  documents FM27 27.0.0 research, including arm64 code observations and
  differences from FM26. It does not provide equivalent 27.0.1/27.1
  disassembly comparisons or exact later-build role vectors.
- [Load271 test](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/fm/load271_test.go)
  names build 27.1.0+2505117, DB 3756; its evidence is save bytes, not
  independently game-checked scoring. [Versions](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/savefile/versions.go)
  does not list 3756 as verified. [Container notes](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/docs/format/container.md)
  distinguish 3756 from original database version 3753 for the 27.1
  save; the two fields cannot substitute for each other.
- [Tactics](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/docs/format/tactics.md)
  identifies a 27.1 change to set-piece structures; successful decoding
  does not establish unchanged role-token identities or tactical constraints.
- [fmsave 0.14.3](https://github.com/rhiever/fmsave/tree/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b)
  describes registered layout coverage for 27.0.0+2486695, and partial
  reader adaptations for other builds. The changelog notes 27.0.1+2494687
  training/mentoring and 27.1.0+2505117 clubs/finances. This is parser evidence.
- [FM Match Lab study 30](https://github.com/caiograco289/Fm-Match-Lab/blob/79bdbe4cdd6786b442f21ffecc085361d51c9129/docs/studies/30-game-update-27-1.md)
  reports changed 27.1 match outcomes (1,500 matches, older engine replay
  comparison). Its independent engine observations do not measure role rating
  or CA-scaled role ability. Even unchanged match outcomes would not
  establish role arithmetic equivalence. No match study is a role oracle.

### Formula and catalogue comparison

The following are blob identifiers at the pinned fm-mcp revision, for
reproducibility, not independent proof about any later executable:

| Source | Git blob SHA-1 |
| --- | --- |
| internal/fm/roleability.go | 803ec62b398ffdc196bf0fa32bd279918b1686d3 |
| internal/fm/oopability.go | f1b540a3832bcd7281b369b928e22883c8f2fb48 |
| internal/fm/roletables.go | a950badc47d14189711fd5de0bfa3cfa8a698cb8 |
| internal/savefile/tacticnames.go | 967781b3d63bc86db635d5542f2354c09a02546e |
| docs/format/role-ability.md | 8e101a0d21c47aad03563feb6274103e765eb099 |

| Dimension | 27.0.0 reference | 27.0.1 / 27.1 conclusion |
| --- | --- | --- |
| IP/OOP classification | 50 IP, 39 OOP classifiers; key/preferable/negative weights | No later game classifier comparison |
| Catalogue/masks | 79 offered roles, 209 explicit placements in R3; side and phase restrictions | No later exact role identity or permission-mask verification |
| Familiarity | Piecewise penalty at 12 and 15; side/neighbor blending; IP pull-up regardless of familiarity (unlike FM26) | No later boundary/side measurements |
| Best role | Phase-local search over native offered roles; context differs from selected tactic placement | No later best-search numeric vectors |
| CA scaling | Rating relative to best, capped at CA before threshold adjustments | No later CA-scaled numeric vectors |
| Thresholds | IP role-specific thresholds; OOP no such thresholds in reference | No later threshold vectors |
| Precision | FM27 float32 path, integer truncation; differs from FM26 float64 path | No later edge-case precision vectors |

The reference Go software chooses FM27 rules for database versions >=3754;
that is a source-level policy, not an empirical compatibility proof.
R3's frozen tests remain untouched, including 51 applicable upstream FM26
rating/best agreement cases (not FM27 ability validation), FM27 documented
examples and synthetic catalogue coverage. The upstream star mapping is
unresolved; its reported ordering observations do not prove exact numeric
scale or cross-player comparisons. No independently obtained FM27 numeric
values were available in this review.

## Build identification contract

The pinned fmsave [SaveInfo](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/src/fmsave/models/meta.py)
and [version decoder](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/src/fmsave/_version.py)
expose the complete save-writing version string (`build`, including
`+number`) and numeric build_number. They read `db_version` as a length
prefixed **string**, listed as unconfirmed. This is not demonstrated to be
the same field as fm-mcp's numeric save database version. Even a string
containing digits does not prove that equivalence. R4 already preserves the
raw metadata and refuses full build strings; its numeric parser conversion
is not proof of that field's meaning. No correction to ingestion is made here.

For future validation preserve separately: game edition, save-writing full
build, executing game full build/platform (they can differ), numeric current
save DB and source, original DB and source if known, parser database string,
parser version and known_build flag, reader field status, catalogue/model
hashes. Do not trim, infer, compare lexically, or infer the current numeric
DB from the original content version. The proposed exact mapping is the
register above; unlisted combinations fail closed. `known_build` indicates
registered layout coverage, not verified player fields or numerical support.
R5 requires a verified portable numeric DB source and exact executable/save
identity mapping before any real build is enabled.

## Reproducible independent validation protocol

Pre-register a case manifest and obtain expected values **before** running a
candidate. For each target build record executable version/platform,
save-writing build, numeric DB evidence, source artifact hash, lawful capture
method and capture date. Use anonymised invented players. Freeze exact raw
1–100 inputs, feet, CA, all 15 positions, phase, role ID, position, side,
centre-back count and relevant tactical context. Hash the canonical input
JSON (sorted keys, compact separators, UTF-8); include the same input digest
on both sides. Record both independent expected and candidate rating,
best-role rating and ability as integers or explicit null; a null must state
the reason in the accompanying manifest. Never derive an expected number
from the candidate, a star value, a rounded attribute or another build.

| Case family | Minimum discriminating contrasts |
| --- | --- |
| Attributes | vary key/preferable/negative independently, with all others fixed |
| Positions | 1, 11, 12, 14, 15, 20; unequal neighboring ratings and both sides |
| Roles | GK plus outfield, every offered role/position, disallowed placement, three-DC vs two-DC context |
| Phases | same player under distinct IP/OOP exact roles; independent best-role search |
| Search/scaling | ties, different strongest roles, CA extremes, threshold below/at/above |
| Precision | fractional weighted sums, exact boundary and one-unit changes near truncation |
| Missing evidence | absent raw values, CA or neighbors; distinguish null from zero |

Use `python role_build_validation.py expected.json candidate.json` to compare
separately prepared bundles. Each has schema_version 1, full build,
numeric database_version, model_sha256, catalogue_sha256, artifact_sha256,
source_kind, and a nonempty cases array. Expected additionally has
capture_method. Case keys are case_id, input_sha256, role_rating,
best_role_rating, role_ability. The candidate source_kind is `candidate`;
expected may be `synthetic`, `upstream_reference` or `game_numeric`.
Hashes must be lowercase SHA-256 hex. Duplicate/missing cases, mismatched
identities and input digests are rejected; mismatch output reports each exact
integer or null discrepancy, with nonzero exit on disagreement. The comparator
does not bypass R3's gate, calculate outputs for unsupported builds, verify
source authenticity or promote status. A reviewer must check artifacts,
capture independence, completeness and declared scope. An invented fixture
can exercise the comparison mechanics but establishes no game compatibility.

If game interfaces expose only stars/role order, capture those separately:
same player, exact build and role/phase/position/side, screenshot or export
hash, displayed stars or ordered roles, ties, sample/coverage and capture
method. Never feed these into the numeric comparator. Such evidence could
support `game_corroborated` for that observed behaviour only.
Reference-matched requires applicable independently prepared reference
vectors; game_numeric_validated requires independently obtained exact
game numbers and a stated tested domain, not reference equality alone.

### Smallest practical user-assisted next step

No personal save or install is required for CI. If a future volunteer has
lawful access to a disposable test career, first capture the full title-screen
build and read-only parser metadata, plus one invented goalkeeper and one
invented asymmetric outfield player's exact inputs. Capture the displayed
role ordering/stars in each phase, including two different familiarity
ratings, and preserve evidence before seeing predictions. This is only
corroboration. Ask upstream researchers for independently captured,
redistributable exact numeric vectors tied to full build and numeric DB,
or a sanctioned game numerical export/interface. Without such an interface,
exact numerical game validation is blocked; do not modify executables,
read private saves or fabricate numbers. Keep the validation procedure opt-in.

## R5 readiness

R5 may design model selection and objective interfaces against synthetic
fixtures and the existing abstract R3 reference pair only. No observed full
FM27 build is presently eligible for experimental numerical optimisation
through the real-save pipeline. Require verified raw evidence, exact tactic
roles, full-build registry entry, documented validation domain and
explicit opt-in before activation. Keep absolute rating separate from
CA-scaled ability: the latter normalises by the player's own strongest
role and can invert rankings, so neither is independently calibrated for
cross-slot expected performance. A provisional 50/50 phase aggregation is
a modelling choice; preserve both phase metrics and require all positively
weighted phases. A later-build discrepancy warrants a new versioned model,
not retuning R3 or replacing golden references. Operational fm27v2 remains
unchanged. R5 implementation is outside this PR.
