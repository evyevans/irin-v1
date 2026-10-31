"""Portfolio reports and conservative opt-in delivery reservation; no sending API."""

import copy, hashlib, json
from datetime import date, timedelta, datetime, timezone
from html import escape
from pathlib import Path
from .paper import amount, money, validate_state


def build_report(state, *, week, as_of=None, report_currency="USD"):
    validate_state(state)
    start = date.fromisoformat(week)
    if start.weekday() != 0:
        raise ValueError("Report week must begin on Monday")
    end = start + timedelta(days=6)
    cutoff = as_of or datetime.now(timezone.utc).isoformat()
    from .core import timestamp

    records = [
        x
        for x in state["snapshots"]
        if x["session"] <= cutoff[:10]
        and (not x.get("valued_at") or timestamp(x["valued_at"]) <= timestamp(cutoff))
    ]
    before = [x for x in records if x["session"] < week]
    within = [x for x in records if week <= x["session"] <= end.isoformat()]
    # Never pretend a partial week or missing start valuation is a zero return.
    report_date = (
        date.fromisoformat(as_of[:10]) if as_of else datetime.now(timezone.utc).date()
    )
    complete = bool(
        report_date > end
        and state.get("next_session")
        and state["next_session"] > end.isoformat()
    )
    weekly = None
    weekly_usd = None
    if before and within and complete:
        weekly_usd = float(
            100 * (money(within[-1]["equity"]) / money(before[-1]["equity"]) - 1)
        )
    last_visible = records[-1]["session"] if records else "0001-01-01"
    events = [
        e
        for e in state["events"]
        if week <= e["session"] <= min(end.isoformat(), last_visible)
    ]
    realized = sum(
        (money(e["realized_pnl"]) for e in events if "realized_pnl" in e), money(0)
    )
    closing = within[-1] if within else {}
    closing_positions = closing.get("positions_state")
    if closing_positions is None and closing.get("session") == state.get(
        "last_session"
    ):
        closing_positions = state["positions"]
    closing_cash = closing.get("cash")
    if closing_cash is None and closing.get("session") == state.get("last_session"):
        closing_cash = state["cash"]
    if report_currency not in ("USD", "CAD"):
        raise ValueError("Unsupported reporting currency")
    report_fx = closing.get("fx_usdcad")
    report_equity = (
        (
            str(money(closing["equity"]) * money(report_fx))
            if report_fx and closing.get("equity") is not None
            else None
        )
        if report_currency == "CAD"
        else closing.get("equity")
    )
    weekly = weekly_usd
    if report_currency == "CAD":
        weekly = None
        if weekly_usd is not None and before[-1].get("fx_usdcad") and report_fx:
            weekly = float(
                100
                * (
                    money(closing["equity"])
                    * money(report_fx)
                    / (money(before[-1]["equity"]) * money(before[-1]["fx_usdcad"]))
                    - 1
                )
            )
    benchmark_results = []
    if state.get("benchmarks"):
        from .benchmarks import evaluate_benchmarks

        relevant = ([before[-1]] if before else []) + within
        cutoff = as_of or datetime.now(timezone.utc).isoformat()
        coverage = bool(relevant) and all(
            x.get("distributions_complete") is True for x in relevant
        )
        benchmark_results = evaluate_benchmarks(
            [
                {k: v for k, v in row.items() if k != "fx_usdcad" or v is not None}
                for row in relevant
            ],
            state["benchmarks"],
            as_of=cutoff,
            report_currency=report_currency,
        )
        if not coverage or not complete:
            from .benchmarks import _METRICS

            for result in benchmark_results:
                result["status"] = "unavailable"
                if not coverage:
                    result["portfolio_return_type"] = "UNVERIFIED"
                    result["reasons"].append("distribution_coverage_unverified")
                if not complete:
                    result["reasons"].append("period_incomplete")
                for key in _METRICS:
                    result[key] = None
    data = dict(
        week=week,
        end=end.isoformat(),
        synthetic=state["synthetic"],
        currency=state["currency"],
        equity=closing.get("equity"),
        cash=closing_cash,
        positions=closing_positions,
        events=events,
        weekly_return_pct=weekly,
        weekly_return_usd_pct=weekly_usd,
        distribution_income_usd=amount(
            sum(
                (
                    money(e["net_usd"])
                    for e in events
                    if e["kind"] == "dividend_entitlement"
                    and e.get("distribution_kind") == "cash_dividend"
                ),
                money(0),
            )
        ),
        realized_pnl=amount(realized),
        last_session=closing.get("session"),
        paper_enabled=closing.get("enabled"),
        halted=closing.get("halted"),
        send_allowed=False,
        reporting_currency=report_currency,
        reporting_equity=report_equity,
        cash_balances=closing.get("cash_balances", {"USD": closing_cash, "CAD": "0"}),
        receivables_usd=closing.get("receivables_usd", "0"),
        attribution=closing.get("attribution"),
        fx_status=closing.get("fx_status", "NOT_REQUIRED"),
        benchmarks=benchmark_results,
    )
    data["body_sha256"] = hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()
    from .governance import assess

    data["send_allowed"] = bool(
        assess(state, as_of=cutoff)["ready"]
        and state["dispatch_enabled"]
        and not state.get("dispatch_hold", True)
        and complete
        and within
        and closing_positions is not None
        and closing_cash is not None
        and data["fx_status"] not in ("PROVISIONAL_STALE", "MISSING")
        and (report_currency == "USD" or report_equity is not None)
        and week not in state.get("deliveries", {})
    )
    return data


def write_report(state, week, output, as_of=None, report_currency="USD"):
    data = build_report(state, week=week, as_of=as_of, report_currency=report_currency)
    path = Path(output)
    path.mkdir(parents=True, exist_ok=True)
    lines = [
        "IRIN · simulated portfolio",
        f'Week: {data["week"]} to {data["end"]}',
        f'Last valued session: {data["last_session"]}',
        f'Synthetic: {data["synthetic"]}',
        f'Equity: USD {data["equity"]}',
        f'Cash: USD {data["cash"]}',
        f'Weekly return ({data["reporting_currency"]}): {data["weekly_return_pct"] if data["weekly_return_pct"] is not None else "unavailable (missing/partial period)"}',
        f'Distribution income recognized: USD {data["distribution_income_usd"]}',
        f'Realized PnL during period: USD {data["realized_pnl"]}',
        f'Open positions: {len(data["positions"]) if data["positions"] is not None else "unavailable"}',
        f'Paper enabled: {data["paper_enabled"]} · halt: {data["halted"]}',
    ]
    lines += [
        "Reporting view: "
        + data["reporting_currency"]
        + " "
        + str(data["reporting_equity"]),
        "Cash sleeves: " + json.dumps(data["cash_balances"], sort_keys=True),
        "Receivables (USD): " + str(data["receivables_usd"]),
        "FX status: " + data["fx_status"],
        "Attribution: " + json.dumps(data["attribution"], sort_keys=True),
    ]
    lines += ["Benchmark: " + json.dumps(b, sort_keys=True) for b in data["benchmarks"]]
    lines += [json.dumps(e, sort_keys=True) for e in data["events"]]
    lines += [
        "Fees, slippage and fills are simulated assumptions. Source attestations are not independent verification. This report does not constitute financial advice."
    ]
    text = "\n".join(lines) + "\n"
    body = "<h1>IRIN</h1><pre>" + escape(text) + "</pre>"
    html = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Simulated portfolio</title><style>body{font:16px/1.6 system-ui;max-width:980px;margin:40px auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
        + body
        + "</html>"
    )
    (path / "report.html").write_text(html, encoding="utf-8")
    (path / "report.txt").write_text(text, encoding="utf-8")
    (path / "report.json").write_text(json.dumps(data, indent=2) + "\n")
    manifest = dict(
        period=week,
        body_sha256=hashlib.sha256(html.encode()).hexdigest(),
        send_allowed=data["send_allowed"],
        qa_pass=bool(data["last_session"]),
        synthetic=data["synthetic"],
        requires_atomic_reservation=True,
    )
    (path / "send_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return data


def reserve_delivery(state, week, body_sha256):
    data = build_report(state, week=week)
    if not data["send_allowed"]:
        raise ValueError("Dispatch is disabled, held, duplicate or period incomplete")
    if len(body_sha256) != 64 or any(c not in "0123456789abcdef" for c in body_sha256):
        raise ValueError("Invalid report digest")
    state = copy.deepcopy(state)
    state.setdefault("deliveries", {})[week] = dict(
        status="reserved", body_sha256=body_sha256
    )
    return state
