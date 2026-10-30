# Contributing

Run `python3 -m unittest discover -s tests -v` and `python3 tools/release_check.py` before proposing a change. Use synthetic fixtures for reproducible failures. Include expected behavior, actual output, Python version and the command used. Never include credentials, private research or recipients in issues, screenshots or logs.

Good first contributions: clearer missing-evidence messages; stronger malformed-input cases; documented source adapters with redistribution rights; exchange-calendar/corporate-action handling; and a recorded Grok Bot acceptance run. Read docs/CLOUD.md before changing the network clients, cloud permissions or persistent state machine; these are separate trust boundaries.

Keep calculation changes small and explain affected constraints. A threshold change needs its rationale and tests. Name lenses descriptively in user-facing explanations. Do not add imagined investor endorsements, invented benchmark results or unsupported return claims.

Contributions are under MIT. Confirm you have the right to contribute copied material and preserve third-party notices. External data, logos, screenshots and publications do not inherit the repository's code licence.

For SQL changes, run `PG_BIN=/path/to/postgres/bin bash tools/test_postgres.sh` on a disposable local cluster. Never test migrations on an existing operator project. Add a meaningful behavioral regression for ledger/permissions defects.
