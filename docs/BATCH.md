# Offline batch research

`python3 -m atlas batch manifest.json --as-of 2026-10-23T22:00:00Z --output batch-output`

The manifest defines the entire research universe. It never loads a bundled ticker
list, private research, database state, local account, or network feed.

```json
{
  "schema_version": 1,
  "snapshots": ["snapshots/peer-a.json", "snapshots/peer-b.json"],
  "held": []
}
```

Paths resolve relative to the manifest directory. Each file uses the complete
[snapshot contract](INPUTS.md). Supply an explicit held ticker array, including an
empty array for an empty portfolio. Every held instrument must have a snapshot in
the same universe. All snapshots must share their last history session, synthetic
mode and portfolio context; `open_positions` must equal the held list length.
There is no inferred holding, balance, evidence, or approval.

For CAD listings, provide a top-level `fx` observation using the paper accounting
contract: `rate` is CAD per USD, with `observed_at`, `available_at`, HTTPS `source`,
and matching boolean `synthetic`. It must be available by `--as-of` and no more
than 96 hours old. CAD quotes and applicable fundamentals convert to USD for the
research rules; supplied sources and the FX observation remain visible in output.
Histories must already use consistent split-adjusted share units. No corporate
action or missing price is invented.

The batch replaces caller-claimed `context.val_stats` and `context.max_corr`:

- Positive supplied EV/EBITDA values form a sorted universe distribution. Its p90
  is element `floor(0.9 * (n - 1))`, with a minimum of 10 usable observations.
- Utility and independent power producer EV/EBITDA share the engine's
  `utility_ipp` median, with a minimum of 5 observations. Segment medians also
  require 5 observations each. Segment classification uses the public rules.
- Annualized 260-session adjusted-return volatility is computed from histories.
  Its universe median requires at least 10 positive, available observations.
- Correlations use up to the latest 252 adjusted-price return intervals and at
  least 60 shared intervals. Both interval start and end dates must match.
  Missing sessions are never forward-filled or assigned zero returns. Constant
  returns yield unavailable correlation. Returns are in each listing's local
  currency; this is not a USD portfolio-return correlation model.
- A candidate's maximum held correlation is available only if every applicable
  held pair is available. A held candidate excludes itself. Missing comparisons
  remain `null`, allowing the engine's correlation gate to fail closed.

Snapshots with unavailable fundamentals, unusable price or filing provenance,
or any invalid source availability remain in evaluation results but do not contribute peer
statistics or correlations. Other rule failures do not automatically remove a
peer from its valuation population. Future history sessions are rejected. Source
metadata is an operator attestation, not independent verification of prices,
fundamentals, corporate action adjustment, or publisher independence.

`batch.json` records the explicit cutoff, universe, sample counts, eligibility,
computed thresholds, correlation sample sizes/reasons, original input digests,
and original source metadata. `results.json` and `report.html` contain the actual
public-engine evaluations using computed context. Their input hashes describe
the effective evaluation snapshots; original input hashes are separately retained
in `batch.json`. Manifest filenames and local filesystem paths are not copied to
the output. Caller-provided names, tickers and source metadata are preserved;
inspect those inputs before sharing artifacts.

Statistics describe only the supplied population and can be affected by its
selection bias. Small samples remain unavailable rather than inheriting defaults.
All results are research only; execution remains disabled.
