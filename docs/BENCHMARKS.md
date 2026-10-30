# Operator-configured benchmarks

`atlas.benchmarks.evaluate_benchmarks` is a pure Python 3.11+ function. It reads supplied portfolio equity and benchmark index levels, performs no network or filesystem access, and returns results in registry order. There are no selected instruments, built-in market series, recommended weights, or performance claims.

```python
from atlas.benchmarks import evaluate_benchmarks

results = evaluate_benchmarks(
    portfolio,
    registry,
    as_of="2026-10-30T22:00:00Z",
    report_currency="USD",                 # USD or CAD
    portfolio_return_type="TOTAL_RETURN",  # or PRICE_RETURN
    periods_per_year=252,
)
```

## Accepted input

`portfolio` is a list of objects with required `session` and `equity` fields. Equity is always in USD. Include `fx_usdcad` on every row when reporting in CAD: it means CAD per USD, so USD equity is multiplied by this rate. Existing ledger snapshot fields may accompany these fields and are ignored.

`registry` is a list of objects. Every entry requires:

| Field | Contract |
|---|---|
| `id` | Nonempty text, unique within the registry |
| `category` | Nonempty operator label; supported examples are `broad_equity`, `global_equity`, and `thematic`; custom labels are accepted |
| `currency` | `USD` or `CAD`, the currency of all supplied levels |
| `return_type` | Explicit `TOTAL_RETURN` or `PRICE_RETURN` |
| `methodology` | Nonempty text describing level construction, distributions, adjustment, and costs |
| `source` | Nonempty text or a nonempty object whose keys and values are nonempty strings, such as `{"name": "Synthetic fixture", "url": "https://example.invalid/index"}` |
| `observations` or `components` | Exactly one construction form, described below |

For a direct series, `observations` is a list of objects with `session`, positive `value`, and timezone-aware ISO `available_at`. `value` is a price/index level in the declared currency; it is not a period return. Include positive `fx_usdcad` at every matched session whenever benchmark and reporting currencies differ. USD levels convert to CAD by multiplying; CAD levels convert to USD by dividing. An empty observations list is valid but unavailable for a nonempty portfolio.

All histories must have unique, strictly increasing ISO `YYYY-MM-DD` sessions. The function validates every supplied row, including rows outside the portfolio window. Numeric values accept decimal strings, `Decimal`, integers, and finite floats. Decimal strings avoid binary float input rounding. Equity, index levels, component weights, and any supplied FX must be finite and strictly positive; booleans are rejected. Extremely large arithmetic outside the supported Decimal exponent range raises `ValueError`.

`as_of` and each `available_at` must be ISO timestamps containing `T` and an explicit timezone (`Z` or an offset). Seconds may be omitted. Timestamps are normalized to UTC. Sessions are date labels compared against the UTC date of the cutoff; portfolio sessions after that date are rejected. Observation availability cannot precede its session's UTC date. `available_at == as_of` is eligible.

No schema claim authenticates a source or proves a total-return series reinvested distributions correctly. Supply actual total-return index levels for `TOTAL_RETURN`; relabelling a price series does not add dividends. Choose and retain the comparison category, methodology, costs, currency, and return-type declaration before interpreting results. Changing the configured registry can change the comparison.

## Synthetic direct-series example

This example contains fictional numbers and generic identifiers only:

```python
portfolio = [
    {"session": "2026-10-26", "equity": "100", "fx_usdcad": "1.25"},
    {"session": "2026-10-27", "equity": "95", "fx_usdcad": "1.25"},
    {"session": "2026-10-28", "equity": "104.5", "fx_usdcad": "1.25"},
]
registry = [{
    "id": "synthetic-broad",
    "category": "broad_equity",
    "currency": "USD",
    "return_type": "TOTAL_RETURN",
    "methodology": "Fictional distribution-reinvesting index; no costs",
    "source": {"name": "Synthetic example", "url": "https://example.invalid/index"},
    "observations": [
        {"session": "2026-10-26", "value": "100", "fx_usdcad": "1.25", "available_at": "2026-10-26T21:00:00Z"},
        {"session": "2026-10-27", "value": "90", "fx_usdcad": "1.25", "available_at": "2026-10-27T21:00:00Z"},
        {"session": "2026-10-28", "value": "99", "fx_usdcad": "1.25", "available_at": "2026-10-28T21:00:00Z"},
    ],
}]
```

In USD this produces benchmark return -1%, portfolio return +4.5%, arithmetic relative return +5.5 percentage points, maximum drawdown 10%, annualized sample volatility about 224.4994432064%, and downside capture 50%. The unrealistic volatility follows directly from two synthetic daily periods of -10% and +10%; it says nothing about an actual investment.

Add separate entries with `global_equity` or `thematic` labels and operator-supplied histories to cover those categories. The evaluator does not choose a primary comparison or search for a favorable period.

## Optional fixed-weight buy-and-hold baskets

Replace `observations` with a nonempty `components` list. Each component requires a unique nonempty `id`, a positive `weight`, and an `observations` history using the direct observation schema. Weights must sum **exactly to 1**. All components inherit the entry's currency and return type; an optional component declaration must equal the parent declaration. Mixed-currency and mixed-return-type baskets require a separately constructed, explicitly documented upstream series.

For example, replacing the direct observations above with the following creates a fictional 50/50 basket:

```python
registry[0].pop("observations")
registry[0]["methodology"] = "Equal initial allocations; fixed units; no rebalancing"
registry[0]["components"] = [
    {
        "id": "synthetic-component-a", "weight": "0.5",
        "observations": [
            {"session": "2026-10-26", "value": "100", "available_at": "2026-10-26T21:00:00Z"},
            {"session": "2026-10-27", "value": "200", "available_at": "2026-10-27T21:00:00Z"},
            {"session": "2026-10-28", "value": "100", "available_at": "2026-10-28T21:00:00Z"},
        ],
    },
    {
        "id": "synthetic-component-b", "weight": "0.5",
        "observations": [
            {"session": "2026-10-26", "value": "200", "available_at": "2026-10-26T21:00:00Z"},
            {"session": "2026-10-27", "value": "200", "available_at": "2026-10-27T21:00:00Z"},
            {"session": "2026-10-28", "value": "400", "available_at": "2026-10-28T21:00:00Z"},
        ],
    },
]
```

The initial portfolio session is the normalization date. Basket levels are `sum(weight_i * level_i,t / level_i,0)`: this example produces levels 1, 1.5, 1.5 and a 50% local return. Units remain fixed; weights drift with the levels. There is no daily rebalancing, fee, or distribution accounting beyond what each supplied component series already contains.

Every component needs every portfolio date, including the first. Missing normalization data prevents the entire basket comparison. Each composite observation becomes available only after its current levels **and its normalization levels** are available. When conversion is required, every component must supply the same session's FX. Missing component FX makes conversion unavailable; conflicting provided component FX raises `ValueError`.

## Exact-date and point-in-time comparison

The portfolio session grid defines the entire window. A benchmark must provide an eligible observation on **every** portfolio session. The function never silently intersects dates, forward-fills levels, interpolates FX, or removes missing periods. Unmatched earlier/later benchmark rows do not enter the calculations. Unmatched future observations may be supplied but cannot affect historical metrics.

A return-type mismatch makes the whole comparison unavailable. A caller can explicitly compare matching `PRICE_RETURN` series by setting both declarations accordingly. The default portfolio declaration is `TOTAL_RETURN`.

Each result retains `id`, `category`, `currency`, `return_type`, `methodology`, and an independent copy of `source`. It also includes:

- `status`: `available` or `unavailable`.
- `construction`: `OBSERVATIONS` or `FIXED_WEIGHT_BUY_AND_HOLD`; baskets additionally include component IDs and weight strings.
- `report_currency`, `portfolio_return_type`, normalized UTC `as_of`, and the exact requested `sessions`.
- `reasons`, `missing_sessions`, and `unavailable_sessions` for blocked comparisons.
- Metric fields listed below, `metric_reasons`, and integer `downside_periods`.

All metrics use percentage units and serialize as Decimal strings, with `None` for unavailable values. A whole-comparison failure sets **all** metrics to `None`. Reasons are machine-readable strings: `insufficient_history`, `return_type_mismatch`, `missing_sessions`, `observations_not_yet_available`, `missing_benchmark_fx`, and `missing_portfolio_fx`. Missing dates and unpublished matched dates are listed separately. An empty portfolio or fewer than two equity observations yields `insufficient_history`.

A comparison can be `available` while an individual metric is unavailable: two levels provide one return period but cannot provide sample volatility; no negative benchmark periods cannot provide downside capture. These cases appear in `metric_reasons` with `insufficient_periods` or `no_negative_benchmark_periods`, respectively. They never become a fabricated zero.

Malformed inputs raise `ValueError` before returning results. One malformed registry entry rejects the call; one well-formed but unavailable entry does not block other valid entries. An empty registry returns an empty result list after validating the portfolio and options.

## Metric definitions

Let `L_t` be local benchmark levels, `F_t` the benchmark conversion multiplier (1 for matching currencies, `fx_usdcad` for USD to CAD, its inverse for CAD to USD), and `B_t = L_t * F_t`. Let `P_t` be USD portfolio equity converted to the report currency at each portfolio row's FX. All calculations use a local 40-digit Decimal context independent of caller precision; square root is Decimal arithmetic.

| Output | Formula |
|---|---|
| `local_return_pct` | `100 * (L_last / L_first - 1)` |
| `fx_return_pct` | `100 * (F_last / F_first - 1)` |
| `reporting_return_pct` | `100 * (B_last / B_first - 1)`; FX and local returns compound multiplicatively |
| `portfolio_return_pct` | `100 * (P_last / P_first - 1)` |
| `relative_return_pct` | `portfolio_return_pct - reporting_return_pct`, in percentage points |
| `annualized_volatility_pct` | `100 * sample_stdev(B_t / B_t-1 - 1) * sqrt(periods_per_year)`; at least two periods required |
| `max_drawdown_pct` | `100 * max(1 - B_t / max(B_0 ... B_t))`; positive loss magnitude |
| `downside_capture_pct` | `100 * mean(portfolio_period_return for benchmark_period_return < 0) / mean(benchmark_period_return for the same periods)` |

Only benchmark-negative periods in the **reporting currency** count toward `downside_periods`. Portfolio gains during benchmark declines can produce negative capture. A flat benchmark has zero return, volatility, and drawdown where enough periods exist, but unavailable downside capture.

`periods_per_year` must be a positive integer, default 252. Each adjacent supplied portfolio session is treated as one equally spaced observation period. The function does not consult an exchange calendar. Use a factor appropriate to the supplied regular grid, and include all intended sessions to avoid misleading volatility. Portfolio returns are endpoint equity returns and assume no external deposits or withdrawals; provide a properly flow-adjusted equity index upstream when cash flows exist. This function does not estimate taxes, validate investment suitability, authenticate sources, or establish outperformance.
