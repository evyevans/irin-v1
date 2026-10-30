# Architecture

```text
Operator / Grok Bot research
          |
  local JSON snapshot
          |
 atlas.core: structure, timestamps, provenance, recomputed indicators
          |
 engine.aplus: deterministic equity heuristics + hypothetical sizing
          |
 RESEARCH_ONLY result + rule/input hashes + blockers
          |
 local JSON and escaped HTML
```

`engine.indicators`, `engine.aplus`, and `engine.exits` retain the existing project's pure calculation logic. The research boundary is new. Explicit paper/cloud/refresh modules supply the persistent workflow separately, using a fresh generic migration and no historical client state or email-sending adapter. The engine's historical internal vocabulary (DB caps, investor lens names, version references) describes inherited rule provenance; no database is contacted.

`atlas.core` fixes policy caps, derives indicators from supplied history, checks source age/availability, and requires explicit chain-source links. It overrides input claims about precomputed indicators, price classification, evidence counts and risk tier. It still trusts the operator's underlying observations, source identities, financial values and portfolio state. It is not a data authentication service.

`engine.exits.manage` is a separately tested pure exit helper. The paper CLI integrates it for simulated position management; the research-only evaluator does not call it. Its session handling and fill prices are idealized; costs, actual order books, holidays and corporate actions are outside that helper.

The standalone research path has no remote calls or credential reads. The explicit cloud adapter reads only its named installation environment variables; the market adapter contacts documented public vendor endpoints. Running it does not install an agent, create a routine, or grant a platform tool permission.


## Persistent worker path (1.2)

```text
point-in-time snapshots + dated bookkeeping -> validate/actions/FX -> paper transition -> complete new state
                                                       |
                                  compare-and-swap revision / idempotency key
                                                       |
                            local SQLite OR service-only Supabase RPC -> private PostgreSQL store
                                                       |
                            persisted positions / cash / events / valuations -> reports
```

Worker commands are explicit; `evaluate` and `demo` retain their research-only behavior. `paper_demo` exercises persistence with synthetic observations. `storage` and `cloud` provide equivalent revision contracts. `worker` coordinates reads, deterministic transitions and atomic commits. A rejected transition performs no ledger write. `portfolio_report` generates escaped output and conservative delivery reservations. Market refresh is separate and never writes the ledger. Server worker state is trusted and the full snapshot is retained in commit history; this is simpler to audit initially but needs storage planning for long deployments.


`accounting` owns native cash sleeves, source-timed action registries and receivables. `paper` applies those changes before exits and risk evaluation, adjusts explicitly raw split histories, and records valuation and FX attribution per session. `benchmarks` performs pure exact-grid comparisons; reports with incomplete distribution coverage remain unverified. `governance` checks configured operational readiness independently of investment rules. It blocks new entries while protective exits continue. Store hash chains cover retained revisions; worker writes refuse a failed verification.

`research_data` optionally collects bounded SEC/FRED observations or transforms local files. Its heuristic filing flags and derived metrics remain observations for review. `batch` builds peer statistics and correlations from the caller's complete universe, overriding claimed aggregates; it never inherits a private watchlist. Source availability stays attached throughout. These modules do not automatically certify a complete research dossier.
