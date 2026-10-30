import unittest
from unittest.mock import patch
from atlas import research_data as r


def fact(value, end="2024-12-31", filed="2025-02-01", **kw):
    return dict(val=value, end=end, filed=filed, form="10-K", accn="example", **kw)


class ResearchDataTests(unittest.TestCase):
    def test_annual_currency_and_hindsight(self):
        rows = [
            fact(100, start="2024-01-01"),
            fact(999, filed="2026-02-01", start="2024-01-01"),
            fact(8, start="2024-10-01"),
        ]
        data = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {"USD": rows, "CAD": [fact(777, start="2024-01-01")]}
                    }
                }
            }
        }
        out = r.extract_companyfacts(data, as_of="2025-03-01T00:00:00Z")
        self.assertEqual(out["series"]["revenue"], {"2024-12-31": 100})
        self.assertEqual(
            out["provenance"]["revenue"]["2024-12-31"]["filed"], "2025-02-01"
        )
        self.assertIsNone(out["metrics"]["fcf"])
        self.assertEqual(
            r.extract_companyfacts(data, as_of="2025-02-01T12:00:00Z")["series"][
                "revenue"
            ],
            {},
        )

    def test_aligned_metrics_and_missing_not_zero(self):
        flows = {
            "Revenues": 100,
            "OperatingIncomeLoss": 20,
            "NetIncomeLoss": 10,
            "NetCashProvidedByUsedInOperatingActivities": 18,
            "PaymentsToAcquirePropertyPlantAndEquipment": 5,
        }
        facts = {
            k: {"units": {"USD": [fact(v, start="2024-01-01")]}}
            for k, v in flows.items()
        }
        facts["CashAndCashEquivalentsAtCarryingValue"] = {"units": {"USD": [fact(30)]}}
        facts["LongTermDebt"] = {"units": {"USD": [fact(10)]}}
        facts["WeightedAverageNumberOfDilutedSharesOutstanding"] = {
            "units": {"shares": [fact(10, start="2024-01-01")]}
        }
        out = r.extract_companyfacts(
            {"facts": {"us-gaap": facts}}, as_of="2025-03-01T00:00:00Z", price=10
        )
        self.assertEqual(out["metrics"]["fcf"], 13)
        self.assertEqual(out["metrics"]["ev"], 80)
        self.assertIsNone(out["metrics"]["div_yield"])
        facts["CashAndCashEquivalentsAtCarryingValue"]["units"]["USD"] = [
            fact(40, end="2025-12-31", filed="2026-02-01")
        ]
        out = r.extract_companyfacts(
            {"facts": {"us-gaap": facts}}, as_of="2026-03-01T00:00:00Z", price=10
        )
        self.assertIsNone(out["metrics"]["ev"])

    def test_filing(self):
        out = r.scan_filing(
            "<p>Substantial doubt about continuing as a going concern.</p>",
            filed="2025-02-01",
            as_of="2025-02-02T00:00:00Z",
        )
        self.assertIn("going_concern", out["flags"])
        self.assertEqual(out["status"], "heuristic_scan")
        with self.assertRaises(ValueError):
            r.scan_filing("text", filed="2025-02-02", as_of="2025-02-02T12:00:00Z")

    def test_network_boundary(self):
        for url in [
            "http://www.sec.gov/Archives/edgar/data/1/a.htm",
            "https://evil.test/a",
            "https://www.sec.gov.evil.test/Archives/edgar/data/a",
            "https://www.sec.gov/Archives/edgar/data/../a",
        ]:
            with self.assertRaises(ValueError):
                r.fetch_filing(url)
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                r.fetch_companyfacts("123")
        with patch.dict(
            "os.environ", {"SEC_USER_AGENT": "Example Research contact@example.org"}
        ), patch.object(r, "_fetch", return_value=b"<p>hello</p>"):
            self.assertEqual(
                r.fetch_filing("https://www.sec.gov/Archives/edgar/data/1/2/a.htm")[
                    "text"
                ],
                "<p>hello</p>",
            )

    def test_regime(self):
        from datetime import date, timedelta

        end = date(2025, 6, 30)
        ry = [
            {"date": (end - timedelta(days=63 - i)).isoformat(), "value": 1 + i * 0.01}
            for i in range(64)
        ]
        payload = dict(
            retrieved_at="2025-07-01T00:00:00Z",
            real_yield=ry,
            industrial_production=[
                {"date": d, "value": v}
                for d, v in [
                    ("2025-03-01", 100),
                    ("2025-04-01", 99),
                    ("2025-05-01", 98),
                    ("2025-06-01", 97),
                ]
            ],
        )
        out = r.evaluate_regime(payload, as_of="2025-07-01T01:00:00Z")
        self.assertTrue(out["known"])
        self.assertTrue(out["adverse"])
        self.assertFalse(out["historical_vintage_verified"])
        self.assertFalse(
            r.evaluate_regime(payload, as_of="2025-06-01T00:00:00Z")["known"]
        )
        self.assertTrue(r.evaluate_regime({}, as_of="2025-07-01T00:00:00Z")["adverse"])

    def test_regime_rejects_observations_after_retrieval(self):
        from datetime import date, timedelta

        end = date(2025, 6, 30)
        payload = dict(
            retrieved_at="2025-06-01T00:00:00Z",
            real_yield=[
                {"date": (end - timedelta(days=63 - i)).isoformat(), "value": i}
                for i in range(64)
            ],
            industrial_production=[
                {"date": d, "value": v}
                for d, v in [
                    ("2025-03-01", 100),
                    ("2025-04-01", 99),
                    ("2025-05-01", 98),
                    ("2025-06-01", 97),
                ]
            ],
        )
        self.assertFalse(
            r.evaluate_regime(payload, as_of="2025-07-01T00:00:00Z")["known"]
        )

    def test_debt_prefers_combined_and_adds_separate_short_term(self):
        def payload(combined=True):
            tags = {
                "Revenues": {"units": {"USD": [fact(100, start="2024-01-01")]}},
                "LongTermDebt": {"units": {"USD": [fact(100)]}},
                "ShortTermBorrowings": {"units": {"USD": [fact(50)]}},
                "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [fact(10)]}},
            }
            if combined:
                tags["DebtLongtermAndShorttermCombinedAmount"] = {
                    "units": {"USD": [fact(150)]}
                }
            return {"facts": {"us-gaap": tags}}

        for combined in (True, False):
            metrics = r.extract_companyfacts(
                payload(combined), as_of="2025-03-01T00:00:00Z"
            )["metrics"]
            self.assertEqual(metrics["debt"], 150)
            self.assertEqual(metrics["net_debt"], 140)

    def test_three_year_metrics_need_consecutive_anchor(self):
        series = {
            k: {end: value for end in ("2019-12-31", "2021-12-31", "2023-12-31")}
            for k, value in [
                ("ocf", 20),
                ("capex", 5),
                ("net_income", 10),
                ("equity", 50),
                ("sbc", 1),
            ]
        }
        series["revenue"] = {"2024-12-31": 100}
        metrics = r.derive_metrics(series)
        for key in ("fcf_avg3", "roe3", "sbc_to_fcf_3y"):
            self.assertIsNone(metrics[key])
        for field in ("ocf", "capex", "net_income", "equity", "sbc"):
            value = next(iter(series[field].values()))
            series[field] = {
                end: value for end in ("2022-12-31", "2023-12-31", "2024-12-31")
            }
        metrics = r.derive_metrics(series)
        self.assertEqual(metrics["fcf_avg3"], 15)
        self.assertAlmostEqual(metrics["roe3"], 0.2)
        self.assertEqual(metrics["sbc_to_fcf_3y"], [1 / 15] * 3)

    def test_sign_sensitive_facts_reject_negative(self):
        for tag in (
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "LongTermDebt",
            "CashAndCashEquivalentsAtCarryingValue",
            "WeightedAverageNumberOfDilutedSharesOutstanding",
        ):
            unit = "shares" if tag.startswith("Weighted") else "USD"
            row = fact(-500, start="2024-01-01")
            with self.assertRaises(ValueError):
                r.extract_companyfacts(
                    {"facts": {"us-gaap": {tag: {"units": {unit: [row]}}}}},
                    as_of="2025-03-01T00:00:00Z",
                )
        out = r.extract_companyfacts(
            {
                "facts": {
                    "us-gaap": {
                        "NetIncomeLoss": {
                            "units": {"USD": [fact(-10, start="2024-01-01")]}
                        },
                        "StockholdersEquity": {"units": {"USD": [fact(-20)]}},
                    }
                }
            },
            as_of="2025-03-01T00:00:00Z",
        )
        self.assertEqual(out["series"]["net_income"]["2024-12-31"], -10)
        self.assertEqual(out["series"]["equity"]["2024-12-31"], -20)

    def test_companyfacts_schema_errors_are_value_errors(self):
        invalid = [
            [],
            {"facts": []},
            {"facts": {"us-gaap": []}},
            {"facts": {"us-gaap": {"Revenues": []}}},
            {"facts": {"us-gaap": {"Revenues": {"units": []}}}},
            {"facts": {"us-gaap": {"Revenues": {"units": {"USD": {}}}}}},
            {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [42]}}}}},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                r.extract_companyfacts(payload, as_of="2025-03-01T00:00:00Z")

    def test_industrial_production_nonpositive_is_unknown(self):
        from datetime import date, timedelta

        end = date(2025, 6, 30)
        payload = dict(
            retrieved_at="2025-07-01T00:00:00Z",
            real_yield=[
                {
                    "date": (end - timedelta(days=63 - i)).isoformat(),
                    "value": -1 + i * 0.01,
                }
                for i in range(64)
            ],
            industrial_production=[
                {"date": d, "value": v}
                for d, v in [
                    ("2025-03-01", 100),
                    ("2025-04-01", 99),
                    ("2025-05-01", 98),
                    ("2025-06-01", 97),
                ]
            ],
        )
        self.assertTrue(
            r.evaluate_regime(payload, as_of="2025-07-01T01:00:00Z")["known"]
        )
        for bad in (0, -1):
            payload["industrial_production"][1]["value"] = bad
            self.assertFalse(
                r.evaluate_regime(payload, as_of="2025-07-01T01:00:00Z")["known"]
            )
