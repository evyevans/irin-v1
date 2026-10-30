"""Native settlement integration: qualification, funded fills, FX and exits."""

import copy
import json
from decimal import Decimal as D
from pathlib import Path
import unittest

from atlas.paper import advance, initialize

ROOT = Path(__file__).resolve().parents[1]


def observation(day, rate="1.25"):
    return dict(
        rate=rate,
        observed_at=day + "T20:00:00Z",
        available_at=day + "T21:00:00Z",
        source="https://example.invalid/fx",
        synthetic=True,
    )


def cad_snapshot():
    snapshot = json.loads((ROOT / "examples/synthetic.json").read_text())
    snapshot["market"] = dict(
        currency="CAD", exchange="TSX", fundamentals_currency="USD"
    )
    for row in snapshot["history"]:
        for key in ("o", "h", "l", "c", "ac"):
            row[key] *= 1.25
    for source in snapshot["sources"]:
        if source["role"] == "price" and source.get("value") is not None:
            source["value"] *= 1.25
    return snapshot


def next_snapshot(snapshot, day, *, gap_below_stop=None):
    snapshot = copy.deepcopy(snapshot)
    row = copy.deepcopy(snapshot["history"][-1])
    close = row["c"] * 1.03
    row.update(
        d=day,
        c=close,
        ac=close,
        o=close * 0.99,
        h=close * 1.005,
        l=close * 0.985,
        v=row["v"] * 2,
    )
    if gap_below_stop is not None:
        stop = float(gap_below_stop)
        row.update(
            o=stop * 0.9, h=stop * 0.95, l=stop * 0.85, c=stop * 0.92, ac=stop * 0.92
        )
    snapshot["history"].append(row)
    for source in snapshot["sources"]:
        source.update(observed_at=day + "T20:00:00Z", available_at=day + "T21:00:00Z")
    return snapshot


class CADRoundtrip(unittest.TestCase):
    def signal(self, *, funded):
        state = initialize("10000", synthetic=True)
        state["enabled"] = True
        snapshot = cad_snapshot()
        bookkeeping = dict(fx=observation("2026-10-23"))
        if funded:
            bookkeeping["conversions"] = [
                dict(id="fund-cad", from_currency="USD", amount="2000", fee_bps="0")
            ]
        state = advance(
            state, [snapshot], as_of="2026-10-23T22:00:00Z", bookkeeping=bookkeeping
        )
        self.assertIn("DEMO-GRID", state["pending"])
        return state, next_snapshot(snapshot, "2026-10-26")

    def test_native_cad_entry_and_gap_exit_with_fx_change_reconcile(self):
        state, snapshot = self.signal(funded=True)
        state = advance(
            state,
            [snapshot],
            as_of="2026-10-26T22:00:00Z",
            bookkeeping=dict(fx=observation("2026-10-26")),
        )
        position = state["positions"]["DEMO-GRID"]
        self.assertEqual(position["currency"], "CAD")
        self.assertEqual(D(position["entry_fx"]), D(".8"))
        native_cost = D(position["entry"]) * position["shares"] * D("1.001")
        self.assertAlmostEqual(D(position["cost"]), native_cost * D(".8"), places=20)
        cad_before_exit = D(state["accounting"]["cash_cad"])
        self.assertAlmostEqual(cad_before_exit, D("2500") - native_cost, places=20)
        self.assertEqual(D(state["cash"]), D("8000"))

        snapshot = next_snapshot(
            snapshot, "2026-10-27", gap_below_stop=position["stop"]
        )
        result = advance(
            state,
            [snapshot],
            as_of="2026-10-27T22:00:00Z",
            bookkeeping=dict(fx=observation("2026-10-27", "1")),
        )
        self.assertFalse(result["positions"])
        exit_event = next(e for e in reversed(result["events"]) if e["kind"] == "exit")
        native_proceeds = D(exit_event["price"]) * position["shares"] * D(".999")
        cad_after_exit = D(result["accounting"]["cash_cad"])
        self.assertEqual(cad_after_exit, cad_before_exit + native_proceeds)
        self.assertEqual(D(result["cash"]), D("8000"))
        self.assertEqual(
            D(exit_event["realized_pnl"]), native_proceeds - D(position["cost"])
        )
        self.assertEqual(
            D(exit_event["asset_effect_usd"]) + D(exit_event["fx_effect_usd"]),
            D(exit_event["realized_pnl"]),
        )
        self.assertEqual(
            D(result["equity"]), (D("8000") + cad_after_exit).quantize(D(".01"))
        )
        self.assertEqual(result["equity"], result["cash_plus_marks"])

    def test_usd_cash_cannot_implicitly_fund_cad_entry(self):
        state, snapshot = self.signal(funded=False)
        result = advance(
            state,
            [snapshot],
            as_of="2026-10-26T22:00:00Z",
            bookkeeping=dict(fx=observation("2026-10-26")),
        )
        self.assertFalse(result["positions"])
        self.assertEqual(D(result["cash"]), D("10000"))
        self.assertEqual(D(result["accounting"]["cash_cad"]), D("0"))
        self.assertTrue(any(e["kind"] == "rejected" for e in result["events"]))


if __name__ == "__main__":
    unittest.main()
