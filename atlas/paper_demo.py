"""One-command reproducible synthetic signal/fill/exit and report demonstration."""

import copy, json, tempfile
from pathlib import Path
from .paper import initialize, advance
from .storage import LocalStore
from .portfolio_report import write_report


def run(output):
    root = Path(__file__).resolve().parents[1]
    first = json.loads((root / "examples/synthetic.json").read_text())
    second = copy.deepcopy(first)
    row = copy.deepcopy(second["history"][-1])
    row.update(d="2026-10-26", c=row["c"] * 1.03, ac=row["ac"] * 1.03, v=row["v"] * 2)
    row.update(h=row["c"] * 1.01, l=row["c"] * 0.99, o=row["c"])
    second["history"].append(row)
    third = copy.deepcopy(second)
    row = copy.deepcopy(third["history"][-1])
    row.update(d="2026-10-27", o=80, h=82, l=78, c=81, ac=81)
    third["history"].append(row)
    with tempfile.TemporaryDirectory(prefix="atlas-demo-") as tmp:
        store = LocalStore(Path(tmp) / "ledger.db")
        state = initialize("25000", synthetic=True)
        state["enabled"] = True
        store.commit(0, "init", state)
        for i, snapshot in enumerate([first, second, third], start=1):
            day = snapshot["history"][-1]["d"]
            for source in snapshot["sources"]:
                source.update(
                    observed_at=day + "T20:00:00Z", available_at=day + "T21:00:00Z"
                )
            state = advance(store.read()["state"], [snapshot], as_of=day + "T22:00:00Z")
            store.commit(i, "day-" + day, state)
        persisted = store.read()["state"]
    path = Path(output)
    path.mkdir(parents=True, exist_ok=True)
    (path / "ledger.json").write_text(json.dumps(persisted, indent=2) + "\n")
    write_report(persisted, "2026-10-26", path, as_of="2026-10-28T22:00:00Z")
    for snapshot in persisted["snapshots"]:
        print(json.dumps(snapshot))
    print(
        "SYNTHETIC: signal, later-session fill and gap-stop exit persisted/reloaded. No real orders or messages."
    )
    return persisted
