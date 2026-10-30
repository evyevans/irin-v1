"""Deterministic long-only simulated ledger. Monetary state uses Decimal strings."""

import copy
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR, InvalidOperation
import hashlib, json
from .core import evaluate_snapshot, InputError, timestamp
from engine import aplus, exits

D = Decimal


def money(v):
    try:
        x = D(str(v))
    except InvalidOperation:
        raise ValueError("Invalid monetary input") from None
    if not x.is_finite() or abs(x) > D("1e18"):
        raise ValueError("Invalid monetary value")
    return x


def amount(v):
    return str(money(v).quantize(D(".01")))


def initialize(capital, *, synthetic=False):
    capital = money(capital)
    if capital <= 0:
        raise ValueError("Initial capital must be positive")
    return dict(
        version=1,
        currency="USD",
        synthetic=synthetic,
        enabled=False,
        halted=False,
        dispatch_enabled=False,
        initial=amount(capital),
        cash=amount(capital),
        equity=amount(capital),
        cash_plus_marks=amount(capital),
        peak=amount(capital),
        fee_bps="10",
        slippage_bps="10",
        positions={},
        pending={},
        events=[],
        snapshots=[],
        last_session=None,
        last_input=None,
    )


def advance(state, snapshots, *, as_of, bookkeeping=None):
    if not snapshots:
        raise ValueError("At least one complete snapshot is required")
    validate_state(state)
    original = state
    state = copy.deepcopy(state)
    policy = dict(DEFAULT_POLICY, **state.get("policy", {}))
    if any(s["synthetic"] != state["synthetic"] for s in snapshots):
        raise ValueError("Synthetic and real ledgers cannot mix")
    ticks = [s["context"]["ticker"] for s in snapshots]
    if len(set(ticks)) != len(ticks):
        raise ValueError("Duplicate ticker")
    days = {s["history"][-1]["d"] for s in snapshots}
    if len(days) != 1:
        raise ValueError("All marks must share a session")
    day = days.pop()
    digest = hashlib.sha256(
        json.dumps(
            dict(snapshots=snapshots, bookkeeping=bookkeeping),
            sort_keys=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    if day == state["last_session"]:
        if digest != state["last_input"]:
            raise ValueError("Session already committed with different input")
        return original
    if timestamp(as_of).date().isoformat() != day:
        raise ValueError(
            "New paper decisions require the valued session UTC date; replay genuine point-in-time inputs"
        )
    if state["last_session"] and day < state["last_session"]:
        raise ValueError("Out-of-order session")
    if state.get("next_session") and day != state["next_session"]:
        raise ValueError("Replay each exchange session sequentially before advancing")
    if state["last_session"] and any(
        sum(r["d"] > state["last_session"] for r in s["history"]) != 1
        for s in snapshots
    ):
        raise ValueError("Replay one complete session at a time")
    by = {s["context"]["ticker"]: s for s in snapshots}
    from . import accounting as acct

    bookkeeping = bookkeeping or {}
    if not isinstance(bookkeeping, dict) or any(
        not isinstance(bookkeeping.get(key, []), list)
        for key in ("conversions", "actions")
    ):
        raise ValueError("Bookkeeping must contain explicit action/conversion arrays")
    acct.fx_mark(state, bookkeeping.get("fx"), as_of=as_of)
    for conversion in bookkeeping.get("conversions", []):
        acct.convert_cash(state, conversion, day=day)
    acct.apply_actions(state, bookkeeping.get("actions", []), by, day=day, as_of=as_of)
    for ticker, position in state["positions"].items():
        if ticker in by and position.get("currency", "USD") != by[ticker].get(
            "market", {}
        ).get("currency", "USD"):
            raise ValueError(
                "Held instrument currency changed without explicit sourced migration"
            )
    if set(state["positions"]) - set(by):
        raise ValueError("Missing held-asset history; valuation blocked")
    by = {t: acct.normalized_history(state, s) for t, s in by.items()}
    from .governance import assess

    state["operational"] = assess(state, as_of=as_of)
    from .committee import evaluate as evaluate_committee

    submitted = bookkeeping.get("committees", {})
    if not isinstance(submitted, dict) or set(submitted) - set(by):
        raise ValueError("Committee submissions must identify supplied instruments")
    committees = state.setdefault("committees", {})
    for ticker, envelope in submitted.items():
        if not isinstance(envelope, dict):
            raise ValueError("Invalid committee envelope")
        old = committees.get(ticker)
        if old:
            if envelope["config"] != old["config"]:
                raise ValueError("Committed committee configuration is immutable")
            incoming = {v["id"]: v for v in envelope["votes"].get("vetoes", [])}
            for veto in old["votes"].get("vetoes", []):
                updated = incoming.get(veto["id"])
                if (
                    updated is None
                    or {k: v for k, v in veto.items() if k != "cure"}
                    != {k: v for k, v in updated.items() if k != "cure"}
                    or ("cure" in veto and veto["cure"] != updated.get("cure"))
                ):
                    raise ValueError("Committed veto cannot be removed or rewritten")
        committees[ticker] = copy.deepcopy(envelope)
    committee_results = {}
    for ticker, envelope in committees.items():
        votes = copy.deepcopy(envelope["votes"])
        votes["previously_listed"] = ticker in state["positions"]
        committee_results[ticker] = evaluate_committee(
            envelope["config"], votes, as_of=as_of
        )
    state["committee_results"] = committee_results
    results = {}
    # Validate every snapshot before any mutation; require fresh price attestations for marks/exits.
    for t, s in by.items():
        validate_market(s, as_of)
        result = evaluate_snapshot(acct.research_snapshot(state, s), as_of=as_of)
        if any(
            "price" in gate.lower() or "Source " in gate for gate in result["gates"]
        ):
            raise ValueError("Ineligible marks; session blocked")
        results[t] = result
    if len(state["positions"]) > policy["max_positions"]:
        state["halted"] = True
    cash = money(state["cash"])
    fee = money(state["fee_bps"]) / 10000
    slip = money(state["slippage_bps"]) / 10000
    if min(fee, slip) < 0 or max(fee, slip) > D(".05"):
        raise ValueError("Invalid simulation cost")

    def event(kind, **fields):
        state["events"].append(dict(session=day, kind=kind, **fields))

    # Process every unseen supplied bar for held positions; no current-close signal fills on its signal date.
    for t, pos in list(state["positions"].items()):
        rows = by[t]["history"]
        prior = state["last_session"]
        if prior and not any(r["d"] == prior for r in rows):
            raise ValueError("Held history lacks prior committed session")
        for i, row in enumerate(rows):
            if row["d"] <= pos.get("managed_through", pos["entry_date"]):
                continue
            m = exits.manage(
                dict(
                    ticker=t,
                    entry_price=float(pos["entry"]),
                    stop_price=float(pos["stop"]),
                    entry_date=pos["entry_date"],
                    highest_close=float(pos["highest"]),
                ),
                rows[: i + 1],
                aplus.load_config(),
                pending_exit=pos.get("queued_exit"),
            )
            pos["managed_through"] = row["d"]
            pos["highest"] = str(max(money(pos["highest"]), money(row["c"])))
            if m["action"] == "exit_now":
                px = money(m["price"]) * (1 - slip)
                gross = px * pos["shares"]
                proceeds = gross * (1 - fee)
                ccy = pos.get("currency", "USD")
                fx = acct.rate(state, ccy)
                if ccy == "USD":
                    cash += proceeds
                else:
                    acct.change_cash(state, ccy, proceeds)
                entry_fx = money(pos.get("entry_fx", "1"))
                asset_effect = (proceeds - money(pos["cost"]) / entry_fx) * entry_fx
                fx_effect = proceeds * (fx - entry_fx)
                event(
                    "exit",
                    ticker=t,
                    fill_session=row["d"],
                    shares=pos["shares"],
                    price=str(px),
                    proceeds=amount(proceeds),
                    realized_pnl=str(proceeds * fx - money(pos["cost"])),
                    currency=ccy,
                    entry_fx=str(entry_fx),
                    exit_fx=str(fx),
                    asset_effect_usd=str(asset_effect),
                    fx_effect_usd=str(fx_effect),
                    reason=m["reason"],
                )
                del state["positions"][t]
                break
            if m["action"] == "queue_exit":
                pos["queued_exit"] = m["reason"]
            if m["action"] == "raise_stop":
                pos["stop"] = str(max(money(pos["stop"]), money(m["new_stop"])))
    # Mark remaining holdings before deciding entries. Always use the full portfolio, not caller-supplied cash.
    marks = sum(
        (
            money(by[t]["history"][-1]["c"])
            * p["shares"]
            * acct.rate(state, p.get("currency", "USD"))
            for t, p in state["positions"].items()
        ),
        D(0),
    )
    extra = acct.extra_assets(state)
    equity = cash + marks + extra
    peak = max(money(state["peak"]), equity)
    dd = float(100 * (1 - equity / peak))
    if dd >= 15:
        state["halted"] = True
    pending = state["pending"]
    state["pending"] = {}
    for t in sorted(by):
        s = copy.deepcopy(by[t])
        pos = state["positions"]
        layer_weights = {}
        for k, p in pos.items():
            layer_weights[p["layer"]] = layer_weights.get(p["layer"], 0) + float(
                100
                * money(by[k]["history"][-1]["c"])
                * p["shares"]
                * acct.rate(state, p.get("currency", "USD"))
                / equity
            )
        s["context"]["portfolio"] = dict(
            equity_usd=float(equity),
            drawdown_pct=dd,
            open_positions=len(pos),
            invested_pct=float(100 * marks / equity),
            layer_weight_pct=layer_weights,
            trades_created=sum(e["kind"] == "entry" for e in state["events"]),
            paused_until_month_end=False,
        )
        result = evaluate_snapshot(acct.research_snapshot(state, s), as_of=as_of)
        results[t] = result
        okay = (
            state["enabled"]
            and not state["halted"]
            and state["operational"]["ready"]
            and (
                t not in committee_results
                or committee_results[t]["action"] == "OPEN_PAPER_POSITION"
            )
            and result["status"] == "RULES_PASS"
            and t not in pos
            and (
                not acct.fx_required(state, by)
                or acct.book(state)["fx_status"] == "CURRENT"
            )
        )
        signal = pending.get(t)
        entries = [e for e in state["events"] if e["kind"] == "entry"]
        today = date.fromisoformat(day)
        recent = lambda n: sum(
            date.fromisoformat(e["session"]) > today - timedelta(days=n)
            for e in entries
        )
        frequency = (
            recent(7) < 1
            and recent(28) < 3
            and sum(e["session"][:7] == day[:7] for e in entries) < 2
        )
        if (
            okay
            and signal
            and signal["session"] < day
            and frequency
            and len(pos) < int(policy["max_positions"])
        ):
            size = result["hypothetical_sizing"]
            entry = money(size["entry"]) * (1 + slip)
            currency = by[t].get("market", {}).get("currency", "USD")
            native_fx = acct.rate(state, currency)
            available_cash = (
                cash
                if currency == "USD"
                else acct.cash_balance(state, currency) * native_fx
            )
            multiplier = money(committee_results.get(t, {}).get("risk_multiplier", 1))
            shares = int(
                (money(size["shares"]) * multiplier).to_integral_value(
                    rounding=ROUND_FLOOR
                )
            )
            shares = min(
                shares,
                int(
                    (available_cash / (entry * (1 + fee))).to_integral_value(
                        rounding=ROUND_FLOOR
                    )
                ),
                int(
                    (
                        equity
                        * money(policy["max_initial_weight_pct"])
                        / 100
                        / (entry * (1 + fee))
                    ).to_integral_value(rounding=ROUND_FLOOR)
                ),
            )
            total = entry * shares * (1 + fee)
            # Cost-adjusted risk and available cash must still fit the configured research caps.
            risk = total - money(size["stop"]) * (1 - slip) * shares * (1 - fee)
            projected_equity = (
                equity - total + money(by[t]["history"][-1]["c"]) * native_fx * shares
            )
            layer = s["context"]["row"]["layer"]
            subsector = s["context"]["row"]["subsector"]
            layer_value = sum(
                (
                    money(by[k]["history"][-1]["c"])
                    * p["shares"]
                    * acct.rate(state, p.get("currency", "USD"))
                    for k, p in pos.items()
                    if p["layer"] == layer
                ),
                D(0),
            )
            sector_value = sum(
                (
                    money(by[k]["history"][-1]["c"])
                    * p["shares"]
                    * acct.rate(state, p.get("currency", "USD"))
                    for k, p in pos.items()
                    if p.get("subsector") == subsector
                ),
                D(0),
            )
            exposure_ok = max(layer_value, sector_value) + money(
                by[t]["history"][-1]["c"]
            ) * native_fx * shares <= projected_equity * D(".25")
            if (
                shares > 0
                and exposure_ok
                and risk <= projected_equity * money(size["risk_pct"]) / 100
                and cash + acct.cad_cash_usd(state) - total
                >= projected_equity * money(policy["min_cash_pct"]) / 100
            ):
                if currency == "USD":
                    cash -= total
                else:
                    acct.change_cash(state, currency, -total / native_fx)
                marks += money(by[t]["history"][-1]["c"]) * native_fx * shares
                extra = acct.extra_assets(state)
                equity = cash + marks + extra
                dd = float(100 * (1 - equity / peak))
                if dd >= 15:
                    state["halted"] = True
                pos[t] = dict(
                    shares=shares,
                    entry=str(entry / native_fx),
                    entry_date=day,
                    stop=str(money(size["stop"]) / native_fx),
                    highest=str(entry / native_fx),
                    currency=currency,
                    entry_fx=str(native_fx),
                    cost=str(total),
                    layer=s["context"]["row"]["layer"],
                    subsector=subsector,
                    managed_through=day,
                )
                event(
                    "entry",
                    ticker=t,
                    shares=shares,
                    currency=currency,
                    native_price=str(entry / native_fx),
                    price_currency="USD",
                    price=str(entry),
                    cost=amount(total),
                    signal_session=signal["session"],
                    input_sha256=result["input_sha256"],
                    config_sha256=result["config_sha256"],
                )
            else:
                event(
                    "rejected",
                    ticker=t,
                    reason="Costs, cash, concentration or risk capacity",
                )
        elif signal:
            event(
                "cancelled",
                ticker=t,
                reason="Fresh qualification, mode or frequency gate failed",
            )
        if okay and t not in pos:
            state["pending"][t] = dict(session=day, input_sha256=result["input_sha256"])
    for ticker, position in state["positions"].items():
        if committee_results.get(ticker, {}).get("action") in (
            "REDUCE_REMOVE",
            "REJECT",
        ):
            position["queued_exit"] = "Committee negative review (next session)"
        position["last_mark"] = str(by[ticker]["history"][-1]["c"])
    peak = max(money(original["peak"]), equity)
    dd = float(100 * (1 - equity / peak))
    if dd >= 15:
        state["halted"] = True
    state.update(
        cash=str(cash),
        equity=amount(equity),
        cash_plus_marks=amount(cash + marks + acct.extra_assets(state)),
        peak=str(peak),
        last_session=day,
        last_input=digest,
    )
    state["snapshots"].append(
        dict(
            session=day,
            cash=amount(cash),
            invested=amount(marks),
            equity=amount(equity),
            cash_balances={"USD": str(cash), "CAD": acct.book(state)["cash_cad"]},
            receivables_usd=str(acct.receivable_value(state)),
            fx_usdcad=(
                acct.book(state)["fx"]["rate"] if acct.book(state)["fx"] else None
            ),
            fx_status=acct.book(state)["fx_status"],
            valued_at=as_of,
            operational=copy.deepcopy(state["operational"]),
            committees=copy.deepcopy(committee_results),
            distributions_complete=all(
                s.get("market", {}).get("distributions_complete") is True
                for s in by.values()
            ),
            accounting=copy.deepcopy(acct.book(state)),
            attribution=acct.summary(state),
            drawdown_pct=round(dd, 6),
            positions=len(state["positions"]),
            positions_state=copy.deepcopy(state["positions"]),
            enabled=state["enabled"],
            halted=state["halted"],
        )
    )
    validate_state(state)
    next_days = {
        s.get("market", {}).get("next_session") for s in snapshots if not s["synthetic"]
    }
    if next_days:
        if len(next_days) != 1:
            raise ValueError("Conflicting next-session calendars")
        state["next_session"] = next_days.pop()
    else:
        next_day = date.fromisoformat(day) + timedelta(days=1)
        while next_day.weekday() > 4:
            next_day += timedelta(days=1)
        state["next_session"] = next_day.isoformat()
    if "benchmarks" in bookkeeping:
        from .benchmarks import evaluate_benchmarks

        registry = bookkeeping["benchmarks"]
        evaluate_benchmarks(
            [
                {k: v for k, v in row.items() if k != "fx_usdcad" or v is not None}
                for row in state["snapshots"]
            ],
            registry,
            as_of=as_of,
        )
        state["benchmarks"] = copy.deepcopy(registry)
    state["last_results"] = results
    return state


DEFAULT_POLICY = dict(max_initial_weight_pct="5", min_cash_pct="20", max_positions=7)


def validate_state(state):
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or state.get("currency") != "USD"
    ):
        raise ValueError("Unsupported ledger schema or currency")
    for key in ("enabled", "halted", "synthetic", "dispatch_enabled"):
        if type(state.get(key)) is not bool:
            raise ValueError("Ledger modes must be explicit booleans")
    for key in ("initial", "cash", "equity", "peak"):
        if money(state[key]) < 0:
            raise ValueError("Ledger balances must be nonnegative")
    if money(state["initial"]) <= 0 or money(state["peak"]) <= 0:
        raise ValueError("Invalid initial capital or peak")
    for key in ("positions", "pending"):
        if not isinstance(state.get(key), dict):
            raise ValueError("Invalid ledger collections")
    if not isinstance(state.get("events"), list) or not isinstance(
        state.get("snapshots"), list
    ):
        raise ValueError("Invalid audit arrays")
    for pos in state["positions"].values():
        if type(pos["shares"]) is not int or pos["shares"] <= 0:
            raise ValueError("Position must hold positive whole shares")
        for key in ("entry", "stop", "highest", "cost"):
            if money(pos[key]) < 0 or (key != "cost" and money(pos[key]) == 0):
                raise ValueError("Invalid position amount")
    from .accounting import validate_accounting

    validate_accounting(state)
    policy = dict(DEFAULT_POLICY, **state.get("policy", {}))
    if (
        not 0 < money(policy["max_initial_weight_pct"]) <= 5
        or not 20 <= money(policy["min_cash_pct"]) <= 100
        or type(policy["max_positions"]) is not int
        or not 1 <= policy["max_positions"] <= 7
    ):
        raise ValueError("Policy may only tighten the baseline safety caps")
    if len(state["positions"]) > policy["max_positions"] and not any(
        p.get("action_origin") for p in state["positions"].values()
    ):
        raise ValueError("Position count exceeds policy")
    for key in ("fee_bps", "slippage_bps"):
        if not 0 <= money(state[key]) <= 500:
            raise ValueError("Invalid cost assumption")


def validate_market(snapshot, as_of):
    if snapshot["synthetic"]:
        return
    market = snapshot.get("market", {})
    if not (
        (
            market.get("currency") == "USD"
            and market.get("exchange") in ("NYSE", "NASDAQ", "NYSE_AMERICAN")
        )
        or (
            market.get("currency") == "CAD"
            and market.get("exchange") in ("TSX", "TSXV")
        )
    ):
        raise ValueError(
            "Paper simulator requires supported exchange and settlement currency"
        )
    if market.get("corporate_actions_checked") is not True:
        raise ValueError("Corporate action review is required")
    if not market.get("next_session") or date.fromisoformat(
        market["next_session"]
    ) <= date.fromisoformat(snapshot["history"][-1]["d"]):
        raise ValueError("Provide next exchange session from an exchange calendar")
    close = timestamp(market.get("session_close"))
    if close.date().isoformat() != snapshot["history"][-1]["d"] or close > timestamp(
        as_of
    ):
        raise ValueError("Incomplete exchange session")
    for source in snapshot["sources"]:
        if source["role"] == "price" and timestamp(source["observed_at"]) < close:
            raise ValueError("Price predates session close")
