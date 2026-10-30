import copy, json, unittest
from pathlib import Path
from atlas.paper import initialize, advance
from atlas.accounting import convert_cash, apply_actions, fx_mark, extra_assets

ROOT = Path(__file__).resolve().parents[1]


def fx(rate="1.25", day="2026-10-23"):
    return dict(
        rate=rate,
        observed_at=day + "T20:00:00Z",
        available_at=day + "T21:00:00Z",
        source="https://example.invalid/fx",
        synthetic=True,
    )


def held():
    s = initialize("10000", synthetic=True)
    s["cash"] = "9000"
    s["positions"] = {
        "DEMO-GRID": dict(
            shares=10,
            entry="100",
            stop="80",
            highest="100",
            cost="1000",
            layer="D",
            subsector="Grid",
            entry_date="2026-10-20",
            managed_through="2026-10-22",
        )
    }
    return s


def action(kind, **kw):
    return dict(
        id="event-1",
        kind=kind,
        source="https://example.invalid/event",
        available_at="2026-10-22T21:00:00Z",
        effective_date="2026-10-23",
        **kw
    )


class Accounting(unittest.TestCase):
    def test_conversion_posts_two_sleeves_without_creating_equity(self):
        s = initialize("10000", synthetic=True)
        fx_mark(s, fx(), as_of="2026-10-23T22:00:00Z")
        convert_cash(
            s,
            dict(id="fx-1", from_currency="USD", amount="1000", fee_bps="10"),
            day="2026-10-23",
        )
        self.assertEqual(__import__("decimal").Decimal(s["cash"]), 9000)
        self.assertEqual(
            __import__("decimal").Decimal(s["accounting"]["cash_cad"]),
            __import__("decimal").Decimal("1248.75"),
        )
        self.assertEqual(extra_assets(s), __import__("decimal").Decimal("999"))

    def test_fx_revaluation_does_not_convert_cash(self):
        s = initialize("10000", synthetic=True)
        fx_mark(s, fx("1.25"), as_of="2026-10-23T22:00:00Z")
        convert_cash(
            s,
            dict(id="fx-1", from_currency="USD", amount="1000", fee_bps="0"),
            day="2026-10-23",
        )
        fx_mark(s, fx("1.00", "2026-10-26"), as_of="2026-10-26T22:00:00Z")
        self.assertEqual(extra_assets(s), 1250)
        self.assertEqual(
            __import__("decimal").Decimal(s["accounting"]["cash_cad"]), 1250
        )
        self.assertEqual(__import__("decimal").Decimal(s["cash"]), 9000)

    def test_dividend_receivable_survives_sale_and_pays_once(self):
        s = held()
        a = action(
            "cash_dividend",
            ticker="DEMO-GRID",
            amount_per_share="1",
            currency="USD",
            pay_date="2026-10-26",
            withholding_rate="0.15",
        )
        apply_actions(s, [a], {}, day="2026-10-23", as_of="2026-10-23T22:00:00Z")
        self.assertEqual(extra_assets(s), __import__("decimal").Decimal("8.50"))
        s["positions"] = {}
        apply_actions(s, [], {}, day="2026-10-26", as_of="2026-10-26T22:00:00Z")
        self.assertEqual(s["cash"], "9008.50")
        apply_actions(s, [a], {}, day="2026-10-26", as_of="2026-10-26T22:00:00Z")
        self.assertEqual(s["cash"], "9008.50")

    def test_split_preserves_basis_and_adjusts_stops(self):
        s = held()
        apply_actions(
            s,
            [action("split", ticker="DEMO-GRID", ratio="2")],
            {},
            day="2026-10-23",
            as_of="2026-10-23T22:00:00Z",
        )
        p = s["positions"]["DEMO-GRID"]
        self.assertEqual(p["shares"], 20)
        self.assertEqual(p["stop"], "40")
        self.assertEqual(p["cost"], "1000")

    def test_changed_action_id_and_unknown_event_rejected(self):
        s = held()
        a = action("split", ticker="DEMO-GRID", ratio="2")
        apply_actions(s, [a], {}, day="2026-10-23", as_of="2026-10-23T22:00:00Z")
        a["ratio"] = "3"
        with self.assertRaises(ValueError):
            apply_actions(s, [a], {}, day="2026-10-23", as_of="2026-10-23T22:00:00Z")
        with self.assertRaises(ValueError):
            apply_actions(
                held(),
                [action("unknown", ticker="DEMO-GRID")],
                {},
                day="2026-10-23",
                as_of="2026-10-23T22:00:00Z",
            )

    def test_integrated_dividend_adds_receivable_to_equity_then_cash(self):
        s = held()
        snap = json.loads((ROOT / "examples/synthetic.json").read_text())
        a = action(
            "cash_dividend",
            ticker="DEMO-GRID",
            amount_per_share="1",
            currency="USD",
            pay_date="2026-10-26",
        )
        out = advance(
            s, [snap], as_of="2026-10-23T22:00:00Z", bookkeeping={"actions": [a]}
        )
        self.assertEqual(out["snapshots"][-1]["receivables_usd"], "10")
        self.assertAlmostEqual(
            float(out["equity"]), 9000 + 10 * snap["history"][-1]["c"] + 10, places=2
        )

    def test_integrated_conversion_counts_cad_cash_in_equity(self):
        s = initialize("10000", synthetic=True)
        snap = json.loads((ROOT / "examples/synthetic.json").read_text())
        out = advance(
            s,
            [snap],
            as_of="2026-10-23T22:00:00Z",
            bookkeeping={
                "fx": fx(),
                "conversions": [
                    dict(id="fx-1", from_currency="USD", amount="1000", fee_bps="0")
                ],
            },
        )
        self.assertEqual(out["equity"], "10000.00")
        self.assertEqual(float(out["cash"]), 9000)

    def test_native_cad_position_is_valued_once_at_fx(self):
        s = held()
        s["positions"]["DEMO-GRID"]["currency"] = "CAD"
        s["positions"]["DEMO-GRID"]["entry_fx"] = "0.8"
        fx_mark(s, fx(), as_of="2026-10-23T22:00:00Z")
        snap = json.loads((ROOT / "examples/synthetic.json").read_text())
        snap["market"] = dict(
            currency="CAD", exchange="TSX", fundamentals_currency="USD"
        )
        out = advance(s, [snap], as_of="2026-10-23T22:00:00Z", bookkeeping={"fx": fx()})
        self.assertAlmostEqual(
            float(out["equity"]), 9000 + snap["history"][-1]["c"] * 10 / 1.25, places=2
        )

    def test_reverse_split_requires_cash_in_lieu_for_fraction(self):
        s = held()
        s["positions"]["DEMO-GRID"]["shares"] = 3
        with self.assertRaises(ValueError):
            apply_actions(
                s,
                [action("split", ticker="DEMO-GRID", ratio="0.5")],
                {},
                day="2026-10-23",
                as_of="2026-10-23T22:00:00Z",
            )

    def test_symbol_change_preserves_position_basis(self):
        s = held()
        apply_actions(
            s,
            [action("symbol_change", ticker="DEMO-GRID", new_ticker="DEMO-NEW")],
            {},
            day="2026-10-23",
            as_of="2026-10-23T22:00:00Z",
        )
        self.assertNotIn("DEMO-GRID", s["positions"])
        self.assertEqual(s["positions"]["DEMO-NEW"]["cost"], "1000")

    def test_cash_merger_realizes_known_cash_consideration(self):
        s = held()
        apply_actions(
            s,
            [
                action(
                    "cash_merger",
                    ticker="DEMO-GRID",
                    cash_per_share="120",
                    currency="USD",
                )
            ],
            {},
            day="2026-10-23",
            as_of="2026-10-23T22:00:00Z",
        )
        self.assertFalse(s["positions"])
        self.assertEqual(float(s["cash"]), 10200)
        self.assertEqual(float(s["events"][-1]["realized_pnl"]), 200)

    def test_spin_off_allocates_basis_without_creating_cash(self):
        s = held()
        apply_actions(
            s,
            [
                action(
                    "spin_off",
                    ticker="DEMO-GRID",
                    new_ticker="DEMO-CHILD",
                    ratio="0.5",
                    stock_basis_fraction="0.2",
                    new_reference_price="40",
                    new_stop="30",
                )
            ],
            {},
            day="2026-10-23",
            as_of="2026-10-23T22:00:00Z",
        )
        self.assertEqual(s["positions"]["DEMO-CHILD"]["shares"], 5)
        self.assertEqual(float(s["positions"]["DEMO-CHILD"]["cost"]), 200)
        self.assertEqual(float(s["positions"]["DEMO-GRID"]["cost"]), 800)

    def test_late_action_cannot_rewrite_prior_entitlement(self):
        with self.assertRaises(ValueError):
            apply_actions(
                held(),
                [action("split", ticker="DEMO-GRID", ratio="2")],
                {},
                day="2026-10-26",
                as_of="2026-10-26T22:00:00Z",
            )

    def test_same_date_actions_require_explicit_order(self):
        s = held()
        actions = [
            action("split", ticker="DEMO-GRID", ratio="2"),
            dict(
                action(
                    "cash_dividend",
                    ticker="DEMO-GRID",
                    amount_per_share="1",
                    currency="USD",
                    pay_date="2026-10-26",
                ),
                id="second",
            ),
        ]
        with self.assertRaises(ValueError):
            apply_actions(
                s, actions, {}, day="2026-10-23", as_of="2026-10-23T22:00:00Z"
            )

    def test_child_does_not_inherit_parent_exit_order(self):
        s = held()
        s["positions"]["DEMO-GRID"]["queued_exit"] = "parent trend broke"
        apply_actions(
            s,
            [
                action(
                    "spin_off",
                    ticker="DEMO-GRID",
                    new_ticker="DEMO-CHILD",
                    ratio="0.5",
                    stock_basis_fraction="0.2",
                    new_reference_price="40",
                    new_stop="30",
                )
            ],
            {},
            day="2026-10-23",
            as_of="2026-10-23T22:00:00Z",
        )
        self.assertNotIn("queued_exit", s["positions"]["DEMO-CHILD"])

    def test_missing_merger_consideration_never_writes_off(self):
        with self.assertRaises(ValueError):
            apply_actions(
                held(),
                [action("cash_merger", ticker="DEMO-GRID", currency="USD")],
                {},
                day="2026-10-23",
                as_of="2026-10-23T22:00:00Z",
            )

    def test_split_history_needs_explicit_basis_and_normalizes_raw(self):
        from atlas.accounting import normalized_history

        s = held()
        apply_actions(
            s,
            [action("split", ticker="DEMO-GRID", ratio="2")],
            {},
            day="2026-10-23",
            as_of="2026-10-23T22:00:00Z",
        )
        snap = {
            "context": {"ticker": "DEMO-GRID"},
            "history": [
                dict(d="2026-10-22", o=100, h=110, l=90, c=100, ac=100, v=10),
                dict(d="2026-10-23", o=50, h=55, l=45, c=50, ac=50, v=20),
            ],
        }
        with self.assertRaises(ValueError):
            normalized_history(s, snap)
        snap["market"] = {"history_basis": "raw"}
        result = normalized_history(s, snap)
        self.assertEqual(result["history"][0]["c"], 50)
        self.assertEqual(result["history"][0]["v"], 20)
        self.assertEqual(snap["history"][0]["c"], 100)
        result["market"]["history_basis"] = "split_adjusted"
        self.assertEqual(normalized_history(s, result)["history"], result["history"])

    def test_currency_mismatch_blocks_mark(self):
        s = held()
        s["positions"]["DEMO-GRID"]["currency"] = "CAD"
        fx_mark(s, fx(), as_of="2026-10-23T22:00:00Z")
        snap = json.loads((ROOT / "examples/synthetic.json").read_text())
        with self.assertRaisesRegex(ValueError, "currency changed"):
            advance(s, [snap], as_of="2026-10-23T22:00:00Z", bookkeeping={"fx": fx()})

    def test_equivalent_timestamp_cannot_replace_fx(self):
        s = initialize("10000", synthetic=True)
        obs = fx()
        fx_mark(s, obs, as_of="2026-10-23T22:00:00Z")
        obs = dict(obs, observed_at="2026-10-23T20:00:00+00:00", rate="1.30")
        with self.assertRaisesRegex(ValueError, "Conflicting FX"):
            fx_mark(s, obs, as_of="2026-10-23T22:00:00Z")

    def test_saved_negative_cad_balance_is_rejected(self):
        from atlas.paper import validate_state

        s = initialize("10000", synthetic=True)
        fx_mark(s, fx(), as_of="2026-10-23T22:00:00Z")
        s["accounting"]["cash_cad"] = "-1250"
        with self.assertRaises(ValueError):
            validate_state(s)

    def test_reorganization_resets_child_currency_fx(self):
        s = held()
        fx_mark(s, fx(), as_of="2026-10-23T22:00:00Z")
        apply_actions(
            s,
            [
                action(
                    "spin_off",
                    ticker="DEMO-GRID",
                    new_ticker="DEMO-CHILD",
                    ratio="1",
                    stock_basis_fraction=".2",
                    new_reference_price="25",
                    new_stop="20",
                    new_currency="CAD",
                )
            ],
            {},
            day="2026-10-23",
            as_of="2026-10-23T22:00:00Z",
        )
        self.assertEqual(s["positions"]["DEMO-CHILD"]["entry_fx"], "0.8")

    def test_usd_benchmark_can_be_registered_without_fx(self):
        from atlas.portfolio_report import build_report

        s = initialize("10000", synthetic=True)
        snap = json.loads((ROOT / "examples/synthetic.json").read_text())
        b = dict(
            id="demo-index",
            category="broad",
            currency="USD",
            return_type="TOTAL_RETURN",
            methodology="synthetic index",
            source="https://example.invalid/index",
            observations=[
                dict(
                    session="2026-10-23",
                    value="100",
                    available_at="2026-10-23T21:00:00Z",
                )
            ],
        )
        s = advance(
            s, [snap], as_of="2026-10-23T22:00:00Z", bookkeeping={"benchmarks": [b]}
        )
        report = build_report(s, week="2026-10-19", as_of="2026-10-26T22:00:00Z")
        self.assertEqual(report["benchmarks"][0]["status"], "unavailable")
        self.assertIn(
            "distribution_coverage_unverified", report["benchmarks"][0]["reasons"]
        )

    def test_roc_above_basis_records_only_excess_gain(self):
        s = held()
        apply_actions(
            s,
            [
                action(
                    "return_of_capital",
                    ticker="DEMO-GRID",
                    amount_per_share="120",
                    currency="USD",
                    pay_date="2026-10-23",
                )
            ],
            {},
            day="2026-10-23",
            as_of="2026-10-23T22:00:00Z",
        )
        self.assertEqual(float(s["positions"]["DEMO-GRID"]["cost"]), 0)
        self.assertEqual(
            sum(float(e.get("realized_pnl", "0")) for e in s["events"]), 200
        )

    def test_weekly_cad_return_uses_both_endpoint_fx_rates(self):
        from atlas.portfolio_report import build_report

        s = initialize("10000", synthetic=True)
        s["snapshots"] = [
            dict(session="2026-10-16", equity="10000", fx_usdcad="1.25"),
            dict(
                session="2026-10-23",
                equity="11000",
                fx_usdcad="1.30",
                cash="11000",
                positions_state={},
            ),
        ]
        s["next_session"] = "2026-10-26"
        r = build_report(
            s, week="2026-10-19", as_of="2026-10-26T22:00:00Z", report_currency="CAD"
        )
        self.assertAlmostEqual(r["weekly_return_pct"], 14.4)
        self.assertAlmostEqual(r["weekly_return_usd_pct"], 10)


class CommitteeSymbolMigration(unittest.TestCase):
    def test_symbol_change_retains_issuer_committee_and_vetoes(self):
        s = held()
        s["committees"] = {
            "DEMO-GRID": {
                "config": {"immutable": "registry"},
                "votes": {"vetoes": [{"id": "risk-event"}]},
            }
        }
        original = copy.deepcopy(s["committees"]["DEMO-GRID"])
        apply_actions(
            s,
            [action("symbol_change", ticker="DEMO-GRID", new_ticker="DEMO-NEW")],
            {},
            day="2026-10-23",
            as_of="2026-10-23T22:00:00Z",
        )
        self.assertNotIn("DEMO-GRID", s["committees"])
        self.assertEqual(s["committees"]["DEMO-NEW"], original)
