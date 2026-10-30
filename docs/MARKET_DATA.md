# Market refresh and research input

A generic installation has no preselected private watchlist or old research cache. Supply your universe through snapshots. Every snapshot must identify the instrument and contain point-in-time research grounded in allowed sources. The Bot's source tools gather filings, fundamentals, sector evidence and opposing evidence; Python validates and grades the supplied contract. It does not perform a complete semantic filing audit.

The optional `refresh` command retrieves public daily OHLCV/adjusted history from Yahoo's chart interface and closing prices from Nasdaq's public historical interface. It requires a **real** dossier, explicit exchange session close and next-session date. It writes a new local snapshot; it never changes a ledger automatically.

```bash
python3 -m atlas refresh local-data/dossier.json --session-close <actual-close-with-timezone> --next-session <YYYY-MM-DD> --output local-data/current.json
```

Provider endpoints are best-effort, unofficial integration surfaces and can change, rate-limit or deny access. Access may be subject to restrictions; review provider terms before automated or commercial use. No provider key or paid data service is bundled, and no promise of permanent free access is made. No returned observation is relabelled real-time. Test vendor access in your own environment before scheduling. There is no fallback to synthetic data.

Cross-checking requires ten common dates, identical latest dates, latest close agreement within 0.5%, and at least eight of ten close pairs within that tolerance. Fewer observations or a vendor failure reject refresh. The fetcher rejects histories containing splits pending manual reconciliation. It records hashes of retrieved responses and actual retrieval/availability times; it cannot reconstruct historical availability from a fresh fetch.

Two vendors may share the same underlying market feed. Their source records intentionally use one shared/unverified upstream ID. Therefore the refresh output alone cannot qualify the research or generate a paper entry. A qualified analyst must establish source independence with documented evidence or obtain genuinely independent allowed sources. Do not simply change upstream strings to obtain a pass. Calendar, identity, corporate-action review and research fundamentals remain operator attestations.

The optional vendor refresher currently targets US/USD data. The paper ledger separately supports native USD/CAD settlement, explicit dated conversions and sourced distribution/reorganization accounting through [ACCOUNTING.md](ACCOUNTING.md). The refresher does not automatically create those accounting terms; its split rejection requires deliberate reconciliation with correctly declared history basis. Do not force unresolved actions through refresh or label a simulation a validated total-return backtest. The model uses adjusted returns for technicals and raw prices for hypothetical fills. Its price comparisons do not prove corporate-action consistency or comprehensive history coverage.

No benchmark outperformance is claimed. The source and benchmark contract must be independently designed for a defensible performance comparison; current portfolio snapshots and weekly returns describe this simulated ledger only. Unavailable comparative metrics remain unavailable.
