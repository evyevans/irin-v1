# Persistent paper trading and cloud setup

The paper worker uses the same deterministic state transition with either a local SQLite ledger or an installation-owned Supabase store. Each Supabase project represents one trusted operator's installation. This is not a shared multi-tenant SaaS backend. No original customer, portfolio, project reference, approval or email recipient is seeded.

## Local setup

Python 3.11+ and no third-party Python packages are required:

```bash
python3 -m atlas paper --ledger local-data/ledger.db init --capital 25000 --synthetic
python3 -m atlas paper --ledger local-data/ledger.db enable
python3 -m atlas paper --ledger local-data/ledger.db run --as-of 2026-10-23T22:00:00Z examples/synthetic.json
python3 -m atlas paper --ledger local-data/ledger.db status
python3 -m atlas paper --ledger local-data/ledger.db report --week 2026-10-19 --output exports/portfolio
```

Optional initialization flags set the simulation scenario: `--fee-bps`, `--slippage-bps` (defaults 10 each per side), `--max-initial-weight-pct` (at most 5), `--min-cash-pct` (at least 20), and `--max-positions` (at most 7). Limits may tighten the baseline; they cannot loosen it. Costs are scenario assumptions, not an observed broker fee. They are fixed for the initialized ledger; create a separate explicitly selected ledger for another scenario rather than rewriting history.

Initial virtual capital is required; 25000 above is an arbitrary example. Omit `--synthetic` for a real-observation paper ledger. Real-observation mode still handles simulated money only. Synthetic and real observations cannot mix. There is no reset command; an existing ledger cannot be silently reinitialized. Keep local ledgers and generated reports private.

`enable` allows simulated entries; `disable` stops new entries while position risk management continues. `halt` also blocks new entries persistently; `resume` clears that administrative halt, but an outstanding 15% drawdown immediately halts entries again. Neither setting disables protective exit management. No command sends broker orders or real-money transactions.

Each run takes one local snapshot per instrument, all from the same session. Include every held instrument. A new instrument may enter the research universe by supplying its snapshot; held instruments cannot be silently omitted. Use a distinct snapshot file for each ticker. Decisions use the actual simulated portfolio instead of the snapshot's declared balances. Known missing or stale prices reject the whole session before persistence. Repair inputs and retry; no partially updated book is committed.

Runs advance one exchange session at a time. For missed days, replay each day's point-in-time snapshot in order. Do not backdate data fetched today as though it were available on an earlier day. A successful replay of an already committed identical session does nothing; changed input for that session is rejected. Commit conflicts require reloading state and recomputing; do not force an overwrite.

## Install on a NEW Supabase project

1. Create a new empty project in your own account. Pick its region/plan and review costs. Keep its credentials in your server or Grok Bot secret store. This package never provisions a paid project automatically.
2. Read and apply `database/001_cloud_store.sql`, then `database/002_audit_chain.sql`, once, using the SQL editor or your migration workflow. It creates a new `atlas_private` schema and service-only public RPC functions. It fails if that schema already exists, avoiding accidental overwrites. Do not apply it to an existing private deployment.
3. Verify the store and audit RPCs are exposed in your project's Data API settings as needed. Supabase's exposure defaults change; SQL execute grants and API exposure are separate controls. Do not expose the private tables or grant `anon`/`authenticated` access to make an error disappear.
4. Set the environment variables named in `.env.example` privately. The program does not auto-load `.env`; configure the process environment or your platform secret store. There is no default project or fallback URL. Never paste keys into the chat or repository.
5. Use `python3 -m atlas paper --cloud init --capital <your-virtual-capital>` and then `python3 -m atlas paper --cloud status`. Review disabled initial state before running `enable`. Use `--synthetic` only for an explicitly synthetic installation.
6. Run `python3 -m atlas paper --cloud run --as-of <actual-UTC-evaluation-time> <snapshot-files...>`. The owning Bot can prepare snapshots from permitted sources and run this command. Do not add a routine until a one-time run and report are correct.

`ATLAS_SUPABASE_PROJECT_REF` is this installation's 20-character project identifier. `ATLAS_SUPABASE_SECRET_KEY` is a server-only secret key (recommended) or a legacy service-role JWT. New secret keys are sent in `apikey`; only legacy JWTs are additionally sent as Bearer authorization. It grants privileged access to that project; never use it in frontend JavaScript. HTTPS origin is constructed from the validated reference; redirects are refused and raw provider errors are not printed.

## Database permissions and trust

The RPC functions use SECURITY INVOKER, an empty search path and qualified relations. PUBLIC, anon and authenticated have no execute grants. The underlying tables enable RLS and reside in an unexposed private schema. The service role has only the table operations needed for this store, including no delete permission on commit history. SQL tests exercise privilege checks and denial paths.

The service-worker key is a trusted-administrator credential. A holder can submit fabricated state, rewrite balances through that trusted role, or use other provider APIs. The database checks structural essentials and nonnegative cash, and serializes revisioned commits; it does not rerun Python research rules or authenticate the observations. The Python worker validates financial state before commits. Deploy only reviewed worker code and restrict key access. This differs from the legacy design's many database trade triggers and is documented rather than disguised as identical enforcement.

Atomic compare-and-swap commits prevent concurrent lost updates. A request ID reused with different content is rejected; an exact retry returns its prior revision. The commit history retains each committed full state, which can grow substantially over time. Plan storage/retention and backups before long-running operation. There is no unbounded automatic retry loop.

## Daily research and paper routine

Use `ops/routines/daily_paper.md`. The workflow is: prepare current research/market snapshots → validate session and evidence → manage held positions → recheck pending candidates → simulate eligible fills → value portfolio → commit all state atomically → return material changes. The Bot's permitted source tools are responsible for gathering fresh research; the Python runner does not invent fundamental facts or execute remote instructions embedded in retrieved text.

For real paper runs, each snapshot must include either USD with an allowed US exchange or CAD with TSX/TSXV and explicit fundamentals currency, `session_close`, `next_session` from an actual exchange calendar, and `corporate_actions_checked: true`. Calendar/identity/action fields are operator attestations. Unknown calendars or corporate actions must remain blocked. See INPUTS.md.

## Optional weekly report and delivery

Generate a preview using `paper ... report --week <Monday>`. It writes report.html, report.txt, report.json and send_manifest.json. Weekly return is unavailable unless both valuation boundaries and a completed trading week exist. The report shows simulated balances, positions, events, realized PnL and mode; it has no recipient, private signature or investor endorsement.

Dispatch is disabled initially. To deliberately opt in, configure the sending account and recipient in the owning Grok Bot's private routine, review the report, then use `paper ... dispatch-enable`. `dispatch-hold` stops new delivery reservations. A report manifest alone is not authorization to send.

Before sending, the routine must atomically reserve the period with `paper ... reserve-send --week <Monday> --sha256 <HTML-digest>`. If it succeeds, send exactly those reviewed bytes through the specifically authorized connector. Then use `paper ... ack-send --week <Monday> --message-id <provider-id>` to record success privately. A reservation blocks duplicate sends even if a network timeout makes the outcome unknown. Never automatically clear a reservation or resend: reconcile the provider's sent state manually. The program itself has no email-sending adapter.

## Disposable verification

Install PostgreSQL 17+ server tools through a trusted distribution, then:

```bash
PG_BIN=/path/to/postgres/bin bash tools/test_postgres.sh
```

The script creates a random temporary cluster, opens only a temporary Unix socket, initializes fake provider roles, applies the real migration, checks API/table access boundaries and malformed writes, races concurrent writers, runs a full synthetic portfolio round trip, then stops and deletes only its own temporary cluster. No existing database or provider project is touched. On macOS an environment sandbox may require approval for PostgreSQL shared memory.

Verified locally with PostgreSQL 17.6 compiled from checksum-verified official source, using a temporary installation. This verifies actual PostgreSQL behavior, not Supabase's hosted gateway, project settings, HTTP JWT mapping or Grok Bot's connectors. Those final deployment checks remain installation-specific and must be recorded honestly.

Primary platform references: [API keys](https://supabase.com/docs/guides/getting-started/api-keys), [database functions and privileges](https://supabase.com/docs/guides/database/functions), and [Data API exposure changelog](https://supabase.com/changelog?tags=data+apis). Recheck provider settings during each new install.


## Accounting, operational health and audit verification

[ACCOUNTING.md](ACCOUNTING.md) covers explicit FX conversions, CAD settlement, distributions and corporate actions. Use [GOVERNANCE.md](GOVERNANCE.md) for optional time-limited health checks, durable review deadlines and notice reconciliation. An operational HOLD blocks entries and report reservation while protective exits continue. These checks are attestations supplied by the installation, not independent monitors.

Every worker write verifies retained audit integrity first. `paper ... audit-verify` returns the revision and head hash; use `--expected-head HASH` against a previously saved private checkpoint to detect truncation to an earlier valid prefix. A database administrator can recompute the entire chain; a hash chain is not an external signature. PostgreSQL migration 002 backfills all retained states from migration 001. Legacy SQLite stores had no historical payloads: upgrade records a clearly flagged current-state checkpoint (`legacy_prefix_unverifiable: true`), and makes no claim about earlier states. Fresh SQLite stores retain every state from revision one. Local and PostgreSQL hashes use different canonical encodings; compare checkpoints only within the same installation/store.

Migration 002 uses PostgreSQL's built-in [SHA-256 binary functions](https://www.postgresql.org/docs/17/functions-binarystring.html), without third-party extensions. Apply it once to an existing public v1.1 database before using the v1.2 cloud worker. Back up and verify that public installation first; never migrate a separate private deployment with this public schema.


New paper decisions require the evaluation timestamp's UTC date to equal the valued US/Canadian session date. This conservative cutoff prevents later-day evidence from being replayed into an earlier decision or next-open exit. After-midnight processing must wait for a supported workflow change; never backdate newly acquired evidence. Historical replay requires genuine point-in-time inputs and their honest historical evaluation cutoff. Exact committed-session retries do not create another decision.
