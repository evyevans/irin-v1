# Generic research observations

`atlas.research_data` supplies optional acquisition and deterministic transformation of research inputs. It contains no seeded universe, portfolio, project identity, contact details or source assertions. Outputs need review before populating a dossier; these utilities do not certify relevance, independence, accounting comparability or filing semantics.

## Commands

After registering `research_data.add_commands(commands)` and dispatching `research_data.execute(args)`:

```sh
python3 -m atlas research-data fundamentals facts.json --as-of 2026-10-30T12:00:00Z --currency USD --price 20 --output local-data/fundamentals.json
python3 -m atlas research-data fundamentals --cik 123456 --as-of 2026-10-30T12:00:00Z --output local-data/fundamentals.json
python3 -m atlas research-data filing annual-report.html --filed 2026-02-01 --as-of 2026-10-30T12:00:00Z --output local-data/flags.json
python3 -m atlas research-data filing --url https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/report.htm --filed 2026-02-01 --as-of 2026-10-30T12:00:00Z --output local-data/flags.json
python3 -m atlas research-data regime observations.json --as-of 2026-10-30T12:00:00Z --output local-data/regime.json
```

CIK and filing URL above are illustrative placeholders. SEC requests require an operator-owned `SEC_USER_AGENT` containing organization identification and contact email. Never put actual contact details in distributed files. One fetch is paced, bounded to 10 MB and redirects are rejected; concurrent workers must coordinate SEC rate limits. Filing fetch accepts only canonical HTTPS archive document paths on `www.sec.gov`; companyfacts URLs are constructed from a numeric CIK on `data.sec.gov`. No arbitrary URL fetch exists.

`regime --fetch` downloads current FRED CSV observations. Set `--as-of` after retrieval; otherwise the result is explicitly unknown/adverse. The output retains the observations and retrieval evidence so it can be saved for a subsequent evaluation. Network access is optional and providers can reject requests.

## Python contracts

- `extract_companyfacts(payload, *, as_of, currency="USD", price=None)` returns `series`, per-year `provenance` and derived `metrics`. Input is the SEC companyfacts JSON structure; price is an operator-supplied observation in the selected currency. No price date or price verification is inferred.
- `scan_filing(text, *, filed, as_of, source=None)` counts annual-report red-flag phrases, emits a text digest and labels results `heuristic_scan`. Hits can be negated, historic or irrelevant; absence of hits proves nothing. `filed` and the claim that text is an annual report remain operator attestations.
- `evaluate_regime(payload, *, as_of)` expects `retrieved_at`, `real_yield` and `industrial_production`; both series contain ascending unique `{date, value}` rows. Optional `sources` is preserved. Unknown data returns `known=false, adverse=true`.
- `fetch_companyfacts(cik)`, `fetch_filing(url)` and `fetch_regime()` acquire raw evidence and retrieval metadata. No account credentials are supplied by the package.

## Time and accounting boundaries

Only annual forms 10-K, 20-F, 40-F and amendments are selected. Flow periods must span 330–400 days. Facts must have period end no later than filing date, and filing date strictly before the evaluation UTC date: companyfacts dates do not establish intraday dissemination times. Future amendments are excluded. For each fiscal end, the latest eligible filing wins, with deterministic concept preference. Provenance records taxonomy, concept, unit, accession, filing date and period.

USD and CAD units never mix. Diluted shares use `shares`; EPS uses the selected currency per share. Metrics join on the latest revenue fiscal end, rather than mixing recent balance sheets with older income statements. Missing inputs remain null, including missing dividends, research expense and tax rates; no assumed tax rate or zero is invented. Explicit combined debt is preferred. `LongTermDebt` is kept separate and augmented only by a separately disclosed short-term-borrowing observation at the same fiscal end. Current-plus-noncurrent debt is never augmented again. Output `debt_basis` identifies this derivation; a long-term-only balance remains explicitly identified as such and may understate undisclosed borrowing. Review mapped debt concepts for each issuer. Acquisition capex, gross debt, cash and share observations must be nonnegative; negative observations require explicit reviewed normalization before ingestion. Losses and negative equity remain valid. Three-year FCF averages, ROE and stock-compensation ratios require three consecutive annual periods ending at the latest revenue fiscal end. Historical comparison periods and growth still require issuer-specific accounting review; custom tags, dimensional segment facts and issuer currency changes are not inferred. No FX conversion of fundamentals occurs.

The regime reproduces the deterministic rule: real ten-year yield rises over 25 basis points across 63 observation intervals, while industrial production falls over three monthly intervals. It requires 64 yield observations with no gap over seven days and four approximately monthly production observations. Industrial production values must be positive; negative real yields remain valid. Yield data older than ten calendar days or production data older than eighty days is unknown. Dates after retrieval invalidate the evidence. This is an inference over current retrieved data, **not** point-in-time FRED vintage history: revisions and release lags prevent backtest certification. `historical_vintage_verified` is always false.

## Official references

The [SEC XBRL API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) documents companyfacts, standard taxonomies and unit arrays. [SEC developer resources](https://www.sec.gov/about/developer-resources) describe identification and fair-access limits. [FRED download guidance](https://fred.stlouisfed.org/help) links data downloads and explains source updates. The [FRED real-time period documentation](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html) distinguishes vintage/realtime data from current values. Current CSV downloads used here do not request a historical vintage.
