# Changelog

## 1.2.0 — 2026-10-30

- Added generic SEC/FRED research observations, batch peer statistics/correlations, operational readiness/reviews/outbox bookkeeping, configurable committee lifecycle and retained-state audit verification.
- Added offline accounting demonstration and migration 002 for PostgreSQL audit chains; fresh and extracted release verification includes the full accounting roundtrip.

Adds USD-base/native USD and CAD cash sleeves, dated FX valuation and explicit fee-bearing conversions, CAD report views and FX attribution. Adds immutable sourced corporate-action terms, dividend entitlement/payment receivables, splits, symbol changes, cash/share mergers, spin-offs, return of capital and confirmed writeoffs, with operator-supplied withholding/basis and cash-in-lieu terms. Split histories require an explicit raw/already-adjusted declaration; new instruments require reviewed post-action history.

Adds operator-configured benchmark registries, exact-session/currency/availability checks, fixed initial-weight baskets and relative-risk metrics. Total-return comparisons require whole-period distribution-completeness attestation; incomplete, missing or incompatible comparisons remain explicitly unavailable. No automatic cash conversion, tax filing, source authentication, broker execution or private deployment history is added. Research-only boundaries and idealized next-session same-close paper fills remain. Hosted Grok Bot/Supabase acceptance and real provider coverage remain unverified.

## 1.1.0 — 2026-10-30

Adds a persistent paper ledger, local SQLite and Supabase stores, clean SQL migration, daily CLI, idealized next-session fills and exits, costs/risk/frequency/concentration controls, portfolio reports, explicit delivery reservations, optional vendor observation refresh, and disposable PostgreSQL integration tests. No private deployment state is imported. Hosted Supabase/Grok Bot acceptance and live provider access remain unverified; advanced FX, distribution and corporate-action accounting are outside this implementation.


## 1.0.0 — 2026-10-30

Initial public research edition: deterministic equity engine, offline synthetic demo, strict local snapshot boundary, escaped report, Grok Bot profile/skill/routine source, and tests. No private deployment data, remote migrations, messaging or execution gateways are included. No live performance or complete Grok Bot acceptance is claimed.
