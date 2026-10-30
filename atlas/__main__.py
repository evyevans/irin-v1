"""python3 -m atlas demo | evaluate <local-snapshot.json>."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from .core import InputError, evaluate_snapshot
from .storage import Conflict
from .cloud import CloudError
from . import worker, batch, research_data
from .demo import run_demo, write_results


def main():
    parser = argparse.ArgumentParser(
        description="Bottleneck Atlas · local equity research, never execution"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run three synthetic, offline examples")
    demo.add_argument("--output", default="demo-output")
    evaluate = commands.add_parser(
        "evaluate", help="Check a local operator-supplied snapshot"
    )
    evaluate.add_argument("snapshot", type=Path)
    evaluate.add_argument(
        "--as-of",
        help="Explicit evaluation time for reproducible historical research; defaults to now in UTC",
    )
    evaluate.add_argument("--output", default="demo-output")
    refresh = commands.add_parser(
        "refresh", help="Fetch optional public EOD observations into a real dossier"
    )
    refresh.add_argument("dossier", type=Path)
    refresh.add_argument("--session-close", required=True)
    refresh.add_argument("--next-session", required=True)
    refresh.add_argument("--output", type=Path, required=True)
    pdemo = commands.add_parser(
        "paper-demo", help="Synthetic persistent signal/fill/exit demonstration"
    )
    pdemo.add_argument("--output", default="demo-output/paper")
    ademo = commands.add_parser(
        "accounting-demo", help="Offline FX/distribution/action/benchmark demonstration"
    )
    ademo.add_argument("--output", default="demo-output/accounting")
    worker.add_commands(commands)
    batch.add_commands(commands)
    research_data.add_commands(commands)
    args = parser.parse_args()
    try:
        if args.command in ("batch", "research-data"):
            (batch if args.command == "batch" else research_data).execute(args)
            return 0
        if args.command == "accounting-demo":
            from .accounting_demo import run

            run(args.output)
            return 0
        if args.command == "paper-demo":
            from .paper_demo import run

            run(args.output)
            return 0
        if args.command == "refresh":
            from .market import refresh as fetch_market

            if args.dossier.stat().st_size > 10_000_000:
                raise InputError("Dossier exceeds limit")
            snap = fetch_market(
                json.loads(args.dossier.read_text()),
                session_close=args.session_close,
                next_session=args.next_session,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(snap, indent=2, allow_nan=False) + "\n")
            print(
                "Observations saved. Upstream independence still requires verification; inspect refresh.warning."
            )
            return 0
        if args.command == "paper":
            worker.execute(args)
            return 0
        if args.command == "demo":
            bundle = run_demo(args.output)
        else:
            if args.snapshot.stat().st_size > 10_000_000:
                raise InputError("Snapshot exceeds the 10 MB limit.")
            snap = json.loads(args.snapshot.read_text(encoding="utf-8"))
            now = args.as_of or datetime.now(timezone.utc).isoformat()
            bundle = write_results([evaluate_snapshot(snap, as_of=now)], args.output)
    except (
        InputError,
        OSError,
        ValueError,
        RecursionError,
        OverflowError,
        KeyError,
        TypeError,
        Conflict,
        CloudError,
    ):
        # Do not echo input or paths: they may contain private values.
        print(
            "Operation rejected. Check input, initialized ledger, mode, revision, credentials and output path; see docs/CLOUD.md and docs/INPUTS.md.",
            file=sys.stderr,
        )
        return 2
    for result in bundle["results"]:
        print(
            f'{result["status"]:10} | {result["evidence_status"]} | {result["ticker"]} | execution disabled'
        )
    print("Local files: results.json and report.html in the selected output directory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
