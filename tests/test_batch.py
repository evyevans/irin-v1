import argparse
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from atlas.batch import add_commands, evaluate_batch, execute
from atlas.core import InputError

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-10-23T22:00:00Z"


def snapshot(ticker="DEMO-PEER", *, held=0):
    value = json.loads((ROOT / "examples/synthetic.json").read_text())
    value["context"]["ticker"] = ticker
    value["context"]["name"] = "Synthetic peer"
    value["context"]["portfolio"]["open_positions"] = held
    return value


class Batch(unittest.TestCase):
    def test_full_universe_thresholds_replace_claimed_context_without_mutation(self):
        universe = []
        for i in range(1, 11):
            peer = snapshot("DEMO-%02d" % i)
            peer["context"]["fund"]["ev_ebitda"] = i
            if i <= 5:
                peer["context"]["row"]["subsector"] = "Regulated utility"
            peer["context"]["val_stats"] = {"ev_ebitda_p90": 99999}
            peer["context"]["max_corr"] = 0.99
            universe.append(peer)
        original = copy.deepcopy(universe)
        result = evaluate_batch(universe, held=[], as_of=AS_OF)
        self.assertEqual(result["val_stats"]["ev_ebitda_p90"], 9)
        self.assertEqual(result["val_stats"]["median_ev_ebitda"]["utility_ipp"], 3)
        self.assertEqual(result["peer_counts"]["vol260"], 10)
        self.assertIsNotNone(result["val_stats"]["vol260_median"])
        self.assertEqual(len(result["results"]), 10)
        self.assertTrue(all(not r["execution_enabled"] for r in result["results"]))
        self.assertEqual(universe, original)
        # Changing caller-claimed derived data cannot influence actual evaluation.
        for peer in universe:
            peer["context"]["val_stats"] = {"ev_ebitda_p90": -1}
            peer["context"]["max_corr"] = -1
        again = evaluate_batch(universe, held=[], as_of=AS_OF)
        self.assertEqual(result["results"], again["results"])

    def test_sparse_peer_samples_stay_unavailable(self):
        result = evaluate_batch([snapshot()], held=[], as_of=AS_OF)
        self.assertIsNone(result["val_stats"]["ev_ebitda_p90"])
        self.assertIsNone(result["val_stats"]["vol260_median"])
        self.assertIsNone(result["correlations"]["DEMO-PEER"]["max_corr"])

    def test_correlations_match_intervals_and_missing_peer_fails_closed(self):
        candidate, peer = snapshot("DEMO-CANDIDATE", held=1), snapshot(
            "DEMO-HELD", held=1
        )
        first, second = 100.0, 100.0
        for i, (a, b) in enumerate(zip(candidate["history"], peer["history"])):
            change = (0.01, -0.02, 0.015, -0.005)[i % 4]
            first *= 1 + change
            second *= 1 - change
            a["ac"], b["ac"] = first, second
        result = evaluate_batch([candidate, peer], held=["DEMO-HELD"], as_of=AS_OF)
        self.assertAlmostEqual(result["correlations"]["DEMO-CANDIDATE"]["max_corr"], -1)
        pair = result["correlations"]["DEMO-CANDIDATE"]["pairs"][0]
        self.assertEqual(pair["matched_intervals"], 252)
        # Removing alternate bars makes two-session returns. They cannot be
        # paired with daily returns merely because their ending dates match.
        last = peer["history"][-1]
        peer["history"] = peer["history"][::2]
        if peer["history"][-1]["d"] != last["d"]:
            peer["history"].append(last)
        result = evaluate_batch([candidate, peer], held=["DEMO-HELD"], as_of=AS_OF)
        self.assertIsNone(result["correlations"]["DEMO-CANDIDATE"]["max_corr"])
        self.assertLess(
            result["correlations"]["DEMO-CANDIDATE"]["pairs"][0]["matched_intervals"],
            60,
        )
        with self.assertRaises(InputError):
            evaluate_batch([candidate], held=["DEMO-HELD"], as_of=AS_OF)

    def test_unavailable_source_cannot_contaminate_peer_thresholds(self):
        universe = [snapshot("DEMO-%02d" % i) for i in range(10)]
        for peer in universe:
            peer["context"]["fund"]["ev_ebitda"] = 10
        universe[-1]["context"]["fund"]["ev_ebitda"] = 100000
        universe[-1]["sources"][0]["available_at"] = "2026-10-24T22:00:00Z"
        result = evaluate_batch(universe, held=[], as_of=AS_OF)
        self.assertEqual(result["peer_counts"]["ev_ebitda"], 9)
        self.assertIsNone(result["val_stats"]["ev_ebitda_p90"])
        self.assertFalse(result["eligibility"]["DEMO-09"]["eligible"])
        self.assertEqual(result["results"][-1]["status"], "NO_TRADE")

    def test_manifest_command_preserves_sources_and_omits_local_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            peer = snapshot()
            (root / "operator-local-snapshot.json").write_text(json.dumps(peer))
            (root / "manifest.json").write_text(
                json.dumps(
                    dict(
                        schema_version=1,
                        snapshots=["operator-local-snapshot.json"],
                        held=[],
                    )
                )
            )
            parser = argparse.ArgumentParser()
            add_commands(parser.add_subparsers(dest="command", required=True))
            args = parser.parse_args(
                [
                    "batch",
                    str(root / "manifest.json"),
                    "--as-of",
                    AS_OF,
                    "--output",
                    str(root / "output"),
                ]
            )
            with redirect_stdout(io.StringIO()) as messages:
                result = execute(args)
            output = (root / "output" / "batch.json").read_text()
            self.assertNotIn(str(root), output + messages.getvalue())
            self.assertNotIn("operator-local-snapshot.json", output)
            self.assertEqual(
                result["provenance"]["DEMO-PEER"]["sources"], peer["sources"]
            )
            self.assertTrue((root / "output" / "report.html").exists())

    def test_mixed_modes_sessions_and_inconsistent_portfolio_rejected(self):
        first, second = snapshot("DEMO-A"), snapshot("DEMO-B")
        second["context"]["portfolio"]["equity_usd"] += 1
        with self.assertRaises(InputError):
            evaluate_batch([first, second], held=[], as_of=AS_OF)
        with self.assertRaises(InputError):
            evaluate_batch([first, first], held=[], as_of=AS_OF)
        with self.assertRaises(InputError):
            evaluate_batch([first], held=["DEMO-A"], as_of=AS_OF)
        second = snapshot("DEMO-B")
        second["synthetic"] = False
        with self.assertRaises(InputError):
            evaluate_batch([first, second], held=[], as_of=AS_OF)
        second = snapshot("DEMO-B")
        second["history"].pop()
        with self.assertRaises(InputError):
            evaluate_batch([first, second], held=[], as_of=AS_OF)
        second = snapshot("DEMO-B")
        second["history"][-1]["d"] = "2026-10-26"
        with self.assertRaises(InputError):
            evaluate_batch([second], held=[], as_of=AS_OF)

    def test_one_unavailable_held_pair_cannot_hide_behind_known_correlation(self):
        candidate = snapshot("DEMO-CANDIDATE", held=2)
        known = snapshot("DEMO-KNOWN", held=2)
        short = snapshot("DEMO-SHORT", held=2)
        short["history"] = short["history"][-40:]
        result = evaluate_batch(
            [candidate, known, short], held=["DEMO-KNOWN", "DEMO-SHORT"], as_of=AS_OF
        )
        pairs = result["correlations"]["DEMO-CANDIDATE"]["pairs"]
        self.assertAlmostEqual(pairs[0]["correlation"], 1)
        self.assertIsNone(pairs[1]["correlation"])
        self.assertIsNone(result["correlations"]["DEMO-CANDIDATE"]["max_corr"])

    def test_cad_listing_normalizes_sizing_using_explicit_dated_fx(self):
        usd = snapshot()
        cad = copy.deepcopy(usd)
        cad["market"] = dict(
            currency="CAD", exchange="TSX", fundamentals_currency="USD"
        )
        for row in cad["history"]:
            for key in ("o", "h", "l", "c", "ac"):
                row[key] *= 1.25
        for source in cad["sources"]:
            if source["role"] == "price" and source.get("value") is not None:
                source["value"] *= 1.25
        fx = dict(
            rate="1.25",
            observed_at="2026-10-23T20:00:00Z",
            available_at="2026-10-23T21:00:00Z",
            source="https://example.invalid/fx",
            synthetic=True,
        )
        expected = evaluate_batch([usd], held=[], as_of=AS_OF)
        actual = evaluate_batch([cad], held=[], as_of=AS_OF, fx=fx)
        self.assertAlmostEqual(
            actual["results"][0]["hypothetical_sizing"]["entry"],
            expected["results"][0]["hypothetical_sizing"]["entry"],
        )
        self.assertEqual(actual["provenance"]["DEMO-PEER"]["sources"], cad["sources"])
        with self.assertRaises(InputError):
            evaluate_batch([cad], held=[], as_of=AS_OF)
        fx.update(
            observed_at="2026-10-16T20:00:00Z", available_at="2026-10-16T21:00:00Z"
        )
        with self.assertRaises(InputError):
            evaluate_batch([cad], held=[], as_of=AS_OF, fx=fx)


if __name__ == "__main__":
    unittest.main()


class MalformedBatch(unittest.TestCase):
    def test_array_snapshot_is_rejected_at_boundary(self):
        with self.assertRaises(ValueError):
            evaluate_batch([[]], held=[], as_of="2026-10-23T22:00:00Z")
