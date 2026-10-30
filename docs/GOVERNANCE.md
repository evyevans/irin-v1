# Operational readiness and durable work

The optional governance controller holds new paper entries when required health checks are absent, failed or expired, reviews are overdue, or notice delivery bookkeeping fails. It continues to permit protective exit processing. It does not send notices, enable the ledger, release a manual halt, certify data, or create real-money execution capability.

Installations without an explicit `governance` record retain the existing paper enablement, halt and risk gates. Once configured, missing or malformed governance fields fail closed. This opt-in boundary preserves existing ledgers; it is not a declaration that an unconfigured installation has passed operational checks.

## Configure and record checks

Apply the clean cloud migrations in order, `001` followed by `002`, for a new cloud installation. Existing installations need the later migration before using its audit facilities. Use the installation-owned service-worker credentials described in [CLOUD.md](CLOUD.md); local SQLite needs no cloud project. No private policy, readiness record, identity or deployment state is imported.

The CLI commits each operation through the same local/cloud state store:

```bash
python3 -m atlas paper governance --input local-data/governance.json
```

For example, create that file with:

```json
{
  "operation": "configure",
  "config": {"required_checks": ["accounting_health", "source_health", "recovery_health"]}
}
```

These names are generic operator choices, not built-in tests. Configuration requires at least one unique nonempty check name. Reconfiguration retains existing health history, reviews and notices; newly required checks remain missing until recorded. Record each independently reviewed result with another operation file:

```json
{
  "operation": "record_check",
  "name": "accounting_health",
  "passed": true,
  "observed_at": "2026-10-30T21:00:00Z",
  "expires_at": "2026-10-30T23:00:00Z"
}
```

Repeat for every required check with actual results and appropriate expiry. `passed` must be a JSON boolean. Both timestamps require explicit timezones, and expiry must follow observation. At `as_of`, a check passes only when `observed_at <= as_of < expires_at` and its result is true. The expiry boundary is stale. Future observations cannot satisfy readiness. Identical observations replay idempotently; conflicting same-time or older replacement observations reject. Later observations are retained in history and supersede the current result.

The public controller evaluates these attestations; it does not run an external health probe or independently establish that accounting, sources, infrastructure or recovery controls work. Choose check definitions and evidence outside the module, run those checks, then record honest results. A healthy status cannot override the research, market, cash, risk, enablement or halt gates.

## Reviews and outbox operations

Each CLI input has an `operation` plus that function's arguments:

| Operation | Arguments |
|---|---|
| `add_review` | `task_id`, timezone-aware `due_at`, optional text `detail` |
| `resolve_review` | Existing `task_id`, timezone-aware `resolved_at` |
| `queue_notice` | `task_id`, timezone-aware `deadline_at`, optional object `payload` |
| `acknowledge_notice` | Existing `task_id`, `status`, timezone-aware `at`, optional text `evidence`; evidence required for `sent` |

An unresolved review becomes overdue when `due_at <= as_of`. A recorded future resolution does not clear an already-due task at an earlier cutoff. Review terms and resolved timestamps are immutable: an identical request is idempotent, while conflicting reuse of an ID rejects. Create a new ID for different work.

Notice terms are immutable and retained after completion. The allowed status transitions are:

```text
queued -> reserved -> sent
queued -> failed -> reserved
reserved -> failed -> reserved
```

`sent` is terminal. A reservation does not establish delivery. An external operator or adapter must explicitly record `sent` with nonempty receipt/evidence text. Status changes must advance in time; identical acknowledgements replay idempotently. Failed notices hold readiness immediately. Queued, reserved or failed notices that reach their deadline without a valid sent acknowledgement are overdue. Future acknowledgements cannot clear readiness at an earlier cutoff. Do not blindly retry a reserved notice after an uncertain external outcome; reconcile delivery first to avoid duplicates.

Queueing and acknowledgement perform bookkeeping only. They never contact a recipient, choose an address, invoke a messaging tool, or grant permission to send. Receipt text remains an operator assertion. A delivery reservation from the separate weekly report workflow is a distinct record and does not automatically update this outbox.

## Assessment, recovery and audit

`atlas.governance.assess(state, as_of=...)` returns `configured`, `ready`, `mode` (`READY` or `HOLD`), per-check statuses, machine-readable reasons, overdue review/notice IDs and `entries_allowed`. It does not mutate its input. `entries_allowed` also requires the ledger's existing `enabled` flag and absence of its `halted` flag. `READY` describes operational prerequisites, not permission to bypass any other entry gate. The daily paper runner records its assessment and requires readiness for new entries while continuing protective exits.

Recovery is deterministic: supply a later fresh passing observation, resolve due work, and reconcile failed/overdue deliveries with valid state transitions. A subsequent assessment returns `READY` only when all applicable conditions pass. This recovery does not silently enable a disabled portfolio or clear an existing halt. No separate human approval workflow is implemented by this module.

Each mutation returns a state copy with retained governance history. Atomic store commits protect concurrent changes; cloud audit verification is available through `paper audit-verify`, with optional `--expected-head` for comparison against a previously retained audit head. Keep the expected head independently if using it to detect replacement history. These controls make supplied operations inspectable; they do not make a trusted service-worker administrator untrusted or prove the truth of submitted health checks. This generic public controller does not reproduce a private system's database triggers, readiness checklist, mode taxonomy or recovery policies.
