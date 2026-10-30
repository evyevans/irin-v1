"""Persistent paper-worker commands; local and cloud share one state machine."""

import argparse, copy, json
from pathlib import Path
from .paper import initialize, advance, validate_state
from .storage import LocalStore, Conflict
from .portfolio_report import write_report, reserve_delivery


def add_commands(commands):
    p = commands.add_parser(
        "paper", help="Persistent paper simulation; no broker orders"
    )
    p.add_argument("--ledger", default="local-data/ledger.db")
    p.add_argument(
        "--cloud",
        action="store_true",
        help="Use this installation Supabase service-worker store",
    )
    subs = p.add_subparsers(dest="action", required=True)
    init = subs.add_parser("init")
    init.add_argument("--capital", required=True)
    init.add_argument("--synthetic", action="store_true")
    init.add_argument("--fee-bps", default="10")
    init.add_argument("--slippage-bps", default="10")
    init.add_argument("--max-initial-weight-pct", default="5")
    init.add_argument("--min-cash-pct", default="20")
    init.add_argument("--max-positions", type=int, default=7)
    for action in (
        "enable",
        "disable",
        "halt",
        "resume",
        "status",
        "dispatch-enable",
        "dispatch-hold",
    ):
        subs.add_parser(action)
    audit = subs.add_parser("audit-verify")
    audit.add_argument("--expected-head")
    governance = subs.add_parser("governance")
    governance.add_argument("--input", type=Path, required=True)
    run = subs.add_parser("run")
    run.add_argument("snapshots", nargs="+", type=Path)
    run.add_argument("--as-of", required=True)
    run.add_argument(
        "--bookkeeping",
        type=Path,
        help="Dated FX, explicit conversions, corporate actions and benchmarks JSON",
    )
    report = subs.add_parser("report")
    report.add_argument("--week", required=True)
    report.add_argument("--output", default="exports/portfolio")
    report.add_argument("--as-of")
    report.add_argument("--currency", choices=["USD", "CAD"], default="USD")
    reserve = subs.add_parser("reserve-send")
    reserve.add_argument("--week", required=True)
    reserve.add_argument("--sha256", required=True)
    ack = subs.add_parser("ack-send")
    ack.add_argument("--week", required=True)
    ack.add_argument("--message-id", required=True)
    return p


def execute(args):
    if args.cloud:
        from .cloud import CloudStore

        store = CloudStore()
    else:
        path = Path(args.ledger)
        path.parent.mkdir(parents=True, exist_ok=True)
        store = LocalStore(path)
    if args.action == "audit-verify":
        result = store.verify_audit(expected_head=args.expected_head)
        print(json.dumps(result, indent=2))
        if not result["valid"]:
            raise ValueError("Audit chain verification failed")
        return
    record = store.read()
    old = record["state"]
    revision = record["revision"]
    if args.action == "status":
        print(json.dumps(record, indent=2))
        return
    if not store.verify_audit()["valid"]:
        raise ValueError("Persisted audit chain is invalid; reconcile before writing")
    if args.action == "init":
        if old is not None:
            raise ValueError("Ledger already initialized; reset is not supported")
        new = initialize(args.capital, synthetic=args.synthetic)
        new.update(
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
            policy=dict(
                max_initial_weight_pct=args.max_initial_weight_pct,
                min_cash_pct=args.min_cash_pct,
                max_positions=args.max_positions,
            ),
        )
    else:
        if old is None:
            raise ValueError("Initialize this installation first")
        validate_state(old)
        new = copy.deepcopy(old)
        if args.action == "report":
            print(
                json.dumps(
                    write_report(
                        old,
                        args.week,
                        args.output,
                        as_of=args.as_of,
                        report_currency=args.currency,
                    ),
                    indent=2,
                )
            )
            return
        if args.action == "run":
            snaps = []
            for path in args.snapshots:
                if path.stat().st_size > 10_000_000:
                    raise ValueError("Snapshot exceeds limit")
                snaps.append(json.loads(path.read_text(encoding="utf-8")))
            bookkeeping = None
            if args.bookkeeping:
                if args.bookkeeping.stat().st_size > 10_000_000:
                    raise ValueError("Bookkeeping exceeds limit")
                bookkeeping = json.loads(args.bookkeeping.read_text(encoding="utf-8"))
            new = advance(old, snaps, as_of=args.as_of, bookkeeping=bookkeeping)
            if new == old:
                print(json.dumps(dict(already_committed=True, revision=revision)))
                return
        elif args.action == "governance":
            from . import governance

            if args.input.stat().st_size > 1_000_000:
                raise ValueError("Governance input exceeds limit")
            request = json.loads(args.input.read_text(encoding="utf-8"))
            operation = request.pop("operation")
            allowed = {
                name: getattr(governance, name)
                for name in (
                    "configure",
                    "record_check",
                    "add_review",
                    "resolve_review",
                    "queue_notice",
                    "acknowledge_notice",
                )
            }
            if operation not in allowed:
                raise ValueError("Unknown governance operation")
            new = allowed[operation](new, **request)
        elif args.action in ("enable", "disable"):
            new["enabled"] = args.action == "enable"
        elif args.action in ("halt", "resume"):
            new["halted"] = args.action == "halt"
        elif args.action == "dispatch-enable":
            new.update(dispatch_enabled=True, dispatch_hold=False)
        elif args.action == "dispatch-hold":
            new["dispatch_hold"] = True
        elif args.action == "reserve-send":
            new = reserve_delivery(old, args.week, args.sha256)
        elif args.action == "ack-send":
            delivery = new.get("deliveries", {}).get(args.week)
            if not delivery or delivery["status"] != "reserved":
                raise ValueError("No matching reserved report")
            # Connector message ID is deployment-private and never included in distribution files.
            delivery.update(status="sent", message_id=args.message_id)
    if new == old:
        print(json.dumps(dict(unchanged=True, revision=revision)))
        return
    validate_state(new)
    import hashlib

    key = hashlib.sha256(
        (str(revision) + "|" + json.dumps(new, sort_keys=True)).encode()
    ).hexdigest()
    committed = store.commit(revision, key, new)
    print(
        json.dumps(
            dict(
                revision=committed,
                action=args.action,
                last_session=new["last_session"],
                positions=len(new["positions"]),
                equity=new["equity"],
                halted=new["halted"],
            )
        )
    )
