# What the release establishes

The tests establish deterministic outputs on supplied fixtures, selected financial/technical constraints, and rejection of specified malformed or ineligible inputs. They do not establish profitability, data accuracy, market readiness or suitability for a person.

## Research assumptions

- Equity-specific valuation thresholds, annualization at 252 sessions, and US/Canadian supported-listing focus are deliberate. This edition is not a crypto research engine.
- The 13 investor-labelled lenses are project-authored heuristics, not faithful models of named investors, their current views, or their proprietary methods. The lenses overlap and are not independent votes. Nine positive lenses are not a 69% probability of success.
- Intrinsic-value estimates are simplified inferences. The constant-growth model, assumed discount rate, target gain and cutoffs have no calibrated predictive interpretation. Do not describe its FCF-yield-plus-growth proxy as a realized or validated IRR.
- Price freshness windows are coarse daily-research controls; exchange calendars remain operator-supplied, and timestamp synchronization and independent corporate-action reconciliation are not implemented.
- Fundamental fields, classification, portfolio state, flags, source content hashes and independence remain operator attestations. A well-formed false snapshot can pass. Prompt instructions reduce risk but are not a technical sandbox for the surrounding Bot.
- A single filing source can support multiple chain links; support is not semantically checked. A compromised Bot could falsify every link. Review the actual cited passages.

## Execution and performance

The explicit paper worker maintains a USD-base ledger with native USD/CAD cash, positions, frequency/risk controls, costs, snapshots and idealized fills/exits. The standalone research evaluator produces no orders. No real-money broker, exchange, wallet or signer ships. Optional cloud persistence and observation fetchers are described in CLOUD.md and MARKET_DATA.md.

Stops cannot guarantee a loss ceiling. Same-bar path uncertainty, gap risk, actual liquidity and adjusted/raw-price consistency limit simulation. Entry/exit costs are assumptions, not observed broker fees. New-entry caps include projected concentration and modeled round-trip stop costs; unpredictable gaps can exceed the modeled risk. Existing position weights can drift beyond initial caps as prices move.

No historical performance statistics are published. Backtest/forward evaluation, holdout universes, delistings, look-ahead controls, complete corporate-action coverage, turnover, costs and honest benchmark selection are required before making performance claims.

## Platform and maintenance

The profile/skill/routine pack follows published Grok Bot concepts. A real-account acceptance run has not been performed for this release. Platform versions, permissions, source availability and source licensing can change. Grok Bot is a third-party product with separate access conditions; the free offline demo does not make that platform free.

## Persistent edition additions

The persistent edition provides a USD simulated portfolio, atomic local/cloud commits, sequential session runner, hypothetical fills, exit management, reports and opt-in delivery reservations. The research-only `evaluate` command never opens a position. See CLOUD.md for operational behavior.

The next-session entry model deliberately retains a legacy idealization: recheck research/technicals at the next session close and, only if still qualified, simulate a fill at that same close with configured slippage and fees. This uses information from the closing bar and cannot represent an order executable at that exact observed close. It can bias results. Do not interpret these simulations as an executable backtest or evidence of returns. Realistic execution would require a later executable observation, a separate order model and additional validation.

The ledger supports long-only whole-share instruments on supported US exchanges with USD settlement and TSX/TSXV with CAD settlement. USD is the accounting/risk base; CAD reporting is a view. Explicit conversions model fees and require fresh dated FX and sufficient source cash. Native settlement never auto-converts. Missing required FX or provisional stale rates constrain valuation, new risk and delivery; observed FX/source terms remain attestations. There is no deposit/withdrawal flow after initialization or independent broker reconciliation.

Dividends and return-of-capital receivables, split/symbol transformations, cash/share mergers, spin-offs and confirmed writeoffs require complete, immutable, dated sourced terms. Withholding, basis allocation and cash-in-lieu prices are operator inputs. Same-date ordering must be explicit; unsupported or ambiguous events reject. Split histories must declare `market.history_basis` as `raw` or `split_adjusted`; the worker never guesses. Reorganization children require reviewed post-action history. Action support is not a tax engine or proof of exhaustive coverage. See [ACCOUNTING.md](ACCOUNTING.md).

Operator-configured benchmarks use exact matching dates, source availability, declared return type and currency. Comparison metrics remain unavailable for missing/incompatible data. Every snapshot must explicitly attest `market.distributions_complete`; only whole-period complete coverage permits a total-return comparison. Otherwise coverage is `UNVERIFIED` and all comparison metrics are unavailable with `distribution_coverage_unverified`. Incomplete coverage is not a price-only return: some distributions may already be present. Source attestation is not proof of total-return accuracy or outperformance. See [BENCHMARKS.md](BENCHMARKS.md).

Optional observation refresh cannot prove exhaustive distribution/action coverage. Limits concern new entries; market drift may increase weights. Halts stop new entries, while protective exits continue.

The cloud service role is a trusted worker/admin, not an untrusted end-user token. Database atomicity does not prove financial correctness; it persists the reviewed worker's validated state. API keys must remain server-side. PostgreSQL migration tests emulate Supabase roles but do not test the hosted PostgREST gateway or platform settings. A real Grok Bot/Supabase install remains unverified.
