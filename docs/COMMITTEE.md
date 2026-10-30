# User-defined committee reviews

`atlas.committee.evaluate(config, votes, as_of="2026-10-24T22:00:00Z")` is a
pure, deterministic review. No registry of named people, account settings,
holdings, capital amounts, or private research is seeded. The caller supplies
the registry, policy, votes and complete veto history. Inputs are not mutated.

The result contains exactly one `action` (also exposed as `action_state`):
`OPEN_PAPER_POSITION`, `KEEP_WATCHLIST`, `REDUCE_REMOVE`, or `REJECT`.
`OPEN_PAPER_POSITION` is an advisory simulated action. It never enables live
execution or bypasses independent research, freshness, cash, concentration,
drawdown, frequency, or stop/risk requirements.

## Registry and policy

This small illustration uses functional role IDs. Choose your own registry;
the module does not automatically install this example.

```json
{
  "schema_version": 1,
  "members": [
    {"id": "quality", "roles": ["score"], "weight": 60},
    {"id": "downside", "roles": ["score", "veto"], "weight": 40},
    {"id": "capacity", "roles": ["sizing"], "sizing_floor": 0.5},
    {"id": "entry", "roles": ["timing"]}
  ],
  "veto_rules": [{
    "id": "funding",
    "holder": "downside",
    "scope": "funding shortfall",
    "trigger_condition": "Documented obligations exceed committed funding",
    "minimum_grade": "A",
    "expiry_days": 30,
    "cure_condition": "Committed financing covers the documented shortfall"
  }],
  "policy": {
    "open_min": 70,
    "watch_min": 55,
    "strong_min": 80,
    "min_score_lenses_active": 2,
    "tie_downside_members": ["downside"]
  }
}
```

IDs must be unique. Roles are `score`, `sizing`, `timing`, and `veto`; a member
may have multiple roles. Only score members carry a positive `weight`, and all
registered weights must sum **exactly to 100**. Every veto member must own at
least one explicit, narrow rule. Veto grades are A or B, expiry limits are
1–365 days, and trigger/cure conditions must be stated.

Members default to `required: true` and `minimum_grade: "B"`. A member can
explicitly be optional; missing optional score weight still contributes zero
to the fixed 100-point denominator. A member's grade can be A, B, or C.
Sizing members have a configurable `sizing_floor` between 0.5 and 1; their
individual factors cannot exceed 1. No role can vote outside its authority.

Policy fields and defaults:

| Field | Default | Meaning |
|---|---:|---|
| `watch_min` / `open_min` / `strong_min` | 55 / 70 / 80 | Ordered score thresholds |
| `min_score_lenses_active` | 1 | Minimum number of usable score votes |
| `tie_band_upper` / `tie_downside_min` | 72 / 60 | Borderline opening band and downside average floor |
| `tie_downside_members` | `[]` | User-selected score roles; empty disables this tie check |
| `dissent_score_max` | 40 | Strong dissent when score is strictly below this |
| `dissent_confidence_min` | 4 | Minimum confidence for a strong dissent |
| `dissent_step` / `dissent_floor` | 0.25 / 0.5 | Reduction per strong dissent, bounded below |
| `dissent_block_at` | 3 | Strong dissent count that blocks an opening |
| `max_multiplier` | 1 | Upper bound on combined risk multiplier |
| `vote_max_age_days` | 30 | Maximum age measured from vote observation |
| `timing_policy` | `"all"` | `all` or `any` timing passes required |

Unknown policy keys are rejected. Required missing timing votes block opening
even under `timing_policy: "any"`.

## Vote evidence and authority

`votes` is an object containing `members`, an explicit array with at most one
vote per registered member. Each usable vote needs its `id`, integer
`confidence` from 1 through 5, `observed_at`, `available_at`, and a nonempty
`sources` array. Optional `expires_at` must follow observation; a vote is
unavailable at or after its expiry. All timestamps require an explicit timezone.

```json
{
  "id": "quality",
  "confidence": 4,
  "score": 90,
  "observed_at": "2026-10-22T20:00:00Z",
  "available_at": "2026-10-22T21:00:00Z",
  "sources": [{
    "source": "https://example.invalid/filing",
    "grade": "A",
    "observed_at": "2026-10-21T20:00:00Z",
    "available_at": "2026-10-21T21:00:00Z"
  }]
}
```

Score-role votes supply `score` in [0,100]. Sizing-role votes supply
`sizing_factor` between their registered floor and 1. Timing-role votes supply
`timing: "pass"` or `"wait"`. A combined-role member supplies each applicable
field. Veto assertions belong in the separate `vetoes` array.

Source URLs must use HTTPS without credentials, query strings or fragments.
Source observation must precede availability, and source availability must be
no later than the vote's availability and the evaluation cutoff. At least one
source must meet the member's minimum evidence grade; a future source in the
record requires review even if another source qualifies. Grades, source content,
and relevance remain operator attestations, never independent verification.

Unavailable, stale, expired, undergraded, or incomplete required votes yield
`KEEP_WATCHLIST` and explicit blockers. Invalid numbers, confidence, role
authority, registry structure or timestamp ordering raise `ValueError`.

The score is `sum(registered_weight * usable_score) / 100`; missing votes are
never renormalized over the remaining active weight. Strong dissent reduces
the product of the sizing votes by
`max(dissent_floor, 1 - dissent_step * dissent_count)`. The final cap is at most
`max_multiplier`. Multiple sizing roles multiply independently, so their product
can be below an individual role's floor. Missing sizing votes use their role's
floor while remaining blocked if required. `risk_multiplier` is zero unless
the resulting action is `OPEN_PAPER_POSITION`; `multiplier_cap` also exposes the
computed advisory cap for review.

## Narrow veto lifecycle

An asserted veto identifies its original `id`, `rule_id`, authorized `member_id`,
boolean `trigger_condition_met`, `triggered_at`, `expires_at`, and `evidence`
using the source-record schema above. Its expiry must fall after its trigger
and within the registered rule's expiry limit. Trigger satisfaction is an
explicit attestation tied to the rule, not inferred from an unrelated low score.
Evidence must meet the rule's grade and have been available by the trigger.

```json
{
  "id": "funding-review",
  "rule_id": "funding",
  "member_id": "downside",
  "trigger_condition_met": true,
  "triggered_at": "2026-10-22T22:00:00Z",
  "expires_at": "2026-11-20T22:00:00Z",
  "evidence": [{
    "source": "https://example.invalid/filing",
    "grade": "A",
    "observed_at": "2026-10-21T20:00:00Z",
    "available_at": "2026-10-21T21:00:00Z"
  }]
}
```

A qualified, unexpired assertion is `ACTIVE` and yields `REJECT`, or
`REDUCE_REMOVE` when `votes.previously_listed` is true. An unqualified trigger,
insufficient grade, or unavailable evidence is `REVIEW_REQUIRED`, which blocks
opening. An expired but unresolved veto is `EXPIRED_REVIEW_REQUIRED`: **expiry
never silently removes it or restores opening eligibility**.

An assertion can include `cure` with boolean `condition_met`, `observed_at`,
`available_at`, and `evidence`. The cure must follow the original trigger,
attest the registered cure condition, and meet the same evidence grade. Its
qualifying sources must have been observed at or after the veto trigger and
available by the cure record's availability and cutoff. Reusing pre-trigger
evidence cannot establish a later cure.
A valid cure changes a qualified assertion to `CURED`; unsupported or future
cures cannot clear it. The record remains in output with its rule and condition.

This function is stateless. A persistence layer must retain prior veto IDs and
their original assertions across reviews, and prevent omission or rewriting
from erasing unresolved vetoes. Supply complete history on each evaluation.
The function alone cannot detect an assertion deleted by its caller.

## Action precedence and audit output

Optional `votes.structural_reject` is a nonempty reason for a negative action.
Optional `votes.blockers` is an array of external pending-gate descriptions.
An active veto or structural rejection takes precedence. Otherwise incomplete
required review comes first, then negative scores, opening thresholds, tie
checks, dissent, timing and external blockers. `previously_listed` affects only
the negative action label; it never initiates a sale.

Output includes the unrenormalized score, active score count/weight, dissent
count/factor, sizing product/cap, blockers, individual veto statuses, input
hashes and explicit cutoff. `execution_enabled` is always false. No database,
network, broker, messaging, or implicit action occurs.

## Persistent paper integration

The optional session bookkeeping key `committees` maps supplied tickers to
objects containing `config` and `votes` in the schemas above. For example,
construct the file from separately reviewed local JSON inputs:

```python
import json
from pathlib import Path

bookkeeping = {
    "committees": {
        "DEMO-GRID": {
            "config": json.loads(Path("committee-config.json").read_text()),
            "votes": json.loads(Path("committee-votes.json").read_text()),
        }
    }
}
Path("session-bookkeeping.json").write_text(json.dumps(bookkeeping))
```

Submit it with the other explicit session inputs:

```sh
python3 -m atlas paper --ledger local-data/ledger.db run local-data/snapshot.json --as-of 2026-10-24T22:00:00Z --bookkeeping session-bookkeeping.json
```

This requires an already initialized ledger and a snapshot for the actual
session being committed. The example paths and ticker are placeholders. FX,
corporate actions, conversions and benchmark terms can coexist in this same
bookkeeping object; adding committee data does not replace their requirements.

The paper runner persists each submitted envelope under its ticker and
reevaluates retained envelopes on subsequent sessions, even when no replacement
is submitted. Vote expiry and unresolved vetoes therefore remain effective.
Tickers without an installed committee keep the existing core entry gates;
absence of a committee is not a completed committee review.

Once committed, a ticker's configuration is immutable. A later vote envelope
must repeat every historical veto ID with its original assertion terms.
Omission or rewriting rejects the session. A first `cure` may be added to an
existing veto; once committed, that cure is also immutable. All updates use the
ledger's atomic session commit. This persistence layer closes the stateless
function's omission boundary described above.

`previously_listed` is derived from actual ledger holdings during each review;
a caller's submitted boolean cannot choose the held-position action label.
New entries for an installed committee require `OPEN_PAPER_POSITION`, retain
all independent core gates, and scale whole-share sizing by the committee's
`risk_multiplier`, which cannot exceed 1. A committee cannot enable entries,
release a halt, invent settlement cash, or increase the core risk capacity.

A negative review of a holding queues its exit after today's exit processing;
the earliest resulting fill is the following session's open under the existing
exit model. It cannot retroactively fill at today's open. Protective stops and
already queued exits continue through committee review and operational holds.
`KEEP_WATCHLIST` blocks new entries without itself ordering a holding's exit.

Current computed results are retained as `committee_results` on the ledger and
under `committees` in daily valuation snapshots. The original submitted
envelopes remain in committed state and retained audit history. Unit and paper
integration coverage is in `tests/test_committee.py` and
`tests/test_committee_integration.py`; those checks establish deterministic
source behavior, not hosted platform acceptance or investment performance.


New paper decisions require the evaluation timestamp's UTC date to equal the valued US/Canadian session date. This conservative cutoff prevents later-day evidence from being replayed into an earlier decision or next-open exit. After-midnight processing must wait for a supported workflow change; never backdate newly acquired evidence. Historical replay requires genuine point-in-time inputs and their honest historical evaluation cutoff. Exact committed-session retries do not create another decision.
