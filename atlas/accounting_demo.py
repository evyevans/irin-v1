"""Offline demonstration of cash sleeves, distributions, splits and benchmarks."""

import copy
import json
import tempfile
from pathlib import Path
from .paper import initialize, advance
from .portfolio_report import write_report
from .storage import LocalStore


def steps():
    first = json.loads(
        (Path(__file__).resolve().parents[1] / "examples/synthetic.json").read_text()
    )
    snapshots = [first]
    for day, multiplier in [
        ("2026-10-26", 1.03),
        ("2026-10-27", 0.5),
        ("2026-10-28", 1),
    ]:
        snap = copy.deepcopy(snapshots[-1])
        row = copy.deepcopy(snap["history"][-1])
        close = row["c"] * multiplier
        row.update(
            d=day,
            o=close,
            h=close * 1.01,
            l=close * 0.99,
            c=close,
            ac=close,
            v=row["v"] * 2,
        )
        snap["history"].append(row)
        snapshots.append(snap)
    for snap in snapshots:
        day = snap["history"][-1]["d"]
        snap["market"] = dict(history_basis="raw", distributions_complete=True)
        for source in snap["sources"]:
            source.update(
                observed_at=day + "T20:00:00Z", available_at=day + "T21:00:00Z"
            )
    for i, snap in enumerate(snapshots):
        day = snap["history"][-1]["d"]
        fx = dict(
            rate="1.25" if i < 2 else "1.30",
            observed_at=day + "T20:00:00Z",
            available_at=day + "T21:00:00Z",
            source="https://example.invalid/fx",
            synthetic=True,
        )
        bookkeeping = dict(
            fx=fx,
            benchmarks=[
                dict(
                    id="demo-total-index",
                    category="broad",
                    currency="USD",
                    return_type="TOTAL_RETURN",
                    methodology="Synthetic total-return index",
                    source="https://example.invalid/index",
                    observations=[
                        dict(
                            session=s["history"][-1]["d"],
                            value=str(100 + j),
                            available_at=s["history"][-1]["d"] + "T21:00:00Z",
                        )
                        for j, s in enumerate(snapshots[: i + 1])
                    ],
                )
            ],
        )
        if i == 0:
            bookkeeping["conversions"] = [
                dict(
                    id="demo-funding", from_currency="USD", amount="1000", fee_bps="10"
                )
            ]
        if i == 2:
            common = dict(
                ticker="DEMO-GRID",
                source="https://example.invalid/actions",
                available_at="2026-10-26T21:00:00Z",
                effective_date=day,
            )
            bookkeeping["actions"] = [
                dict(
                    common,
                    id="demo-dividend",
                    kind="cash_dividend",
                    sequence=1,
                    amount_per_share="1",
                    currency="USD",
                    pay_date="2026-10-28",
                    withholding_rate=".15",
                ),
                dict(common, id="demo-split", kind="split", sequence=2, ratio="2"),
            ]
        if i == 3:
            bookkeeping["actions"] = [
                dict(
                    id="demo-cash-merger",
                    ticker="DEMO-GRID",
                    kind="cash_merger",
                    cash_per_share="60",
                    currency="USD",
                    source="https://example.invalid/actions",
                    available_at="2026-10-27T21:00:00Z",
                    effective_date=day,
                )
            ]
        yield snap, bookkeeping


def run(output):
    state = initialize("25000", synthetic=True)
    state["enabled"] = True
    with tempfile.TemporaryDirectory(prefix="atlas-accounting-") as tmp:
        store = LocalStore(Path(tmp) / "ledger.db")
        store.commit(0, "init", state)
        for i, (snap, bookkeeping) in enumerate(steps(), start=1):
            day = snap["history"][-1]["d"]
            state = advance(
                store.read()["state"],
                [snap],
                as_of=day + "T22:00:00Z",
                bookkeeping=bookkeeping,
            )
            store.commit(i, day, state)
        state = store.read()["state"]
        audit = store.verify_audit()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "ledger.json").write_text(json.dumps(state, indent=2) + "\n")
    (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    write_report(
        state, "2026-10-26", output, as_of="2026-10-29T22:00:00Z", report_currency="CAD"
    )
    print(
        json.dumps(
            dict(
                synthetic=True,
                equity_usd=state["equity"],
                cash_cad=state["accounting"]["cash_cad"],
                events=[e["kind"] for e in state["events"]],
                audit_valid=audit["valid"],
            )
        )
    )
    return state
