# Local snapshot contract

The executable starting example is `examples/synthetic.json`. All its data is invented. Do not use its values, favorable assumptions or fake URLs as evidence for a real issuer.

## Envelope

| Field | Contract |
|---|---|
| `schema_version` | Integer 1 |
| `synthetic` | Explicit boolean; real records require false |
| `history` | 1–10000 strictly ascending unique daily rows: `d` ISO date, positive finite `o/h/l/c/ac`, nonnegative `v`; OHLC bounds consistent |
| `context` | Equity facts and declared portfolio state, described below |
| `sources` | 0–200 source records with unique IDs |
| `chain_sources` | Map all four chain steps to nonempty arrays of eligible filing source IDs |

Daily history is oldest first. `c` is unadjusted close and `ac` is a consistently adjusted close in the same currency. The engine uses raw-close moving averages and ATR, and adjusted-close returns. Splits and bad adjustment factors can therefore distort signals; validate corporate actions outside this program. Weekday-only synthetic dates are not an exchange calendar. Short history yields failed technical checks rather than invented indicators.

## Source records

Each source has `id`, `role` (`price`, `filing` or `bottleneck`), `publisher`, `upstream`, HTTPS `url`, `observed_at`, `available_at`, `label`, and `content_sha256` (64 lowercase hexadecimal characters). URLs may not contain credentials, query strings or fragments. Timestamps need an explicit timezone. Source observation must be no later than availability, which must be no later than evaluation.

- Synthetic records use `label: synthetic`, reserved `.invalid` URLs and dummy hashes.
- Real records use `label: operator_attested`, genuine content hashes and real URLs. The program does not retrieve the URL or recompute the source-content hash. Forged attestations can still pass.
- At least two price records need distinct declared publishers **and** upstreams, observation dates matching the final history date, and observation ages no more than 96 hours.
- At least one filing observation must be no older than 395 days. Use publication/filing time as observation and actual first accessibility as availability, not the accounting period end.
- At least two bottleneck records need independent declared publishers/upstreams and observation ages no more than 730 days.
- Real price records also require numeric `value`; each must agree with the final history close within 0.5%. Actual upstream independence still needs analyst verification.
- Every supplied source is checked; an invalid/stale extra source blocks qualification too. Remove or refresh ineligible evidence deliberately.

These are configurable-in-code conservative daily research windows, not claims that a 95-hour-old price is current enough to trade. They do not implement exchange calendars or infer source independence from domains.

## Context

Required objects: `row`, `fund`, `portfolio`, `flags`, `val_stats`, `regime`, `fe_counts`, `chain`; required strings: `ticker`, `name`; required `score`: 0–100.

- `row`: `layer`, `subsector`, `focus_segment`, boolean `us_listed`; business model and junior/stage fields when relevant. The model is specific to equities. Unknown segments cannot receive A+.
- `fund`: nullable observed numeric fields, e.g. market cap, free cash flow, debt/equity, interest coverage, net income, operating cash flow, sales, earnings ratios, growth rates, stock compensation and reinvestment ratios. Ratios/growth are decimals except fields explicitly ending `_pct`. `available` and `ocf_all_positive_10y` are booleans; `sbc_to_fcf_3y` is a numeric array. Missing facts stay absent/null, and may block qualification. No synthetic substitution is allowed. Numeric inputs have an absolute magnitude limit of 10^24 to prevent overflow. Valuation multiples, leverage, current ratio, market cap, revenue, payout/reinvestment ratios, runway and streak counts must be nonnegative; undefined or loss-denominator multiples should be null, never a negative number interpreted as a cheap valuation. Earnings and cash flows may be negative. Boolean facts must be actual booleans; stock-compensation/free-cash-flow ratios require three nonnegative annual values.
- `flags`: status (`scanned` only after a documented filing review) and an array `flags`; e.g. `going_concern`, `material_weakness`, `restatement`, `covenant_breach`. An empty array asserts a performed scan found none; it is not a default for an unreviewed filing.
- `portfolio`: positive `equity_usd`, `drawdown_pct` and `invested_pct` (0–100), nonnegative integer `open_positions` and `trades_created`, `layer_weight_pct` object with values 0–100; optional boolean `paused_until_month_end`. State is declared, not reconciled by this program.
- `regime`: explicit booleans `known`, `adverse`; unknown conditions are not silently favorable for applicable sectors.
- `val_stats`: `median_ev_ebitda` object (for utilities), optional numeric `ev_ebitda_p90`, `vol260_median`. Real values need a dated comparable universe.
- `fe_counts.dc_quant`: nonnegative integer count of quantified demand references; `direct_material`: explicit boolean. These are analyst attestations.
- `chain`: nonempty descriptions for `ai_demand`, `customer_contract`, `revenue_backlog`, `margin_cash_flow`. `chain_sources` links each to eligible filings. Existence of a link is not proof the filing actually supports the description.
- Optional `spread_pct`: 0–100; `max_corr`: -1 to 1. Missing correlation blocks research qualification when positions are already open. Under-US$10 stocks need a verified-by-analyst spread and extra balance-sheet/earnings checks.

The sample shows one supported grid-equipment case. Financed developers require explicit `context.project_evidence.financing` and `.permitting`, each with a `credible` boolean and nonempty `source_ids` linking to eligible current filing records. Caller row/database approval flags are ignored. The analyst must review complete funding and permit terms; links and credibility flags remain attestations and do not guarantee project viability. REIT valuation is also not implemented in the engine. Supply no guessed valuation proxies.

## Output

`status` is RULES_PASS or NO_TRADE; `grade` is the inherited engine's A+/B/Reject heuristic. A favorable engine grade may still have NO_TRADE when a public provenance gate fails. `execution_enabled` is always false. `hypothetical_sizing` is an illustration, not an order or executable payload.

The CLI exits 0 when a research result was produced (including NO_TRADE), and 2 for malformed input or I/O failure. A successful process exit does not mean a thesis passed. JSON and HTML are saved locally in the selected output directory. They may contain private input and should be reviewed before sharing.


## Real-observation paper metadata

The research-only evaluator still accepts the basic envelope. The persistent paper worker additionally requires a `market` object: `currency` is USD with NYSE/NASDAQ/NYSE_AMERICAN or CAD with TSX/TSXV; CAD also needs explicit `fundamentals_currency` USD/CAD; `session_close` is an explicit timezone timestamp no later than evaluation; `next_session` is the next actual exchange session date; `corporate_actions_checked` is an explicit true attestation. Price observations must be dated after the declared session close. A qualified operator must supply this metadata from an actual market calendar and corporate-action review. Unknown, suspended or unresolved-action instruments are not eligible.

For the next run, provide the expected next session with exactly one new daily row after the prior committed session, and include every held ticker. Use an explicit `--bookkeeping` file for dated FX, conversions, distributions, corporate actions, benchmark registries and optional user-defined committees. See [ACCOUNTING.md](ACCOUNTING.md) and [COMMITTEE.md](COMMITTEE.md). Unknown terms block processing. `market.distributions_complete: true` is an explicit coverage attestation; incomplete coverage keeps comparisons unverified. The simulator does not infer taxes or establish a validated total-return strategy.
