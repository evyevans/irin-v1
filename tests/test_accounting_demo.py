import json, tempfile, unittest
from pathlib import Path
from atlas.accounting_demo import run


class AccountingDemo(unittest.TestCase):
    def test_demo_persists_distribution_split_merger_and_cash_sleeves(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = run(tmp)
            self.assertEqual(json.loads((Path(tmp) / "ledger.json").read_text()), state)
            self.assertFalse(state["positions"])
            self.assertEqual(
                state["accounting"]["receivables"]["demo-dividend"]["net"], "8.50"
            )
            self.assertTrue(state["accounting"]["receivables"]["demo-dividend"]["paid"])
            self.assertTrue(json.loads((Path(tmp) / "audit.json").read_text())["valid"])
            report = json.loads((Path(tmp) / "report.json").read_text())
            self.assertEqual(report["reporting_currency"], "CAD")
            self.assertEqual(float(report["distribution_income_usd"]), 8.5)
            self.assertEqual(report["benchmarks"][0]["status"], "unavailable")
            self.assertIn("period_incomplete", report["benchmarks"][0]["reasons"])
