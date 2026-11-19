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
the time needed for squad-only refreshes.

Club-level starting-XI eligibility is confirmed for permanent and incoming
players whose current club is Rangers; outgoing loans are unavailable.
Missing/conflicting evidence is unknown, and must be explicitly resolved before
including a player in a confirmed XI. Injury, suspension, match registration
and tactical suitability are separate and not inferred here. Squad membership
includes owned players away on loan. Native CSV retains the Loan column (blank,
in, out, or unknown); Club remains Rangers for the managed roster, as upstream
does. Dashboard JSON separately retains actual club and loan/availability state.
Existing score formulas and ranking order are retained; the comparison baseline
excludes confirmed outgoing loans and remains a positional score comparison,
not an XI selection.

fmsave documents the managed-club link as confirmed only for single-human
manager saves, and some club/parent identifiers are unconfirmed fields. The
integration cannot distinguish two separate careers with identical club and
manager identifiers, or verify actual match eligibility from these exports.

One test deliberately uses unittest's expectedFailure marker:

- Identity: a newly active namesake changes the native CSV display key and splits
  existing history.

When fixing each issue, remove its marker and keep the regression assertion.
An unexpected success fails the suite, so these markers cannot silently remain
after a fix.
