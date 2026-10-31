# Optional daily paper workflow

Enable deliberately after a successful manual cloud/local installation. Configure the owning Bot, permitted universe, source access, exchange calendar, timezone, ledger/store and notification policy privately. Suggested US timing is after the verified end-of-day observations are available, not a presumed fixed latency. No specific recipient or owner is part of this repository.

```text
Run IRIN research for the configured universe and every held instrument, using only permitted sources. Read docs/CLOUD.md and docs/INPUTS.md. Read docs/ACCOUNTING.md, docs/GOVERNANCE.md and docs/COMMITTEE.md for enabled installation features. Prepare a bookkeeping file with sourced FX, conversions/actions, benchmark observations and configured committee reviews; retain unresolved vetoes. Do not infer tax/basis terms or auto-convert cash. Prepare complete, dated snapshots for one closed exchange session. Retain provenance and opposing evidence; never fill missing facts with demo values. Use the actual exchange calendar and corporate-action information. If a required source, mark, calendar or held instrument is missing, report the blocker; do not force the run.

Run the configured `python3 -m atlas paper ... run --as-of <actual UTC evaluation time> <snapshot-files...> [--bookkeeping <dated-bookkeeping.json>]` command. Never print credentials or read unrelated private projects. A paper run changes only this installation's simulated ledger. Never route broker orders, change mode or policy, send email, publish, or clear halts automatically. Interpret an error as a rejected run, not a zero-event success.

If a conflict occurs, reload the committed state before a deliberate retry. Exact already-committed sessions are safe to replay. Replay any missed sessions sequentially with genuine point-in-time inputs; do not backdate fresh research to obtain historical fills. Return only meaningful new signals, simulated fills/exits, halts, failures and required input. Stay quiet on unchanged replay/no material changes. Describe all fills and performance as simulated.
```
