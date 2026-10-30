import copy, json, tempfile, unittest
from pathlib import Path
from atlas.paper import initialize, advance
from atlas.storage import LocalStore, Conflict

ROOT = Path(__file__).resolve().parents[1]


class Paper(unittest.TestCase):
    def setUp(self):
        self.snap = json.loads((ROOT / "examples/synthetic.json").read_text())
        self.state = initialize("10000", synthetic=True)
        self.state["enabled"] = True

    def next(self):
        s = copy.deepcopy(self.snap)
        row = copy.deepcopy(s["history"][-1])
        row["d"] = "2026-10-26"
        row["c"] *= 1.03
        row["ac"] = row["c"]
        row["h"] = row["c"] * 1.005
        row["l"] = row["c"] * 0.985
        row["o"] = row["c"] * 0.99
        row["v"] *= 2
        s["history"].append(row)
        for p in s["sources"]:
            p["observed_at"] = "2026-10-26T20:00:00Z"
            p["available_at"] = "2026-10-26T21:00:00Z"
        return s

    def test_requires_explicit_enable(self):
        self.state["enabled"] = False
        r = advance(self.state, [self.snap], as_of="2026-10-23T22:00:00Z")
        self.assertFalse(r["pending"])
        self.assertFalse(r["positions"])

    def test_signal_then_later_session_fill_and_reconcile(self):
        a = advance(self.state, [self.snap], as_of="2026-10-23T22:00:00Z")
        self.assertEqual(len(a["pending"]), 1)
        self.assertFalse(a["positions"])
        b = advance(a, [self.next()], as_of="2026-10-26T22:00:00Z")
        self.assertEqual(len(b["positions"]), 1)
        self.assertEqual(b["equity"], b["cash_plus_marks"])
        self.assertLess(float(b["cash"]), 10000)

    def test_same_session_replay_is_identical(self):
        a = advance(self.state, [self.snap], as_of="2026-10-23T22:00:00Z")
        self.assertEqual(a, advance(a, [self.snap], as_of="2026-10-23T22:00:00Z"))

    def test_mixed_synthetic_rejected(self):
        self.state["synthetic"] = False
        with self.assertRaises(ValueError):
            advance(self.state, [self.snap], as_of="2026-10-23T22:00:00Z")

    def test_local_atomic_compare_and_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = LocalStore(Path(tmp) / "ledger.db")
            a.commit(0, "init", self.state)
            with self.assertRaises(Conflict):
                a.commit(0, "other", self.state)
            a.commit(0, "init", self.state)
            self.assertEqual(a.read()["revision"], 1)

    def test_missing_held_ticker_cannot_be_marked_as_cash(self):
        a = advance(self.state, [self.snap], as_of="2026-10-23T22:00:00Z")
        b = advance(a, [self.next()], as_of="2026-10-26T22:00:00Z")
        with self.assertRaises(ValueError):
            advance(b, [], as_of="2026-10-27T22:00:00Z")

    def test_gap_stop_exit_credits_cash_and_realized_pnl(self):
        a = advance(self.state, [self.snap], as_of="2026-10-23T22:00:00Z")
        b = advance(a, [self.next()], as_of="2026-10-26T22:00:00Z")
        s = self.next()
        row = copy.deepcopy(s["history"][-1])
        row.update(d="2026-10-27", o=80, h=82, l=78, c=81, ac=81)
        s["history"].append(row)
        for p in s["sources"]:
            p.update(
                observed_at="2026-10-27T20:00:00Z", available_at="2026-10-27T21:00:00Z"
            )
        c = advance(b, [s], as_of="2026-10-27T22:00:00Z")
        self.assertFalse(c["positions"])
        self.assertEqual(c["events"][-1]["kind"], "exit")
        self.assertLess(float(c["events"][-1]["realized_pnl"]), 0)
        self.assertEqual(c["equity"], c["cash_plus_marks"])

    def test_halt_cancels_pending_entry(self):
        a = advance(self.state, [self.snap], as_of="2026-10-23T22:00:00Z")
        a["halted"] = True
        b = advance(a, [self.next()], as_of="2026-10-26T22:00:00Z")
        self.assertFalse(b["positions"])
        self.assertFalse(b["pending"])

    def test_fees_never_allow_a_position_over_policy_weight(self):
        self.state["policy"] = {"max_initial_weight_pct": "1"}
        a = advance(self.state, [self.snap], as_of="2026-10-23T22:00:00Z")
        b = advance(a, [self.next()], as_of="2026-10-26T22:00:00Z")
        for p in b["positions"].values():
            self.assertLessEqual(float(p["cost"]), 100)

    def test_exchange_and_currency_are_explicit_for_real_ledgers(self):
        from atlas.paper import validate_market

        s = copy.deepcopy(self.snap)
        s["synthetic"] = False
        with self.assertRaises(ValueError):
            validate_market(s, "2026-10-23T22:00:00Z")

    def test_local_store_rejects_invalid_ledger(self):
        from atlas.paper import validate_state

        self.state["cash"] = "-1"
        with self.assertRaises(ValueError):
            validate_state(self.state)

    def test_cannot_skip_portfolio_sessions_and_lose_drawdown(self):
        a = advance(self.state, [self.snap], as_of="2026-10-23T22:00:00Z")
        b = advance(a, [self.next()], as_of="2026-10-26T22:00:00Z")
        s = self.next()
        for d, p in [("2026-10-27", 1000), ("2026-10-28", 110)]:
            s["history"].append(
                dict(d=d, o=p, h=p * 1.01, l=p * 0.99, c=p, ac=p, v=2000000, xok=True)
            )
        for p in s["sources"]:
            p.update(
                observed_at="2026-10-28T20:00:00Z", available_at="2026-10-28T21:00:00Z"
            )
        with self.assertRaises(ValueError):
            advance(b, [s], as_of="2026-10-28T22:00:00Z")

    def test_projected_theme_exposure_blocks_entry(self):
        self.state["cash"] = "7558.33"
        self.state["positions"] = {
            "HELD": dict(
                shares=21,
                entry="116.27",
                entry_date="2026-10-26",
                stop="10",
                highest="116.27",
                cost="2441.67",
                layer="D",
                managed_through="2026-10-26",
            )
        }
        self.state["last_session"] = "2026-10-26"
        self.state["next_session"] = "2026-10-27"
        self.state["pending"] = {"DEMO-GRID": dict(session="2026-10-26")}
        s = self.next()
        r = copy.deepcopy(s["history"][-1])
        r["d"] = "2026-10-27"
        r["c"] *= 1.03
        r["ac"] = r["c"]
        r["h"] = r["c"] * 1.01
        r["l"] = r["c"] * 0.99
        r["o"] = r["c"]
        r["v"] *= 2
        s["history"].append(r)
        for p in s["sources"]:
            p.update(
                observed_at="2026-10-27T20:00:00Z", available_at="2026-10-27T21:00:00Z"
            )
        s["context"]["max_corr"] = 0.5
        held = copy.deepcopy(s)
        held["context"]["ticker"] = "HELD"
        held["history"][-1].update(o=116.27, h=117, l=115, c=116.27, ac=116.27)
        b = advance(self.state, [s, held], as_of="2026-10-27T22:00:00Z")
        self.assertNotIn("DEMO-GRID", b["positions"])

    def test_risk_includes_both_entry_and_exit_costs(self):
        self.state = initialize("100000", synthetic=True)
        self.state.update(enabled=True, fee_bps="0", slippage_bps="500")
        self.snap["context"]["score"] = 80
        a = advance(self.state, [self.snap], as_of="2026-10-23T22:00:00Z")
        s = self.next()
        s["context"]["score"] = 80
        b = advance(a, [s], as_of="2026-10-26T22:00:00Z")
        for p in b["positions"].values():
            self.assertLessEqual(
                float(p["cost"]) - float(p["stop"]) * 0.95 * p["shares"], 500
            )

    def test_invalid_decimal_capital_is_a_boundary_error(self):
        with self.assertRaises(ValueError):
            initialize("invalid")

    def test_end_of_day_drawdown_includes_entry_costs(self):
        self.state["peak"] = "11764"
        a = advance(self.state, [self.snap], as_of="2026-10-23T22:00:00Z")
        b = advance(a, [self.next()], as_of="2026-10-26T22:00:00Z")
        actual = 100 * (1 - float(b["equity"]) / float(b["peak"]))
        self.assertAlmostEqual(b["snapshots"][-1]["drawdown_pct"], actual, places=3)
        self.assertEqual(b["halted"], actual >= 15)
