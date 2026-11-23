# Touchline M2b — Squad experience

## Product intent and repository audit

Turn the existing decision centre into a connected club intelligence workspace.
The target is a manager reviewing a selection concern, comparing internal
alternatives, examining a player's evidence, and deciding whether to recruit.
The original approved implementation boundary was **M2b.1 only**.
PR #29 merged that foundation; the current implementation boundary is
**M2b.2 only**. Later gates remain independently reviewed and deferred.

Audit base: PR #28 (45acd2f). The React/TypeScript client is a small
dependency-light app: main.tsx owns views, async queries and route state;
state.ts serializes opaque generation, slot and player IDs into the fragment;
style.css supplies the dark theme and responsive layouts. The server already
validates six immutable analytical reports and M2a's separate history artifact.
M1a–c and the M1 closure document establish the report, offline launch,
selection, keyboard, browser history and explicit generation-switch contracts.
The current pitch and assignment table share a slot; the slot details expose
eligibility, alternatives, depth dependencies and absence scenarios. Recruitment
uses engine-order candidates, selected-slot comparisons and signing impacts.
Reuse those views and IDs; do not replace the engine, route model or renderer.
Extract the shell and common primitives, strengthen visual hierarchy, and
make planned destinations visibly unavailable. Defer new data consumers and
charts. Existing browser tests cover keyboard traversal, pinned switching,
offline requests, reflow, axe and screenshot artifacts.

M2a provides /api/profile, /api/history and /api/benchmark, all GET-only,
generation-pinned and identity-scoped. History is sparse and paginated (1–50
actual versions); legacy generations lack the artifact. Preserve that boundary.

## Information architecture

| Destination | Primary question | Layout and onward navigation |
| --- | --- | --- |
| Overview | What needs attention? | XI completeness, depth risks and hypothetical upgrades; direct links to slot and candidate |
| Squad | Who is in my squad and where are the gaps? | Summary and searchable directory; canonical player selection to profile or tactical slot |
| Player profile (within Squad) | What do we actually know about this player? | Identity and last observation; overview, suitability, development and provenance sections; link to relevant slot or candidate |
| Tactics & XI | Who fits the current shape? | Existing pitch and assignments, selected slot detail, eligible alternatives and coverage |
| Recruitment | Which target changes the team? | Existing candidate list, incumbent comparison, signing scenario; links back to tactical slot and eventually profile |
| Analysis | How does the squad compare with the league? | M2c, not M2b; link from player benchmark only when implemented |
| Staff | Who supports the team? | Deferred |
| Data & Settings | What evidence and configuration underpin this decision? | Generation provenance, limitations and report versions |

The desktop shell has a left workspace rail, a global pinned context bar and
one central content landmark. At tablet widths panels stack as capacity
requires; at mobile widths workspace buttons wrap above content, context
remains visible, cards stack and wide tables scroll inside labelled regions.
No full-page horizontal scroll. Use a 4/8/12/16/24 spacing scale, local
system sans fonts, restrained dark surfaces, neutral primary figures,
mint interaction/selection, amber caveats, explicit labels and high-contrast
focus indicators. Avoid decorative motion, remote fonts and icon-only controls.
Use native buttons, headings, labels, tables, disclosure controls and
status/alert semantics. The skip link targets the main landmark; workspace
changes move focus to main, comparison selection focuses the detail heading,
and return restores the candidate control. Browser Back/Forward retain
generation and selections. Never encode a player name as identity.

## Planned workspace details

**Squad directory:** summary first (active squad membership, not inferred
contract ownership), compact searchable/sortable table with player, club,
cohort, availability, position context and last-seen date. Filters for
availability and position only when evidence supports them. Keep stable IDs
and distinguish duplicate names. Use the existing overview player directory,
not bulk history. Empty filters are different from unavailable data.

**Player profile:** header with canonical identity, observed club, membership
state and date of last stored observation; show accepted game chronology
and last seen separately. Primary overview exposes recorded attributes with
their original meanings and explicit missing fields, then current tactical
assessment and benchmark. On-demand profile and benchmark queries are
bound to the selected generation. Show score units, model, eligibility and
reference extraction date, population and limitations. Use aligned tables
or bars on a fixed comparable scale; don't compare GK and outfield totals
or treat contextual familiarity as role ability. Inactive, missing, legacy
and invalid history all have distinct explanations.

**Development:** paginated history ordered by snapshot ID; show recorded
points against game date, with equal-date revisions individually accessible.
No interpolation, forward-fill, fabricated observations, inferred transfers,
or historical recalculation. If a chart is used, show isolated points,
explicit units, labelled axes, selected attribute and accessible equivalent
table; no trend line with one point, and no connecting line across unknown
periods. Unknown is not zero. Benchmark data describe the current published
reference only, never historical league performance.

**Evidence vocabulary:** observed = captured record or membership evidence;
calculated = existing weighted assessment, optimisation or benchmark;
assumed = hypothetical availability/signing; missing = not recorded;
unavailable = unsupported, legacy or invalid artifact; not evaluated = engine
limit, not negative outcome. Use text labels in addition to colour. Preserve
source/model and assumption disclosures, separate game/observation/import/
generation dates, and keep all six report and M2a contracts intact.

## Acceptance gates

| Milestone | Required acceptance (each gate independently reviewed) |
| --- | --- |
| M2b.1 Foundation | Reusable shell, panel/tag/state components, consistent navigation and source context, responsive desktop/tablet/mobile; existing Overview, Tactics, Recruitment and Data views preserved; planned destinations explicit; keyboard and focus continuity, explicit generation switch, URL/history retention; local-only runtime, no data/API/engine changes. |
| M2b.2 Directory | Active squad directory with canonical identity, explicit cohorts/availability/last seen, search, stable sort and evidence-aware filters, keyboard-accessible rows, empty/unavailable states, namesake and overlap tests; route links preserve generation; no profile/history charts yet. |
| M2b.3 Profile and suitability | On-demand pinned profile and benchmark endpoints, legacy/inactive/invalid cases, recorded attributes and missingness, current suitability and reference comparisons with units/date/reasons; links between squad, tactics and recruitment; no historical scoring or new analytics. |
| M2b.4 Development | Bounded history paging; actual stored observations only; equal-date revision handling, single-point/empty/corrupt history, accessible point chart and equivalent table, explicit source dates and missingness; no interpolated events or charts that imply continuous observations. |

Each gate requires invented-data tests and regression checks for M1 workflows,
accessibility, offline operation and generation pinning. Physical Windows
acceptance and independent review remain separate from CI. No automatic
implementation of a later gate is authorized.

## M2b.1 scope

The existing hash route remains the single navigation state. The shell
receives the pinned route and matching provenance, not the latest pointer.
Assigned-player names open their existing tactical slot; candidate names
open the existing comparison. Both use the same player-action styling.
Names without an existing destination remain text, and profile routes are
deferred. No new endpoints, scoring, dependencies,
persistence or launcher changes. Build and test with the M1c commands and
invented fixture; browser evidence is uploaded by the existing CI workflow.

### M2b.1 verification (local Linux, invented fixtures)

- Python unittest discovery: 217 passed.
- TypeScript production build and frontend state tests: build passed, 3 tests passed.
- Python-only production runtime and launcher smoke checks: passed with Node
  absent from runtime PATH; clean shutdown and duplicate launch refusal.
- Chromium workflow: 3 passed, including keyboard comparison and signing,
  Back/reload, generation switch and invalid pointer handling, no external
  requests, reduced motion, responsive reflow and axe WCAG 2 A/AA checks.
  The final expanded shell test (including assigned-player navigation) passed
  independently. Overview screenshots at 1440, 768 and 390 CSS pixels,
  mobile tactics, and recruitment screenshots at 1440, 1280, 768 and 390
  are produced in Playwright results. The CI workflow uploads them.
- Firefox/WebKit, the real Windows runner, and independent/physical Windows
  acceptance remain separate checks; do not interpret Linux smoke tests or
  automated axe checks as full accessibility or Windows certification.

## M2b.2 — Squad directory implementation

Audit base: `a69c5bc` (merged PR #29). `touchline_server.py:player_card`
already supplies the necessary directory fields from the validated tactical
assessment. The generation validator checks canonical player/member sets and
last-seen dates; the overview supplies the canonical baseline assignments
and slot labels. The directory is a frontend-only consumer of this existing
generation-pinned overview. It neither queries the database nor fetches
individual profiles/history in bulk. No report or endpoint changes.

| Directory evidence | Source and definition |
| --- | --- |
| Active squad | Unique canonical overview players whose `cohorts` contains `squad`; not ownership, first-team registration or proof of a complete real-world roster. |
| Known availability | Active squad rows with `availability` equal to `available` or `unavailable`; the bridge derives this from club and loan evidence, not injury, fitness, suspension or registration. |
| Unknown availability | Remaining active squad rows; unknown is neither available nor unavailable. |
| Assigned in XI | Active squad players with a non-vacant published `baseline` assignment joined by `player_id` and `slot_id`; calculated, not actual match selection. |
| Player and club | `display_name`, `club`; internal row/navigation identity is `player_id`; missing club is labelled. Namesakes show the canonical identity. |
| Cohorts | All active `cohorts` on the card, including overlap with `target`; overlap does not duplicate rows or counts. |
| Analysis domain | Published `keeper` classification (GK rating at least 18, or fallback natural-position text); false can include missing GK evidence. This is an analysis domain, not observed outfield ability or tactical eligibility. No granular position ratings in `player_card`, so no granular position filter or positional-depth claim. |
| Availability and loan | `availability` and `loan_state` from the card; no inferred contract or fitness state. |
| Observation date | `record_game_date` of the stored latest record; `last_seen_game_date` is separate membership evidence, the maximum across the player's active cohorts. Neither is an import timestamp, current chronology, nor publication date. |

Search is case-insensitive and whitespace-trimmed, with name, availability
and published keeper/outfield domain filters combined. Column sorting is deterministic
in both directions with missing text/dates last and canonical ID as the
ascending tie-breaker. Reset restores name ascending and all filters. The
directory displays a live result count and 25 rows per page. Empty active
squad membership, no matching rows and a generation unavailable at the
server are separate states. Missing granular position evidence is disclosed;
the directory does not count unobserved ratings as zero or invent positions.

Only players with an existing baseline XI assignment have a player action:
it opens the exact tactical slot with the canonical player ID and pinned
generation in the hash. Unassigned players have no profile destination yet.
Browser Back/Forward and reload use existing hash navigation. Filters are
local presentation state and reset on remount/generation change. Explicit
switching validates the destination overview before navigation, follows the
same assigned-player identity to its new baseline slot (or clears the link), clears
selections outside the active squad when on Squad, and leaves the user in
the Squad workspace if a slot disappeared. A new pointer does not change
the displayed rows. Absence from a subsequent cohort is not evidence of a
transfer or release. The existing accepted chronology and publication
provenance remain distinct from the displayed record and membership dates.

### M2b.2 verification and acceptance

- Python unittest discovery: 217 passed on Linux, invented data only.
- Frontend state tests: 8 passed; production TypeScript/Vite build passed.
- Linux Python-only production runtime and launcher smoke: passed, including
  Node absent from runtime PATH, duplicate launch refusal and clean shutdown.
- Local bundled Chromium: all 7 browser tests passed (including the small
  performance fixture and the existing workflow/regression checks). At all four
  directory widths, no page-level horizontal overflow and no reported axe
  WCAG 2 A/AA violations. Keyboard activation, sort state, filters, reload,
  Back and explicit generation switch were exercised. System Chromium could
  not start under the host's process/socket restrictions; the bundled browser
  succeeded. Local Firefox/WebKit were not available.
- Browser evidence is produced by `workflow.spec.ts` and uploaded by the
  existing `touchline-browser-evidence` CI artifact. The new test captures
  Squad at 1440/1280/768/390 and filtered/no-match states at 1440/390.
  Since the watcher rejects an empty squad import, the defensive empty
  directory UI test intercepts the invented overview response with an
  explicitly synthetic empty projection; it is not evidence of a successful
  empty-squad publication. It separately exercises an unavailable pinned ID.
  Additional browser coverage switches between two genuinely published
  fixture generations and checks that overlapping cohort evidence changes
  only after explicit acceptance, with Back restoring the pinned evidence.
- Physical Windows acceptance, independent review and final CI verification
  remain outstanding. M2b.2 is not formally closed by implementation alone.

Excluded: profile/history/benchmark drill-down, granular positional evidence
contracts, new analytics, scoring or solver changes, watcher, launcher,
persistence, dependency and league/staff workspace changes.
