import copy, json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Worker(unittest.TestCase):
    def test_cli_initialize_mode_daily_report_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "book.db")
            out = str(Path(tmp) / "report")

            def run(*args):
                p = subprocess.run(
                    [sys.executable, "-m", "atlas", "paper", "--ledger", db, *args],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(p.returncode, 0, p.stderr)
                return p

            run("init", "--capital", "25000", "--synthetic")
            run("enable")
            run(
                "run",
                "--as-of",
                "2026-10-23T22:00:00Z",
                str(ROOT / "examples/synthetic.json"),
            )
            run(
                "run",
                "--as-of",
                "2026-10-23T22:00:00Z",
                str(ROOT / "examples/synthetic.json"),
            )
            run("report", "--week", "2026-10-19", "--output", out)
            self.assertTrue((Path(out) / "report.html").exists())
            self.assertTrue((Path(out) / "report.txt").exists())
            self.assertFalse(
                json.loads((Path(out) / "send_manifest.json").read_text())[
                    "send_allowed"
                ]
            )
            status = json.loads(run("status").stdout)
            self.assertEqual(status["state"]["currency"], "USD")

    def test_report_does_not_invent_missing_week_return(self):
        from atlas.paper import initialize
        from atlas.portfolio_report import build_report

        data = build_report(initialize("10000"), week="2026-10-19")
        self.assertIsNone(data["weekly_return_pct"])
        self.assertFalse(data["send_allowed"])

    def test_unconfirmed_send_cannot_release_duplicate_guard(self):
        from atlas.paper import initialize
        from atlas.portfolio_report import reserve_delivery

        state = initialize("10000")
        with self.assertRaises(ValueError):
            reserve_delivery(state, "2026-10-19", "a" * 64)

    def test_completed_friday_week_is_reportable_on_monday(self):
        from atlas.paper import initialize
        from atlas.portfolio_report import build_report

        state = initialize("10000")
        state.update(
            last_session="2026-10-23",
            next_session="2026-10-26",
            dispatch_enabled=True,
            dispatch_hold=False,
        )
        state["snapshots"] = [
            dict(session="2026-10-16", equity="10000"),
            dict(session="2026-10-23", equity="10100"),
        ]
        report = build_report(state, week="2026-10-19", as_of="2026-10-26T07:00:00Z")
        self.assertAlmostEqual(report["weekly_return_pct"], 1)
        self.assertTrue(report["send_allowed"])

    def test_paper_demo_signals_fills_and_exits_in_temporary_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, "-m", "atlas", "paper-demo", "--output", tmp],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            state = json.loads((Path(tmp) / "ledger.json").read_text())
            self.assertEqual([e["kind"] for e in state["events"]], ["entry", "exit"])
            self.assertTrue(state["synthetic"])
            self.assertFalse(state["positions"])

    def test_reserved_report_cannot_be_reserved_twice(self):
        from atlas.paper import initialize
        from atlas.portfolio_report import reserve_delivery

        state = initialize("10000")
        state.update(
            last_session="2026-10-23",
            next_session="2026-10-26",
            dispatch_enabled=True,
            dispatch_hold=False,
        )
        state["snapshots"] = [dict(session="2026-10-23", equity="10000")]
        reserved = reserve_delivery(state, "2026-10-19", "a" * 64)
        with self.assertRaises(ValueError):
            reserve_delivery(reserved, "2026-10-19", "a" * 64)

    def test_old_week_does_not_report_future_balances(self):
        from atlas.paper import initialize
        from atlas.portfolio_report import build_report

        state = initialize("10000")
        state.update(
            equity="15000",
            cash="15000",
            last_session="2026-11-03",
            next_session="2026-11-04",
        )
        state["snapshots"] = [
            dict(
                session="2026-10-16", equity="10000", cash="10000", positions_state={}
            ),
            dict(
                session="2026-10-23", equity="10100", cash="10100", positions_state={}
            ),
            dict(
                session="2026-11-03", equity="15000", cash="15000", positions_state={}
            ),
        ]
        report = build_report(state, week="2026-10-19", as_of="2026-11-04T22:00:00Z")
        self.assertEqual(report["equity"], "10100")
        self.assertEqual(report["cash"], "10100")
        self.assertEqual(report["last_session"], "2026-10-23")

    def test_cli_initial_risk_settings_cannot_loosen_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "atlas",
                    "paper",
                    "--ledger",
                    str(Path(tmp) / "book.db"),
                    "init",
                    "--capital",
                    "10000",
                    "--max-initial-weight-pct",
                    "50",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn("Traceback", proc.stderr)
