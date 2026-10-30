import copy
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class PublicContract(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads((ROOT / "examples" / "synthetic.json").read_text())

    def evaluate(self, snapshot=None, as_of="2026-10-23T22:00:00Z"):
        from atlas.core import evaluate_snapshot

        return evaluate_snapshot(snapshot or self.snapshot, as_of=as_of)

    def test_demo_is_deterministic_and_offline(self):
        from atlas.demo import run_demo

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            socket, "socket", side_effect=AssertionError("network")
        ):
            first = run_demo(Path(tmp))
            before = (Path(tmp) / "report.html").read_bytes()
            second = run_demo(Path(tmp))
            self.assertEqual(first, second)
            self.assertEqual(before, (Path(tmp) / "report.html").read_bytes())
            self.assertEqual(
                [r["status"] for r in first["results"]],
                ["RULES_PASS", "NO_TRADE", "NO_TRADE"],
            )
            self.assertTrue(all(r["mode"] == "RESEARCH_ONLY" for r in first["results"]))
            self.assertTrue(all(r["synthetic"] for r in first["results"]))

    def test_source_age_and_future_availability_fail_closed(self):
        self.assertEqual(
            self.evaluate(as_of="2026-10-30T22:00:00Z")["status"], "NO_TRADE"
        )
        self.snapshot["sources"][0]["available_at"] = "2026-10-24T00:00:00Z"
        self.assertEqual(self.evaluate()["status"], "NO_TRADE")

    def test_same_publisher_is_not_two_independent_sources(self):
        for source in self.snapshot["sources"]:
            source["publisher"] = "same publisher"
        self.assertEqual(self.evaluate()["status"], "NO_TRADE")

    def test_synthetic_cannot_be_relabelled_real_by_one_flag(self):
        self.snapshot["synthetic"] = False
        self.assertEqual(self.evaluate()["status"], "NO_TRADE")

    def test_empty_evidence_chain_blocks_even_if_claimed_complete(self):
        self.snapshot["context"]["chain"] = {}
        self.snapshot["context"]["chain_missing"] = []
        self.assertEqual(self.evaluate()["status"], "NO_TRADE")

    def test_invalid_prices_and_portfolio_rejected(self):
        from atlas.core import InputError

        for value in [0, -1, float("nan"), float("inf"), True]:
            with self.subTest(value=value):
                snap = copy.deepcopy(self.snapshot)
                snap["history"][-1]["c"] = value
                with self.assertRaises(InputError):
                    self.evaluate(snap)
        self.snapshot["context"]["portfolio"]["equity_usd"] = 0
        with self.assertRaises(InputError):
            self.evaluate()

    def test_duplicate_dates_and_inconsistent_ohlc_rejected(self):
        from atlas.core import InputError

        snap = copy.deepcopy(self.snapshot)
        snap["history"][-1]["d"] = snap["history"][-2]["d"]
        with self.assertRaises(InputError):
            self.evaluate(snap)
        self.snapshot["history"][-1]["h"] = 0.1
        with self.assertRaises(InputError):
            self.evaluate()

    def test_missing_fundamentals_do_not_crash_or_pass(self):
        self.snapshot["context"]["fund"] = {}
        self.assertEqual(self.evaluate()["status"], "NO_TRADE")

    def test_report_escapes_untrusted_names(self):
        from atlas.report import render_html

        result = self.evaluate()
        result["name"] = "<script>alert(1)</script>"
        rendered = render_html([result])
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_cli_rejects_bad_json_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{")
            proc = subprocess.run(
                [sys.executable, "-m", "atlas", "evaluate", str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertNotEqual(proc.stderr, "")


class AdditionalInputSafety(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads((ROOT / "examples/synthetic.json").read_text())

    def test_malformed_shapes_never_escape_as_tracebacks(self):
        from atlas.core import InputError, evaluate_snapshot

        mutations = [("subsector", []), ("focus_segment", {}), ("layer", [])]
        for key, value in mutations:
            with self.subTest(key=key):
                snap = copy.deepcopy(self.snapshot)
                snap["context"]["row"][key] = value
                with self.assertRaises(InputError):
                    evaluate_snapshot(snap, as_of="2026-10-23T22:00:00Z")

    def test_newer_history_than_source_blocks(self):
        from atlas.core import evaluate_snapshot

        self.snapshot["history"][-1]["d"] = "2026-10-24"
        self.assertEqual(
            evaluate_snapshot(self.snapshot, as_of="2026-10-23T22:00:00Z")["status"],
            "NO_TRADE",
        )

    def test_terminal_control_characters_rejected(self):
        from atlas.core import InputError, evaluate_snapshot

        self.snapshot["context"]["ticker"] = "\x1b[2J"
        with self.assertRaises(InputError):
            evaluate_snapshot(self.snapshot, as_of="2026-10-23T22:00:00Z")

    def test_shared_upstream_blocks_price_independence(self):
        from atlas.core import evaluate_snapshot

        for source in self.snapshot["sources"]:
            if source["role"] == "price":
                source["upstream"] = "same underlying feed"
        self.assertEqual(
            evaluate_snapshot(self.snapshot, as_of="2026-10-23T22:00:00Z")["status"],
            "NO_TRADE",
        )

    def test_missing_sources_are_no_trade(self):
        from atlas.core import evaluate_snapshot

        self.snapshot["sources"] = []
        self.snapshot["chain_sources"] = {}
        self.assertEqual(
            evaluate_snapshot(self.snapshot, as_of="2026-10-23T22:00:00Z")["status"],
            "NO_TRADE",
        )


class ReleaseCheck(unittest.TestCase):
    def test_detects_secret_and_private_term_without_printing_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            secret = "ghp_" + "a" * 36
            (folder / "README.md").write_text(secret + "\nprivate-demo-person")
            deny = folder / "deny.json"
            deny.write_text(json.dumps(["private-demo-person"]))
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release_check.py"),
                    "--root",
                    str(folder),
                    "--deny-file",
                    str(deny),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("FAIL", proc.stdout)
            self.assertNotIn(secret, proc.stdout + proc.stderr)
            self.assertNotIn("private-demo-person", proc.stdout + proc.stderr)


class ReviewRegressions(unittest.TestCase):
    def test_invalid_fundamental_domains_cannot_qualify(self):
        from atlas.core import InputError, evaluate_snapshot

        base = json.loads((ROOT / "examples/synthetic.json").read_text())
        for field, value in [
            ("net_income", True),
            ("ocf_all_positive_10y", [0]),
            ("pe", -100),
            ("ev_ebitda", -100),
            ("de", -100),
            ("sbc_to_fcf_3y", []),
            ("available", 1),
        ]:
            with self.subTest(field=field):
                snap = copy.deepcopy(base)
                snap["context"]["fund"][field] = value
                with self.assertRaises(InputError):
                    evaluate_snapshot(snap, as_of="2026-10-23T22:00:00Z")

    def test_extreme_inputs_report_boundary_error_without_traceback(self):
        base = json.loads((ROOT / "examples/synthetic.json").read_text())
        cases = [copy.deepcopy(base) for _ in range(3)]
        cases[0]["context"]["portfolio"]["equity_usd"] = 10**400
        cases[1]["history"][-1]["ac"] = 1e308
        cases[2]["sources"][0]["observed_at"] = "0001-01-01T00:00:00+01:00"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            for snap in cases:
                path.write_text(json.dumps(snap))
                proc = subprocess.run(
                    [sys.executable, "-m", "atlas", "evaluate", str(path)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc.returncode, 2)
                self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()


class PriceConsistency(unittest.TestCase):
    def test_real_price_source_value_disagreement_blocks(self):
        from atlas.core import evaluate_snapshot

        snap = json.loads((ROOT / "examples/synthetic.json").read_text())
        snap["synthetic"] = False
        for source in snap["sources"]:
            source.update(
                label="operator_attested",
                url="https://www.example.com/" + source["id"],
                content_sha256="a" * 64,
            )
            if source["role"] == "price":
                source["value"] = snap["history"][-1]["c"]
        snap["sources"][0]["value"] = 1
        self.assertEqual(
            evaluate_snapshot(snap, as_of="2026-10-23T22:00:00Z")["status"], "NO_TRADE"
        )


class EnvironmentTemplateCheck(unittest.TestCase):
    def test_empty_environment_template_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".env.example"
            path.write_text("ATLAS_SUPABASE_SECRET_KEY=\n")
            cmd = [sys.executable, str(ROOT / "tools/release_check.py"), "--root", tmp]
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            path.write_text("ATLAS_SUPABASE_SECRET_KEY=some-private-value\n")
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 1)


class ProjectEvidence(unittest.TestCase):
    def test_developer_focus_needs_explicit_dated_project_evidence(self):
        from atlas.core import evaluate_snapshot

        snap = json.loads((ROOT / "examples/synthetic.json").read_text())
        snap["context"]["row"]["focus_segment"] = "developer_financed_permitted"
        snap["context"]["row"]["financing_credible"] = True

        def focus():
            result = evaluate_snapshot(snap, as_of="2026-10-23T22:00:00Z")
            return next(c for c in result["checks"] if c["id"] == "C3")

        self.assertFalse(focus()["pass_"])
        refs = [s["id"] for s in snap["sources"] if s["role"] == "filing"]
        snap["context"]["project_evidence"] = {
            key: dict(credible=True, source_ids=refs)
            for key in ("financing", "permitting")
        }
        self.assertTrue(focus()["pass_"])
        snap["context"]["project_evidence"]["financing"]["source_ids"] = ["missing"]
        self.assertFalse(focus()["pass_"])
