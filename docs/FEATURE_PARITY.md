# Public workflow map

IRIN implements the research, committee, operational-governance,
accounting, reporting and persistent-paper mechanisms in a fresh public package.
Mechanism parity means the source provides the corresponding calculations,
state transitions and fail-closed controls described below. It does not mean
copying a private installation's identities, named-person registry, universe,
holdings, credentials, historical approvals or deployment records. Those are
intentionally replaced with explicit installation-owned configuration and inputs.
The original private folder remains outside the release.

| Capability | Public implementation | Verification / limit |
|---|---|---|
| Grok Bot profile, skill, bootstrap | Generic user-owned role, source contracts and setup | Source pack provided; real platform acceptance not performed |
| Cloud database | Fresh private PostgreSQL store plus service-only Supabase invoker RPCs | Fresh PostgreSQL migration/privilege tests; hosted gateway not tested |
| Credentials/project identity | Required per-install environment settings, no default project | Validated project format, fixed HTTPS origin, redirect refusal |
| Persistent portfolio | USD-base equity, native USD/CAD cash, long-only positions, pending entries, events, daily valuations | Local and real PostgreSQL full-state roundtrip tested |
| Daily operation | Explicit worker command, validated snapshots, atomic complete-book update | Restart/replay/conflict tests; operator supplies real calendar/source evidence |
| Entry timing | Prior-session signal, next-session close requalification and idealized close fill | Explicitly biased/idealized; not an executable backtest |
| Exit management | Gap/stop, trend/time/thesis hooks from retained pure engine, stop tightening | Protective exits continue while new entries halted; gaps can exceed planned risk |
| Risk | Actual portfolio state, initial cost cap, cash floor, projected layer/subsector limits, max positions, frequency, drawdown | Tested concentration/cost regressions; worker/admin remains trusted |
| Costs | Configured entry/exit fee and slippage assumptions | Modeled round-trip risk included; no actual market-depth execution model |
| Research checks | Retained deterministic equity/lens/valuation engine plus public provenance boundary | Input validation and engine regressions; inputs remain attestations, without endorsements or calibrated probabilities |
| Batch research orchestration | User-supplied manifest; whole-universe EV/EBITDA percentile, utility/IPP and segment medians, volatility median, held-position correlations and actual snapshot evaluation | `atlas/batch.py`, `tests/test_batch.py`; sample floors, matched return intervals, all-held comparison coverage, explicit cutoff and source eligibility; no inherited private universe. See [BATCH.md](BATCH.md) |
| Decisive committee | User-owned weighted registry, fixed score denominator, confidence-qualified dissent, multiplicative sizing, timing policy, narrow evidenced veto triggers and expiry/cure lifecycle; exactly one action state | `atlas/committee.py`, committee unit/integration tests; missing required or expired unresolved review blocks opening, committed veto assertions cannot vanish, negative holding reviews queue next-session exits. No seeded named-person registry. See [COMMITTEE.md](COMMITTEE.md) |
| Market data | Optional Yahoo/Nasdaq public observation fetcher and cross-check | Parser tests; vendor availability/terms not guaranteed; independence stays unverified |
| Fundamentals acquisition and derivation | Optional bounded SEC companyfacts fetch or supplied local facts; annual filing selection by cutoff, currency-safe metric joins, aligned multiyear calculations and field provenance | `atlas/research_data.py`, `tests/test_research_data.py`; missing facts remain unavailable, debt basis explicit; issuer-specific/custom-tag semantics need review. See [RESEARCH_DATA.md](RESEARCH_DATA.md) |
| Filing risk scans | Optional bounded canonical SEC filing fetch or local filing text; phrase counts, text digest and dated source evidence | Deterministic heuristic scanner tested; hits can be negated, historical or irrelevant, and absence proves nothing; no semantic certification |
| Macro regime | Optional current FRED observations or supplied local series; dated real-yield/industrial-production rule with coverage/freshness gates | Regime and acquisition-boundary tests; unknown data is adverse; current downloads are not verified historical vintages |
| Operational readiness and recovery | Optional operator-defined time-limited health checks, durable due reviews, notice outbox/receipts, deterministic HOLD and recovery assessment | `atlas/governance.py`, governance unit/integration tests; stale/failed/missing prerequisites block new entries and report reservation while protective exits continue. Does not run external probes or silently clear manual halts. See [GOVERNANCE.md](GOVERNANCE.md) |
| Reports | Escaped HTML/text/JSON, USD/CAD views, cash/receivables/FX attribution, realized PnL and conditional weekly return | Missing/partial return unavailable; synthetic labels prominent |
| Delivery | Opt-in Bot connector routine, hold, atomic period reservation and acknowledgement | No send adapter; uncertain outcomes block resend and need reconciliation |
| FX/currency | USD base, native USD/CAD sleeves and settlement, dated valuation, explicit conversions with fees, CAD report view, FX attribution | No implicit conversion; source/rate attestations and fresh-FX controls; no broker reconciliation |
| Corporate actions and distributions | Immutable sourced/timed dividends and receivables, splits, symbol changes, cash/share mergers, spin-offs, return of capital and confirmed writeoffs | Operator withholding/basis/cash-in-lieu inputs; explicit split-history basis and reviewed child history; ambiguous/unsupported cases reject; no tax certification |
| Benchmark/scorecard | Operator registries/direct levels or fixed initial-weight baskets; local/FX/reporting returns, relative return, volatility, drawdown and downside capture | Exact sessions, availability, currency and return type checked; unverified distribution coverage blocks metrics; no default instruments or validated performance |
| Retained audit history and integrity | Revision/request IDs, retained full-state payloads and chained hashes in both SQLite and PostgreSQL; worker verifies integrity before writes; optional independent expected-head comparison | `atlas/storage.py`, `database/002_audit_chain.sql`, local tamper tests and disposable PostgreSQL checks. Old SQLite history is explicitly unverifiable before its upgrade checkpoint; a trusted administrator can recompute chains. No external signature or automatic backup. See [CLOUD.md](CLOUD.md) |
| Public packaging | Fresh identity, MIT code, explicit manifest/ZIP, privacy and secret scans | Parent private folder is not cleared for publication |

The session state machine is in `atlas/paper.py`, accounting in
`atlas/accounting.py`, comparisons in `atlas/benchmarks.py`, reports in
`atlas/portfolio_report.py`, and explicit worker operations in `atlas/worker.py`.
Research acquisition, batch evaluation, committee lifecycle and operational
governance have their own modules and tests identified above. See
[ACCOUNTING.md](ACCOUNTING.md) for settlement and corporate-action assumptions,
and [VALIDATION.md](VALIDATION.md) for the executed release checks.

The public implementation supplies these mechanisms using generic configuration;
it intentionally does not reproduce a legacy database's exact table layout,
private trigger names, named-investor allocations, checklist labels or customer
data. The retained pure rules and new public state controls must be evaluated
against each installation's chosen policy rather than assuming historical
settings were imported.

Source tests, synthetic simulations and a disposable PostgreSQL installation
provide evidence for implemented behavior. They do not establish hosted Grok
Bot routine import, live Supabase Data API/credential mapping, vendor access,
actual connector delivery or acceptance on a real account. Those deployment
checks remain installation-specific; they are not missing algorithmic
implementations, independent source verification or investment-performance
evidence. Python runtime and hosted-CI limits are recorded in the validation
record. The generic mechanisms do not enable broker or real-money execution.
