"""Synthetic benchmark fixtures; expected returns are hand-computed."""

import copy
from decimal import Decimal
import unittest

from atlas.benchmarks import evaluate_benchmarks

D = Decimal
AS_OF = "2026-10-30T22:00:00Z"
DAYS = ["2026-10-26", "2026-10-27", "2026-10-28"]


def portfolio(values=(100, 95, 104.5), fx=None):
    rows = [dict(session=day, equity=str(value)) for day, value in zip(DAYS, values)]
    if fx:
        for row, value in zip(rows, fx):
            row["fx_usdcad"] = str(value)
    return rows


def benchmark(
    values=(100, 90, 99), *, currency="USD", return_type="TOTAL_RETURN", fx=None
):
    rows = [
        dict(session=day, value=str(value), available_at=day + "T21:00:00Z")
        for day, value in zip(DAYS, values)
    ]
    if fx:
        for row, value in zip(rows, fx):
            row["fx_usdcad"] = str(value)
    return dict(
        id="synthetic-broad",
        category="broad_equity",
        currency=currency,
        return_type=return_type,
        methodology="Synthetic reinvested distribution index",
        source={"name": "Synthetic fixture", "url": "https://example.invalid/index"},
        observations=rows,
    )


class BenchmarkHelpers:
    def evaluate(self, bench=None, rows=None, **kwargs):
        return evaluate_benchmarks(
            portfolio() if rows is None else rows,
            [benchmark() if bench is None else bench],
            as_of=AS_OF,
            **kwargs
        )[0]

    def assertMetric(self, row, name, expected):
        self.assertIsInstance(row[name], str)
        self.assertAlmostEqual(float(row[name]), expected, places=9)


class BenchmarkMetrics(BenchmarkHelpers, unittest.TestCase):
    def test_usd_metrics_use_sample_volatility_and_matched_downside_periods(self):
        row = self.evaluate()
        self.assertEqual(row["status"], "available")
        self.assertEqual(row["sessions"], DAYS)
        self.assertMetric(row, "local_return_pct", -1)
        self.assertMetric(row, "fx_return_pct", 0)
        self.assertMetric(row, "reporting_return_pct", -1)
        self.assertMetric(row, "portfolio_return_pct", 4.5)
        self.assertMetric(row, "relative_return_pct", 5.5)
        self.assertMetric(row, "max_drawdown_pct", 10)
        self.assertMetric(row, "annualized_volatility_pct", 224.4994432064365)
        self.assertMetric(row, "downside_capture_pct", 50)
        self.assertEqual(row["downside_periods"], 1)

    def test_fx_is_multiplicative_for_usd_benchmark_and_portfolio_in_cad(self):
        row = self.evaluate(
            benchmark((100, 110, 110), fx=(1.25, 1.5, 1.5)),
            portfolio((100, 110, 110), fx=(1.25, 1.5, 1.5)),
            report_currency="CAD",
        )
        self.assertMetric(row, "local_return_pct", 10)
        self.assertMetric(row, "fx_return_pct", 20)
        self.assertMetric(row, "reporting_return_pct", 32)
        self.assertMetric(row, "portfolio_return_pct", 32)
        self.assertMetric(row, "relative_return_pct", 0)

    def test_cad_benchmark_converts_to_usd_with_inverse_fx(self):
        row = self.evaluate(
            benchmark((100, 110, 110), currency="CAD", fx=(1.25, 1.5, 1.5))
        )
        self.assertMetric(row, "local_return_pct", 10)
        self.assertMetric(row, "fx_return_pct", -16.666666666666668)
        self.assertMetric(row, "reporting_return_pct", -8.333333333333334)
        self.assertMetric(row, "relative_return_pct", 12.833333333333334)

    def test_cad_benchmark_already_in_reporting_currency_needs_no_benchmark_fx(self):
        row = self.evaluate(
            benchmark(currency="CAD"),
            portfolio(fx=(1.25, 1.25, 1.25)),
            report_currency="CAD",
        )
        self.assertMetric(row, "fx_return_pct", 0)
        self.assertMetric(row, "reporting_return_pct", -1)

    def test_downside_capture_averages_only_matched_negative_benchmark_returns(self):
        p = portfolio((100, 80, 84)) + [dict(session="2026-10-29", equity="79.8")]
        b = benchmark((100, 90, 99))
        b["observations"].append(
            dict(
                session="2026-10-29", value="79.2", available_at="2026-10-29T21:00:00Z"
            )
        )
        row = self.evaluate(b, p)
        # Portfolio downside-period returns -20%, -5%; benchmark -10%, -20%.
        self.assertMetric(row, "downside_capture_pct", 83.33333333333333)
        self.assertEqual(row["downside_periods"], 2)
        self.assertMetric(row, "max_drawdown_pct", 20.8)

    def test_no_downside_and_one_period_volatility_are_unavailable(self):
        row = self.evaluate(benchmark((100, 110)), portfolio((100, 105)))
        self.assertEqual(row["status"], "available")
        self.assertIsNone(row["annualized_volatility_pct"])
        self.assertIsNone(row["downside_capture_pct"])
        self.assertIn(
            "no_negative_benchmark_periods",
            row["metric_reasons"]["downside_capture_pct"],
        )
        self.assertIn(
            "insufficient_periods", row["metric_reasons"]["annualized_volatility_pct"]
        )

    def test_decimal_inputs_do_not_mutate_and_results_are_json_safe(self):
        import json

        p, b = portfolio(), benchmark()
        p[0]["equity"] = D("100")
        b["observations"][0]["value"] = D("100")
        before = copy.deepcopy((p, b))
        json.dumps(self.evaluate(b, p), allow_nan=False)
        self.assertEqual((p, b), before)


class BenchmarkAvailability(BenchmarkHelpers, unittest.TestCase):
    def test_missing_middle_session_does_not_silently_shorten_period(self):
        b = benchmark()
        del b["observations"][1]
        row = self.evaluate(b)
        self.assertEqual(row["status"], "unavailable")
        self.assertIn("missing_sessions", row["reasons"])
        self.assertEqual(row["missing_sessions"], [DAYS[1]])
        self.assertIsNone(row["relative_return_pct"])

    def test_late_observation_cannot_leak_into_historical_comparison(self):
        b = benchmark()
        b["observations"][1]["available_at"] = "2026-10-31T01:00:00Z"
        row = self.evaluate(b)
        self.assertEqual(row["status"], "unavailable")
        self.assertIn("observations_not_yet_available", row["reasons"])
        self.assertIsNone(row["reporting_return_pct"])

    def test_future_unmatched_observation_does_not_block_available_history(self):
        b = benchmark()
        b["observations"].append(
            dict(session="2026-11-02", value="150", available_at="2026-11-02T22:00:00Z")
        )
        self.assertEqual(self.evaluate(b)["status"], "available")

    def test_return_type_mismatch_never_generates_relative_performance(self):
        row = self.evaluate(benchmark(return_type="PRICE_RETURN"))
        self.assertEqual(row["status"], "unavailable")
        self.assertIn("return_type_mismatch", row["reasons"])
        self.assertIsNone(row["relative_return_pct"])

    def test_matching_price_return_declarations_allow_comparison(self):
        row = self.evaluate(
            benchmark(return_type="PRICE_RETURN"), portfolio_return_type="PRICE_RETURN"
        )
        self.assertMetric(row, "relative_return_pct", 5.5)

    def test_missing_benchmark_conversion_fx_is_explicitly_unavailable(self):
        row = self.evaluate(benchmark(currency="CAD"))
        self.assertEqual(row["status"], "unavailable")
        self.assertIn("missing_benchmark_fx", row["reasons"])

    def test_missing_portfolio_conversion_fx_is_explicitly_unavailable(self):
        row = self.evaluate(benchmark(currency="CAD"), report_currency="CAD")
        self.assertEqual(row["status"], "unavailable")
        self.assertIn("missing_portfolio_fx", row["reasons"])

    def test_short_or_empty_history_never_claims_comparable_return(self):
        for rows in ([], portfolio((100,))):
            with self.subTest(rows=rows):
                row = self.evaluate(rows=rows)
                self.assertEqual(row["status"], "unavailable")
                self.assertIn("insufficient_history", row["reasons"])

    def test_category_and_registry_order_are_operator_selected(self):
        registry = []
        for category in (
            "thematic",
            "global_equity",
            "broad_equity",
            "operator_category",
        ):
            b = benchmark()
            b.update(id=category, category=category)
            registry.append(b)
        rows = evaluate_benchmarks(portfolio(), registry, as_of=AS_OF)
        self.assertEqual(
            [r["category"] for r in rows], [b["category"] for b in registry]
        )
        self.assertEqual([r["source"] for r in rows], [b["source"] for b in registry])


class BenchmarkValidation(unittest.TestCase):
    def reject(self, p=None, b=None, **kwargs):
        with self.assertRaises(ValueError):
            evaluate_benchmarks(
                portfolio() if p is None else p,
                [benchmark() if b is None else b],
                as_of=kwargs.pop("as_of", AS_OF),
                **kwargs
            )

    def test_nonfinite_zero_negative_and_non_numeric_values_are_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity", 0, -1, "abc", True, None):
            for field in ("equity", "value", "fx_usdcad"):
                with self.subTest(value=value, field=field):
                    p, b = portfolio(), benchmark()
                    if field == "equity":
                        p[1][field] = value
                    else:
                        b["observations"][1][field] = value
                    self.reject(p, b)

    def test_dates_must_be_strict_iso_sorted_and_unique(self):
        for sessions in (
            (DAYS[0], DAYS[0]),
            (DAYS[1], DAYS[0]),
            ("20261026", DAYS[1]),
            ("2026-02-30", DAYS[1]),
        ):
            for target in ("portfolio", "benchmark"):
                with self.subTest(sessions=sessions, target=target):
                    p, b = portfolio(), benchmark()
                    rows = p if target == "portfolio" else b["observations"]
                    rows[0]["session"], rows[1]["session"] = sessions
                    self.reject(p, b)

    def test_asof_and_availability_require_timezone(self):
        for value in ("2026-10-30", "2026-10-30T22:00:00", "bad", None):
            with self.subTest(value=value):
                self.reject(as_of=value)
                b = benchmark()
                b["observations"][1]["available_at"] = value
                self.reject(b=b)

    def test_portfolio_future_session_is_rejected(self):
        self.reject(as_of="2026-10-27T22:00:00Z")

    def test_availability_cannot_precede_observation_session(self):
        b = benchmark()
        b["observations"][1]["available_at"] = "2026-10-26T21:00:00Z"
        self.reject(b=b)

    def test_required_metadata_and_valid_declarations(self):
        for field in (
            "id",
            "category",
            "currency",
            "return_type",
            "methodology",
            "source",
            "observations",
        ):
            with self.subTest(field=field):
                b = benchmark()
                del b[field]
                self.reject(b=b)
        for field, value in (
            ("currency", "EUR"),
            ("return_type", "total"),
            ("source", {}),
            ("methodology", ""),
        ):
            b = benchmark()
            b[field] = value
            self.reject(b=b)
        self.reject(report_currency="EUR")
        self.reject(portfolio_return_type="unknown")

    def test_duplicate_registry_ids_cannot_ambiguously_label_results(self):
        with self.assertRaises(ValueError):
            evaluate_benchmarks(portfolio(), [benchmark(), benchmark()], as_of=AS_OF)

    def test_annualization_factor_is_a_positive_integer(self):
        for value in (0, -1, True, 252.5, "252"):
            with self.subTest(value=value):
                self.reject(periods_per_year=value)


class BenchmarkBaskets(BenchmarkHelpers, unittest.TestCase):
    def basket(self):
        b = benchmark()
        del b["observations"]
        b["methodology"] = "Fixed initial weights; buy and hold without rebalancing"
        b["components"] = [
            dict(
                id="synthetic-component-a",
                weight="0.5",
                observations=benchmark((100, 200, 100))["observations"],
            ),
            dict(
                id="synthetic-component-b",
                weight="0.5",
                observations=benchmark((200, 200, 400))["observations"],
            ),
        ]
        return b

    def test_fixed_weight_basket_holds_initial_units_and_does_not_rebalance(self):
        row = self.evaluate(self.basket())
        # Normalized levels 1, 1.5, 1.5. Daily 50/50 rebalancing would end at 1.875.
        self.assertMetric(row, "local_return_pct", 50)
        self.assertMetric(row, "reporting_return_pct", 50)
        self.assertMetric(row, "relative_return_pct", -45.5)
        self.assertEqual(row["construction"], "FIXED_WEIGHT_BUY_AND_HOLD")
        self.assertEqual(
            row["components"],
            [
                dict(id="synthetic-component-a", weight="0.5"),
                dict(id="synthetic-component-b", weight="0.5"),
            ],
        )

    def test_missing_component_date_blocks_whole_basket(self):
        b = self.basket()
        del b["components"][1]["observations"][1]
        row = self.evaluate(b)
        self.assertEqual(row["status"], "unavailable")
        self.assertEqual(row["missing_sessions"], [DAYS[1]])

    def test_initial_component_publication_time_applies_to_whole_basket(self):
        b = self.basket()
        b["components"][0]["observations"][0]["available_at"] = "2026-10-31T01:00:00Z"
        row = self.evaluate(b)
        self.assertEqual(row["status"], "unavailable")
        self.assertEqual(row["unavailable_sessions"], DAYS)

    def test_basket_converts_with_common_session_fx(self):
        b = self.basket()
        for c in b["components"]:
            for row, fx in zip(c["observations"], ("1.25", "1.5", "1.5")):
                row["fx_usdcad"] = fx
        row = self.evaluate(b, portfolio(fx=(1.25, 1.5, 1.5)), report_currency="CAD")
        self.assertMetric(row, "local_return_pct", 50)
        self.assertMetric(row, "fx_return_pct", 20)
        self.assertMetric(row, "reporting_return_pct", 80)

    def test_conflicting_component_fx_is_rejected(self):
        b = self.basket()
        for c in b["components"]:
            for row in c["observations"]:
                row["fx_usdcad"] = "1.25"
        b["components"][1]["observations"][1]["fx_usdcad"] = "1.30"
        with self.assertRaises(ValueError):
            self.evaluate(b, portfolio(fx=(1.25, 1.25, 1.25)), report_currency="CAD")

    def test_component_weights_ids_and_exclusive_construction_are_validated(self):
        for change in ("sum", "zero", "duplicate", "both", "empty", "unknown_currency"):
            with self.subTest(change=change):
                b = self.basket()
                if change == "sum":
                    b["components"][0]["weight"] = "0.4"
                elif change == "zero":
                    b["components"][0]["weight"] = "0"
                elif change == "duplicate":
                    b["components"][1]["id"] = b["components"][0]["id"]
                elif change == "both":
                    b["observations"] = benchmark()["observations"]
                elif change == "empty":
                    b["components"] = []
                else:
                    b["components"][0]["currency"] = "CAD"
                with self.assertRaises(ValueError):
                    self.evaluate(b)


class AdditionalBenchmarkValidation(BenchmarkHelpers, unittest.TestCase):
    def test_declarations_have_scalar_types(self):
        for key in ("currency", "return_type"):
            b = benchmark()
            b[key] = []
            with self.assertRaises(ValueError):
                self.evaluate(b)
        for key in ("report_currency", "portfolio_return_type"):
            with self.assertRaises(ValueError):
                self.evaluate(**{key: []})

    def test_iso_minute_timestamps_and_exact_cutoff_are_accepted(self):
        b = benchmark()
        b["observations"][-1]["available_at"] = "2026-10-30T18:00-04:00"
        row = self.evaluate(b)
        self.assertEqual(row["status"], "available")
        b["observations"][-1]["available_at"] = "2026-10-30T22:00Z"
        self.assertEqual(self.evaluate(b)["status"], "available")

    def test_caller_decimal_precision_does_not_change_results(self):
        from decimal import localcontext

        expected = self.evaluate()
        with localcontext() as context:
            context.prec = 5
            actual = self.evaluate()
        self.assertEqual(actual, expected)


class BenchmarkRegressionFixtures(BenchmarkHelpers, unittest.TestCase):
    def test_reporting_currency_determines_downside_periods(self):
        row = self.evaluate(
            benchmark((100, 90, 90), fx=(1, 2, 2)),
            portfolio((100, 95, 95), fx=(1, 2, 2)),
            report_currency="CAD",
        )
        self.assertMetric(row, "local_return_pct", -10)
        self.assertMetric(row, "reporting_return_pct", 80)
        self.assertEqual(row["downside_periods"], 0)
        self.assertIsNone(row["downside_capture_pct"])

    def test_flat_history_has_zero_risk_and_no_downside_capture(self):
        row = self.evaluate(benchmark((100, 100, 100)))
        self.assertMetric(row, "reporting_return_pct", 0)
        self.assertMetric(row, "annualized_volatility_pct", 0)
        self.assertMetric(row, "max_drawdown_pct", 0)
        self.assertIsNone(row["downside_capture_pct"])

    def test_one_unavailable_entry_does_not_block_other_valid_entries(self):
        unavailable, available = benchmark(return_type="PRICE_RETURN"), benchmark()
        unavailable["id"] = "synthetic-unavailable"
        rows = evaluate_benchmarks(portfolio(), [unavailable, available], as_of=AS_OF)
        self.assertEqual([row["status"] for row in rows], ["unavailable", "available"])
        self.assertTrue(
            all(
                rows[0][key] is None
                for key in (
                    "local_return_pct",
                    "fx_return_pct",
                    "reporting_return_pct",
                    "portfolio_return_pct",
                    "relative_return_pct",
                    "annualized_volatility_pct",
                    "max_drawdown_pct",
                    "downside_capture_pct",
                )
            )
        )
        self.assertMetric(rows[1], "relative_return_pct", 5.5)

    def test_returned_source_does_not_share_mutable_input_state(self):
        b = benchmark()
        result = self.evaluate(b)
        result["source"]["name"] = "changed returned copy"
        self.assertEqual(b["source"]["name"], "Synthetic fixture")

    def test_custom_annualization_factor_changes_sample_volatility(self):
        self.assertMetric(
            self.evaluate(periods_per_year=2), "annualized_volatility_pct", 20
        )

    def test_positive_portfolio_return_during_benchmark_decline_gives_negative_capture(
        self,
    ):
        row = self.evaluate(benchmark((100, 90, 99)), portfolio((100, 105, 105)))
        self.assertMetric(row, "downside_capture_pct", -50)

    def test_basket_precision_does_not_depend_on_caller_context(self):
        from decimal import localcontext

        b = benchmark()
        del b["observations"]
        b["components"] = [
            dict(
                id="synthetic-a",
                weight="0.3333333333333333333333333333333333333333",
                observations=benchmark((100, 110, 120))["observations"],
            ),
            dict(
                id="synthetic-b",
                weight="0.6666666666666666666666666666666666666667",
                observations=benchmark((100, 100, 100))["observations"],
            ),
        ]
        expected = self.evaluate(b)
        with localcontext() as context:
            context.prec = 5
            self.assertEqual(self.evaluate(b), expected)
