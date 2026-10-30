"""Three reproducible synthetic scenarios; never fetches market data."""

import copy
import json
from pathlib import Path
from .core import evaluate_snapshot
from .report import render_html

ROOT = Path(__file__).resolve().parents[1]


def write_results(results, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    bundle = {"synthetic": all(r["synthetic"] for r in results), "results": results}
    (output / "results.json").write_text(
        json.dumps(bundle, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output / "report.html").write_text(render_html(results), encoding="utf-8")
    return bundle


def run_demo(output):
    fixture = json.loads((ROOT / "examples/synthetic.json").read_text(encoding="utf-8"))
    missing = copy.deepcopy(fixture)
    missing["context"]["name"] = "Synthetic Missing Evidence"
    missing["sources"] = []
    missing["chain_sources"] = {}
    stale = copy.deepcopy(fixture)
    stale["context"]["name"] = "Synthetic Stale Prices"
    results = [
        evaluate_snapshot(fixture, as_of="2026-10-23T22:00:00Z"),
        evaluate_snapshot(missing, as_of="2026-10-23T22:00:00Z"),
        evaluate_snapshot(stale, as_of="2026-10-30T22:00:00Z"),
    ]
    return write_results(results, output)
