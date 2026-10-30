"""Actual full-ledger persistence smoke test against the disposable PostgreSQL store."""

import copy, json, os, subprocess
from pathlib import Path
from atlas.paper import initialize, advance
from atlas.storage import encoded

ROOT = Path(__file__).resolve().parents[1]
PSQL = os.environ["PG_BIN"] + "/psql"


def sql(query, **variables):
    args = [PSQL, "-X", "-qAt", "-v", "ON_ERROR_STOP=1"]
    for key, value in variables.items():
        args += ["-v", key + "=" + str(value)]
    return subprocess.check_output(args, input=query, text=True).strip()


def commit(rev, key, state):
    return int(
        sql(
            "set role service_role;select public.atlas_store_commit(:'rev'::bigint,:'key',:'state'::jsonb);",
            rev=rev,
            key=key,
            state=encoded(state),
        )
    )


state = initialize("25000", synthetic=True)
commit(0, "init", state)
state["enabled"] = True
commit(1, "enable", state)
snap = json.loads((ROOT / "examples/synthetic.json").read_text())
state = advance(state, [snap], as_of="2026-10-23T22:00:00Z")
commit(2, "day-one", state)
second = copy.deepcopy(snap)
row = copy.deepcopy(second["history"][-1])
row.update(d="2026-10-26", c=row["c"] * 1.03, ac=row["ac"] * 1.03, v=row["v"] * 2)
row.update(h=row["c"] * 1.01, l=row["c"] * 0.99, o=row["c"])
second["history"].append(row)
for source in second["sources"]:
    source.update(
        observed_at="2026-10-26T20:00:00Z", available_at="2026-10-26T21:00:00Z"
    )
state = advance(state, [second], as_of="2026-10-26T22:00:00Z")
commit(3, "day-two", state)
assert len(state["positions"]) == 1
assert commit(3, "day-two", state) == 4
stored = json.loads(sql("set role service_role;select public.atlas_store_read();"))
assert stored["revision"] == 4 and stored["state"] == state
print(
    "PASS: initialized, enabled, signalled, filled and replayed full portfolio through PostgreSQL; exact state roundtrip."
)

from atlas.accounting_demo import steps

for revision, (snapshot, bookkeeping) in enumerate(list(steps())[2:], start=4):
    day = snapshot["history"][-1]["d"]
    state = advance(
        state, [snapshot], as_of=day + "T22:00:00Z", bookkeeping=bookkeeping
    )
    commit(revision, "accounting-" + day, state)
stored = json.loads(sql("set role service_role;select public.atlas_store_read();"))
assert stored["revision"] == 6 and stored["state"] == state
assert not state["positions"]
assert any(e["kind"] == "split" for e in state["events"])
assert any(e["kind"] == "dividend_payment" for e in state["events"])
assert state["benchmarks"] and state["accounting"]["fx"]["rate"] == "1.30"
audit = json.loads(
    sql("set role service_role;select public.atlas_store_audit_verify();")
)
assert audit["valid"] and audit["revision"] == 6
print(
    "PASS: FX, dividend entitlement/payment, split, cash merger, benchmark registry and audit chain persisted/reloaded exactly through PostgreSQL."
)
