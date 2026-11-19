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

Three tests deliberately use unittest's expectedFailure marker:

- Chronology: an unchanged later save does not advance the snapshot watermark,
  allowing a subsequent older save to rewind active membership.
- Loan direction: an incoming loan is exported as outgoing.
- Identity: a newly active namesake changes the native CSV display key and splits
  existing history.

When fixing each issue, remove its marker and keep the regression assertion.
An unexpected success fails the suite, so these markers cannot silently remain
after a fix.
