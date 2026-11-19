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

Two tests deliberately use unittest's expectedFailure marker:

- Loan direction: an incoming loan is exported as outgoing.
- Identity: a newly active namesake changes the native CSV display key and splits
  existing history.

When fixing each issue, remove its marker and keep the regression assertion.
An unexpected success fails the suite, so these markers cannot silently remain
after a fix.
