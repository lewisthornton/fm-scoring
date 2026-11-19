# Rangers integration characterisation

Run from the repository root with Python 3.11 or newer:

```sh
python -m unittest discover -s tests -v
```

No external packages, live FM save, installed fmsave, or F9 exporter are required.
The tests substitute the parser boundary, exercise the actual watcher import
transaction, invoke the real bridge CLI and native scoring CLI, and inspect the
generated HTML data. All observations and databases are invented and temporary.
The current tests verify HTML data and file generation, not browser interactions
or compatibility with a particular installed fmsave version.

## Shared scoring mathematics

The standalone root module `scoring.py` has no dependencies or I/O. Its public
functions accept an attribute mapping and the existing weights/model mapping:

- `weighted(attrs, groups)`: labelled weighted positional (or staff) scores;
  roles missing any required attribute are absent from the result.
- `curve_value(points, x)`: existing piecewise linear outfield interpolation.
- `curve_scores(attrs, model)`: existing curve-weighted equivalent attribute
  levels, omitting unobserved attributes.
- `win_score(attrs, model)`: sum of experimental outfield win-index
  contributions over observed attributes.
- `pts_value(points, x)`, `pts_score(attrs, model)`: keeper points per season,
  using the goalkeeper breakpoints and observed contributions.

The native `score.py` re-exports those functions and `PTS_LEVELS`. The Rangers
bridge delegates its single-profile `score` adapter to `weighted`, retaining
its convention of returning None for missing or zero-total profiles. The native
function retains its original error behaviour for malformed zero-total profiles.
Empty/missing optional win and keeper points tables return None; if configured
but no attributes are observed, the old sum is zero. The win index and keeper
points are separate experimental quantities, neither a calibrated match
probability. No weights or arithmetic are changed.

Both launch layouts are supported, using the selected checkout's exact
`scoring.py` for bridge and native scoring. For the existing standalone Windows
launcher, update the repository checkout and replace the bridge and its
`rangers_club.py` companion in the launcher directory with the versions from
`integrations/rangers/`. Leave the local database and launcher arguments as-is:

```powershell
py C:\FMAnalytics\rangers_fm_scoring_bridge.py --fm-scoring-root "C:\path\to\fm-scoring" --watch
```

The database still defaults to the file next to the bridge. Alternatively
launch from the repository with `--db` pointing at the existing database:

```powershell
py C:\path\to\fm-scoring\integrations\rangers\rangers_fm_scoring_bridge.py --fm-scoring-root "C:\path\to\fm-scoring" --db "C:\FMAnalytics\fm_rangers_scoped.sqlite3" --watch
```

No scoring module needs to be copied beside the standalone bridge. The selected
checkout must include the new root module; an older checkout without it is
rejected explicitly before rendering. Both CLI entrypoints and arguments are
preserved. A regression test copies the launcher and companion into a separate
directory, uses an invented database at the default path, and verifies identical
HTML output, read-only database access, and exact checkout module selection.

`test_scoring.py` freezes pre-refactor numerical vectors for every fm27v2
positional profile, interpolation, missing attributes, experimental metrics,
and precision. The integration parity test freezes the pre-refactor embedded
JSON from all eight generated pages using an invented mixed squad and four
recruitment targets. Object keys are sorted, list ordering is preserved, and
float values are rounded to nine decimal places only for the snapshot digest
to accommodate interpreter-level summation differences. The production
calculation retains full precision.

Career chronology is stored in an additive `career_chronology` table. On opening
an existing database, the watcher seeds each unmigrated career from its maximum
valid game date across snapshots and active or inactive membership rows. Missing
or malformed legacy dates cannot establish a watermark and are left untouched.
Existing historical rows and keys are preserved. If a previous rewind erased all
evidence of a later date, migration cannot reconstruct that date.

Each accepted import updates the watermark, player versions and cohort membership
in one transaction. Older dates are skipped and same-date filter changes remain
valid. New imports require a calendar-valid YYYY-MM-DD game date; a missing or
invalid date triggers an import error without modifying existing records.

## Managed club and loan evidence

The watcher exports `managed-clubs --all` and verifies its single Rangers row
against `clubs --club <uid>`. Each career binds the save-local club UID and,
when present, manager staff UID in the additive `career_club` table in the same
transaction as chronology and memberships. Existing databases bind on the first
accepted import after reconciling their active squad's named club identifiers;
conflicting or absent legacy evidence requires review. The bridge can still read
unmigrated databases, using a single unambiguous legacy club UID if present.

According to fmsave's
[Player model](https://github.com/rhiever/fmsave/blob/main/src/fmsave/models/players.py),
`club_uid` is the club fielding the registered team and `loan_parent_club_uid`
is the club of the contract in effect when `on_loan` is true. The
[CLI](https://github.com/rhiever/fmsave/blob/main/src/fmsave/cli.py)
filters `--managed-club` by current club UID only, so the watcher now reads the
full player export transiently even without F9 targets to retain outgoing loans.
Only the relevant squad and matched targets are persisted. This may increase
the time needed for squad-only refreshes. The watcher logs the transient
world export's elapsed time and size on each successful extraction.

Club-level starting-XI eligibility is confirmed for permanent and incoming
players whose current club is Rangers; outgoing loans are unavailable.
Missing/conflicting evidence is unknown, and must be explicitly resolved before
including a player in a confirmed XI. Injury, suspension, match registration
and tactical suitability are separate and not inferred here. Squad membership
includes owned players away on loan and possible owned players with a matching
parent UID but missing or contradictory loan evidence. These remain unknown
until verified. Native CSV retains the Loan column (blank,
in, out, or unknown); Club remains Rangers for the managed roster, as upstream
does. Dashboard JSON separately retains actual club and loan/availability state.
Existing score formulas and ranking order are retained. The comparison baseline
requires confirmed club-level availability. Familiar, scoreable players with
unknown availability are listed separately per role and excluded from uplift.
Without a confirmed incumbent, uplift and attribute comparisons remain undefined.

fmsave documents the managed-club link as confirmed only for single-human
manager saves, and some club/parent identifiers are unconfirmed fields. The
integration cannot distinguish two separate careers with identical club and
manager identifiers, or verify actual match eligibility from these exports.

## Stable player observations

Native player CSV files may include the optional `Player ID` column. It is an
opaque, nonempty string treated as metadata, and is separate from the observed
`Name`. Blank/missing IDs retain the legacy name/alias grouping. A producer
must namespace IDs if it combines observations from distinct careers or sources.
The Rangers bridge writes a JSON array `["rangers", career, player_key]` using
the existing SQLite key unchanged; native fmsave squad imports use
`["fmsave", save, uid, unique_id, birth_date]`. Names, clubs and cohort membership
are not part of either identity. Use distinct career keys (or native save slugs)
for distinct saves. No database migration is required.

Identified rows are grouped by ID and date; same-date files retain the existing
sorted-file precedence and merge observed attributes. History retains observed
names, clubs, scores and dates, and the latest name is displayed. Duplicate
display names are numbered for presentation only; the table's title attribute
exposes the ID and row selection opens the corresponding history. Where a player
has changed name, the history includes a name column. Name-only config selectors
still work when unique; use `id:<Player ID>` in last_names, signed, released,
recalled or intake_kept to select an exact identity when names are ambiguous.
Private IDs are stripped on public share-leagues exports.

Existing observations are not backfilled or deleted. A legacy name-only history
and an identified history remain separate even when their names match, since
the old file cannot prove identity. Existing aliases apply to legacy names.
The ordinary same-date bridge refresh still replaces its current observation
files. A newly identified history begins with the first identified observation;
old name-only histories remain available separately and cannot be safely joined
automatically. Do not reuse a career/save namespace for a different save.

The numerical parity test retains every original payload digest after checking
and removing only the newly added `player_id` and historical `name` fields from
the three native player tables. It also checks the new full payload digests.
Charts, filters, recruitment and staff data are unchanged in the unambiguous
fixture. The namesake expected failure now passes as a regular regression.
