# USD/CAD paper accounting

Version 1.2.0 keeps portfolio equity, risk, position cost basis and realized PnL in USD. It also holds native USD and CAD cash. CAD reporting converts the USD equity view; it does not change the ledger base currency or move cash. All money and fills are simulated.

## Supply bookkeeping explicitly

After initializing and deliberately enabling a ledger (see [CLOUD.md](CLOUD.md)), pass a local JSON object to the daily worker:

```bash
python3 -m atlas paper run local-data/snapshot.json --as-of 2026-10-30T22:00:00Z --bookkeeping local-data/bookkeeping.json
python3 -m atlas paper report --week 2026-10-26 --as-of 2026-11-02T22:00:00Z --currency CAD --output exports/portfolio
```

The object may contain `fx`, `conversions`, `actions` and `benchmarks`. An omitted conversion/action list means no new requests. Previously registered future actions remain stored. Register actions by their effective session; the worker refuses late terms that would rewrite a committed session. All held instruments, including newly created action instruments, need complete eligible daily snapshots. Session input hashes include bookkeeping; conflicting same-session replays are rejected.

A synthetic example of FX and an explicit cash conversion:

```json
{
  "fx": {
    "rate": "1.35",
    "observed_at": "2026-10-30T21:00:00Z",
    "available_at": "2026-10-30T21:01:00Z",
    "source": "https://example.invalid/synthetic-fx",
    "synthetic": true
  },
  "conversions": [
    {"id": "synthetic-conversion-1", "from_currency": "USD", "amount": "1000", "fee_bps": "10"}
  ],
  "actions": [],
  "benchmarks": []
}
```

These are fictional terms, not an observation or recommendation. Synthetic FX must match a synthetic ledger; use actual reviewed evidence for real inputs.

## FX and native settlement

`fx.rate` is positive **CAD per USD**. USD converts to CAD by multiplication and CAD converts to USD by division. FX requires an HTTPS source, observed/available timestamps no later than `as_of`, and matching synthetic status. An observation cannot move backward or change terms at an existing observation timestamp. Rates older than 96 hours are `PROVISIONAL_STALE`; absent required FX is `MISSING`. Fresh FX is required for conversions and new foreign-currency risk; stale/missing FX blocks report delivery eligibility.

Each conversion needs a unique `id`, `from_currency` (`USD` or `CAD`), positive `amount` and optional `fee_bps` (default zero, allowed range 0–500). The other currency is the target. Proceeds are source amount times the source-to-target rate times `(1 - fee_bps / 10000)`. Fees reduce proceeds and are recorded in USD. Identical ID/terms replay once; conflicting terms reject. Cash cannot become negative. A CAD purchase needs CAD cash; no automatic conversion covers a shortage.

Supported paper listings use USD settlement on supported US exchanges or CAD settlement on TSX/TSXV. CAD snapshots declare `market.currency: "CAD"` and explicit `market.fundamentals_currency` (`USD` or `CAD`). The research adapter converts CAD quote/eligible monetary fundamental fields into USD for checks; native prices remain the settlement and position-management basis. This is not a general multicurrency security or multicurrency financial-statement system.

Snapshots preserve cash sleeves, receivables, FX status and attribution. Attribution includes CAD cash basis/unrealized FX, realized cash FX, cash/receivable revaluation and a position FX component. These are inspectable accounting components, not an audited return decomposition or tax report.

## Immutable action terms and entitlements

Every action requires `id`, `kind`, `ticker`, `effective_date`, `available_at` and HTTPS `source`. Terms are hashed and stored; the same ID cannot acquire different terms. Availability must precede the run cutoff. Same-ticker/same-date actions require explicit unique integer `sequence` values. No semantic source verification occurs. The operator supplies complete primary-source terms and resolves ambiguities before running.

| Kind | Required economic terms and behavior |
|---|---|
| `cash_dividend` | `amount_per_share`, `currency`, `pay_date`; optional `withholding_rate` (default zero). Shares entered before effective date earn gross/net receivables; net cash settles on/after pay date. |
| `return_of_capital` | Same distribution terms; reduces USD position basis by gross USD value, floored at zero; records the above-basis excess as simulated realized gain. |
| `split` | Positive `ratio` (new shares per old share). Shares scale; entry/stop/highest prices divide by ratio. |
| `symbol_change` | `new_ticker`; moves the position, rejecting an already-held target. |
| `cash_merger` | Explicit `cash_per_share`, optional settlement `currency`; exits the position and realizes proceeds less USD basis. |
| `share_merger` | `new_ticker`, positive `ratio`, `stock_basis_fraction`, `new_reference_price`, `new_stop`; optional `new_currency` and `cash_per_share`. Creates the replacement instrument and removes the predecessor. |
| `spin_off` | Same child instrument/basis/ratio terms as share merger; retains parent with remaining basis. |
| `writeoff` | `confirmed_worthless: true`; cash consideration must be zero. Removes position at a loss of remaining basis. |

Fractional share entitlements settle as cash using explicit positive `cash_in_lieu_price`; missing terms reject. Whole-share positions remain. Reorganizations reject already-held child targets because lot consolidation needs separate resolution. Pending predecessor signals are cancelled by relevant transformations. Unsupported action kinds reject rather than inventing treatment.

Withholding, tax characterization, basis allocations, reference prices and stops are operator inputs. Defaults are not legal/tax determinations. Above-basis excess is recorded as generic simulated realized gain; jurisdiction-specific tax characterization is not inferred. No tax filing, treaty eligibility, broker reconciliation, short positions or general lot accounting is provided.

## Price history around actions

For a ticker with applicable stored splits, `market.history_basis` is required:

- `raw`: pre-effective OHLC/adjusted-close fields are supplied unadjusted. The worker divides prices before each effective date by its split ratio and multiplies prior volume by that ratio; successive splits compound.
- `split_adjusted`: the supplied series is already consistently adjusted for those splits, and the worker does not apply the split again.

The worker never guesses a basis. Declare it accurately and keep source price observations consistent with the normalized current quote. This contract covers split normalization, not a claim that vendor adjusted-close series correctly accounts for every distribution. Merger/spin-off children require operator-reviewed post-action history; predecessor history is not automatically repurposed as child history.

## Benchmarks and distribution coverage

Supply `market.distributions_complete` as a boolean on every snapshot. It attests that relevant distribution/action coverage has been reviewed; source presence alone cannot prove completeness. A report compares the entire relevant portfolio session grid. Only a period whose snapshots all attest completeness is treated as `TOTAL_RETURN`. Otherwise ledger coverage is `UNVERIFIED`: the ledger may already include some distributions and must not be relabelled price-only. All comparison metrics remain unavailable with `distribution_coverage_unverified`.

Use `bookkeeping.benchmarks` for an operator-configured registry. [BENCHMARKS.md](BENCHMARKS.md) defines direct levels, initial fixed-weight buy-and-hold baskets, source/methodology metadata, availability, FX and exact-date matching. Missing dates/FX, future availability, insufficient history or a return-type mismatch remain explicit unavailable reasons. No benchmark instruments, returns or superiority are supplied or claimed by default.

The independent pure benchmark function also accepts an explicit `PRICE_RETURN` declaration for genuinely price-only input series. That option does not make an incomplete paper ledger a price-return series. Benchmark metrics and source attestations do not establish investment performance.


New paper decisions require the evaluation timestamp's UTC date to equal the valued US/Canadian session date. This conservative cutoff prevents later-day evidence from being replayed into an earlier decision or next-open exit. After-midnight processing must wait for a supported workflow change; never backdate newly acquired evidence. Historical replay requires genuine point-in-time inputs and their honest historical evaluation cutoff. Exact committed-session retries do not create another decision.
