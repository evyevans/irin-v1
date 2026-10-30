"""Dated cash sleeves and immutable corporate-action accounting for simulation.

All event terms and tax/basis inputs are supplied attestations, not inferred legal facts.
"""

import copy, hashlib, json
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from .core import timestamp
from .paper import money, amount

D = Decimal


def book(state):
    return state.setdefault(
        "accounting",
        dict(
            cash_cad="0",
            cad_basis_usd="0",
            receivables={},
            actions={},
            conversions={},
            fx=None,
            fx_status="NOT_REQUIRED",
            realized_fx_usd="0",
            fx_revaluation_usd="0",
        ),
    )


def rate(state, currency):
    if currency == "USD":
        return D(1)
    if currency != "CAD":
        raise ValueError("Unsupported currency")
    fx = book(state)["fx"]
    if not fx:
        raise ValueError("Dated USD/CAD observation required")
    return 1 / money(fx["rate"])


def cash_balance(state, currency):
    return (
        money(state["cash"])
        if currency == "USD"
        else (
            money(book(state)["cash_cad"])
            if currency == "CAD"
            else rate(state, currency)
        )
    )


def change_cash(state, currency, value):
    new = cash_balance(state, currency) + money(value)
    if new < 0:
        raise ValueError(
            "Insufficient settlement-currency cash; no implicit conversion"
        )
    if currency == "USD":
        state["cash"] = str(new)
    else:
        a = book(state)
        old = cash_balance(state, currency)
        if value < 0:
            removed = money(a["cad_basis_usd"]) * (-value) / old if old else D(0)
            a["cad_basis_usd"] = str(money(a["cad_basis_usd"]) - removed)
            a["realized_fx_usd"] = str(
                money(a["realized_fx_usd"]) + (-value) * rate(state, "CAD") - removed
            )
        else:
            a["cad_basis_usd"] = str(
                money(a["cad_basis_usd"]) + money(value) * rate(state, "CAD")
            )
        a["cash_cad"] = str(new)


def extra_assets(state):
    a = book(state)
    return (
        money(a["cash_cad"]) * rate(state, "CAD") if money(a["cash_cad"]) else D(0)
    ) + receivable_value(state)


def receivable_value(state):
    return sum(
        (
            money(r["net"]) * rate(state, r["currency"])
            for r in book(state)["receivables"].values()
            if not r.get("paid")
        ),
        D(0),
    )


def foreign_assets(state):
    return extra_assets(state)


def fx_mark(state, observation, *, as_of):
    a = book(state)
    now = timestamp(as_of)
    old = a["fx"]
    if observation is not None:
        if (
            type(observation.get("synthetic")) is not bool
            or observation["synthetic"] != state["synthetic"]
        ):
            raise ValueError("FX synthetic/real mismatch")
        value = money(observation.get("rate"))
        if value <= 0:
            raise ValueError("FX rate must be positive CAD per USD")
        observed = timestamp(observation.get("observed_at"))
        available = timestamp(observation.get("available_at"))
        if (
            not observed <= available <= now
            or not isinstance(observation.get("source"), str)
            or not observation["source"].startswith("https://")
        ):
            raise ValueError("Invalid FX provenance or future availability")
        if old and timestamp(old["observed_at"]) > observed:
            raise ValueError("Cannot move FX observation backward")
        if old and timestamp(old["observed_at"]) == observed and old != observation:
            raise ValueError("Conflicting FX observation; use a new dated observation")
        if old:
            cad_exposure = money(a["cash_cad"]) + sum(
                (
                    money(r["net"])
                    for r in a["receivables"].values()
                    if r["currency"] == "CAD" and not r.get("paid")
                ),
                D(0),
            )
            effect = cad_exposure * (1 / value - 1 / money(old["rate"]))
            a["fx_revaluation_usd"] = str(money(a["fx_revaluation_usd"]) + effect)
        a["fx"] = copy.deepcopy(observation)
    if a["fx"]:
        age = (now - timestamp(a["fx"]["observed_at"])).total_seconds()
        a["fx_status"] = "CURRENT" if 0 <= age <= 96 * 3600 else "PROVISIONAL_STALE"
    else:
        a["fx_status"] = (
            "MISSING"
            if money(a["cash_cad"])
            or any(
                p.get("currency", "USD") == "CAD" for p in state["positions"].values()
            )
            or any(
                r["currency"] == "CAD" and not r.get("paid")
                for r in a["receivables"].values()
            )
            else "NOT_REQUIRED"
        )


def stamp(state, kind, day, **fields):
    state["events"].append(dict(session=day, kind=kind, **fields))


def convert_cash(state, request, *, day):
    a = book(state)
    key = request.get("id")
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    if not isinstance(key, str) or not key:
        raise ValueError("Conversion ID required")
    if key in a["conversions"]:
        if a["conversions"][key] != digest:
            raise ValueError("Conversion ID conflict")
        return
    if a["fx_status"] != "CURRENT":
        raise ValueError("Fresh FX required for conversion")
    source = request.get("from_currency")
    target = {"USD": "CAD", "CAD": "USD"}.get(source)
    if not target:
        raise ValueError("Conversion currencies must be USD/CAD")
    value = money(request.get("amount"))
    fee = money(request.get("fee_bps", "0")) / 10000
    if value <= 0 or not 0 <= fee <= D(".05"):
        raise ValueError("Invalid conversion amount or fee")
    proceeds = value * rate(state, source) / rate(state, target) * (1 - fee)
    change_cash(state, source, -value)
    change_cash(state, target, proceeds)
    a["conversions"][key] = digest
    stamp(
        state,
        "fx_conversion",
        day,
        id=key,
        from_currency=source,
        to_currency=target,
        amount_out=str(value),
        amount_in=str(proceeds),
        cost_usd=str(value * rate(state, source) * fee),
        fx=copy.deepcopy(a["fx"]),
    )


def _fractional(state, pos, exact, *, price, currency, day, event_id):
    whole = int(exact.to_integral_value(rounding=ROUND_FLOOR))
    fraction = exact - whole
    if fraction:
        if price is None or money(price) <= 0:
            raise ValueError(
                "Fractional corporate-action entitlement needs sourced cash-in-lieu price"
            )
        proceeds = fraction * money(price)
        basis = money(pos["cost"]) * fraction / exact
        change_cash(state, currency, proceeds)
        pos["cost"] = str(money(pos["cost"]) - basis)
        stamp(
            state,
            "cash_in_lieu",
            day,
            id=event_id,
            shares=str(fraction),
            currency=currency,
            proceeds=str(proceeds),
            realized_pnl=amount(proceeds * rate(state, currency) - basis),
        )
    pos["shares"] = whole
    return whole


def apply_actions(state, actions, snapshots, *, day, as_of):
    a = book(state)
    now = timestamp(as_of)
    date.fromisoformat(day)
    for action in actions:
        key = action.get("id")
        digest = hashlib.sha256(
            json.dumps(action, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        if not isinstance(key, str) or not key:
            raise ValueError("Action ID required")
        if key in a["actions"]:
            if a["actions"][key]["digest"] != digest:
                raise ValueError("Corporate action ID conflict")
            continue
        if timestamp(action.get("available_at")) > now or not str(
            action.get("source", "")
        ).startswith("https://"):
            raise ValueError("Action needs dated available primary-source terms")
        effective = date.fromisoformat(action["effective_date"]).isoformat()
        if effective < day:
            raise ValueError(
                "Late action cannot rewrite a committed entitlement/session"
            )
        if action.get("kind") not in (
            "cash_dividend",
            "split",
            "symbol_change",
            "cash_merger",
            "share_merger",
            "spin_off",
            "return_of_capital",
            "writeoff",
        ):
            raise ValueError("Unsupported corporate action; manual resolution required")
        a["actions"][key] = dict(
            digest=digest, terms=copy.deepcopy(action), applied=False
        )
    groups = {}
    for record in a["actions"].values():
        if not record["applied"]:
            terms = record["terms"]
            groups.setdefault((terms["effective_date"], terms["ticker"]), []).append(
                terms
            )
    for terms in groups.values():
        if len(terms) > 1 and (
            any(type(t.get("sequence")) is not int for t in terms)
            or len({t["sequence"] for t in terms}) != len(terms)
        ):
            raise ValueError("Same-date actions need explicit unique sequence terms")
    for key, record in sorted(
        a["actions"].items(),
        key=lambda item: (
            item[1]["terms"]["effective_date"],
            item[1]["terms"].get("sequence", 0),
            item[0],
        ),
    ):
        if record["applied"] or record["terms"]["effective_date"] > day:
            continue
        action = record["terms"]
        kind = action["kind"]
        ticker = action["ticker"]
        pos = state["positions"].get(ticker)
        record["applied"] = True
        if not pos:
            continue
        currency = pos.get("currency", "USD")
        qty = pos["shares"]
        if kind in ("cash_dividend", "return_of_capital"):
            if pos["entry_date"] >= action["effective_date"]:
                continue
            pay = date.fromisoformat(action["pay_date"]).isoformat()
            if pay < action["effective_date"]:
                raise ValueError("Dividend payment predates entitlement")
            ccy = action.get("currency")
            per = money(action["amount_per_share"])
            withholding = money(action.get("withholding_rate", "0"))
            if ccy not in ("USD", "CAD") or per < 0 or not 0 <= withholding <= 1:
                raise ValueError("Invalid distribution terms")
            gross = qty * per
            net = gross * (1 - withholding)
            a["receivables"][key] = dict(
                currency=ccy,
                gross=str(gross),
                net=str(net),
                pay_date=pay,
                paid=False,
                ticker=ticker,
                kind=kind,
            )
            if kind == "return_of_capital":
                reduction = min(money(pos["cost"]), gross * rate(state, ccy))
                excess = gross * rate(state, ccy) - reduction
                pos["cost"] = str(money(pos["cost"]) - reduction)
                if excess:
                    stamp(
                        state,
                        "return_of_capital_excess",
                        day,
                        id=key,
                        ticker=ticker,
                        realized_pnl=amount(excess),
                    )
            stamp(
                state,
                "dividend_entitlement",
                day,
                distribution_kind=kind,
                net_usd=str(net * rate(state, ccy)),
                id=key,
                ticker=ticker,
                shares=qty,
                currency=ccy,
                gross=str(gross),
                net=str(net),
                withholding=str(gross - net),
                pay_date=pay,
            )
        elif kind == "split":
            ratio = money(action["ratio"])
            if ratio <= 0:
                raise ValueError("Split ratio must be positive")
            for field in ("entry", "stop", "highest"):
                pos[field] = str(money(pos[field]) / ratio)
            exact = D(qty) * ratio
            if not _fractional(
                state,
                pos,
                exact,
                price=action.get("cash_in_lieu_price"),
                currency=currency,
                day=day,
                event_id=key,
            ):
                del state["positions"][ticker]
            state["pending"].pop(ticker, None)
            stamp(
                state,
                "split",
                day,
                id=key,
                ticker=ticker,
                ratio=str(ratio),
                new_shares=pos["shares"],
            )
        elif kind == "symbol_change":
            target = action["new_ticker"]
            if target in state["positions"]:
                raise ValueError(
                    "Symbol-change target already held; explicit merger terms required"
                )
            if ticker in state.get("committees", {}):
                if target in state["committees"]:
                    raise ValueError("Symbol-change committee target already exists")
                state["committees"][target] = state["committees"].pop(ticker)
            state["positions"][target] = state["positions"].pop(ticker)
            state["pending"].pop(ticker, None)
            stamp(
                state,
                "symbol_change",
                day,
                id=key,
                old_ticker=ticker,
                new_ticker=target,
            )
        elif kind in ("cash_merger", "writeoff"):
            ccy = action.get("currency", currency)
            if kind == "cash_merger" and "cash_per_share" not in action:
                raise ValueError("Merger cash consideration is required")
            price = money(
                action["cash_per_share"]
                if kind == "cash_merger"
                else action.get("cash_per_share", "0")
            )
            if price < 0 or kind == "writeoff" and price != 0:
                raise ValueError("Invalid cash settlement")
            if kind == "writeoff" and action.get("confirmed_worthless") is not True:
                raise ValueError(
                    "Writeoff requires explicit final worthlessness confirmation"
                )
            proceeds = price * qty
            change_cash(state, ccy, proceeds)
            stamp(
                state,
                "exit",
                day,
                id=key,
                ticker=ticker,
                shares=qty,
                currency=ccy,
                price=str(price),
                proceeds=str(proceeds),
                realized_pnl=amount(proceeds * rate(state, ccy) - money(pos["cost"])),
                reason=kind,
            )
            del state["positions"][ticker]
            state["pending"].pop(ticker, None)
        else:
            target = action["new_ticker"]
            ratio = money(action["ratio"])
            fraction = money(action["stock_basis_fraction"])
            ccy = action.get("new_currency", currency)
            if ratio <= 0 or not 0 <= fraction <= 1:
                raise ValueError(
                    "Sourced share ratio and cost-basis allocation required"
                )
            if target in state["positions"]:
                raise ValueError(
                    "Already-held reorganization target needs separate lot consolidation"
                )
            if ccy not in ("USD", "CAD"):
                raise ValueError("Unsupported reorganization currency")
            child = copy.deepcopy(pos)
            child.pop("queued_exit", None)
            child["entry_date"] = action["effective_date"]
            child["action_origin"] = key
            child["currency"] = ccy
            child["entry_fx"] = str(rate(state, ccy))
            child["cost"] = str(money(pos["cost"]) * fraction)
            child["entry"] = str(money(action["new_reference_price"]))
            child["stop"] = str(money(action["new_stop"]))
            child["highest"] = child["entry"]
            if min(money(child["entry"]), money(child["stop"])) <= 0:
                raise ValueError(
                    "New instrument needs explicit reference price and protective stop"
                )
            exact = D(qty) * ratio
            if _fractional(
                state,
                child,
                exact,
                price=action.get("cash_in_lieu_price"),
                currency=ccy,
                day=day,
                event_id=key,
            ):
                state["positions"][target] = child
            if kind == "share_merger":
                boot = money(action.get("cash_per_share", "0")) * qty
                if boot < 0:
                    raise ValueError("Negative merger cash")
                change_cash(state, currency, boot)
                stamp(
                    state,
                    "reorganization_cash",
                    day,
                    id=key,
                    currency=currency,
                    proceeds=str(boot),
                    realized_pnl=amount(
                        boot * rate(state, currency)
                        - money(pos["cost"]) * (1 - fraction)
                    ),
                )
                del state["positions"][ticker]
            else:
                pos["cost"] = str(money(pos["cost"]) * (1 - fraction))
            state["pending"].pop(ticker, None)
            stamp(
                state,
                kind,
                day,
                id=key,
                ticker=ticker,
                new_ticker=target,
                ratio=str(ratio),
                stock_basis_fraction=str(fraction),
            )
    for key, r in a["receivables"].items():
        if not r["paid"] and r["pay_date"] <= day:
            change_cash(state, r["currency"], money(r["net"]))
            r["paid"] = True
            stamp(
                state,
                "dividend_payment",
                day,
                id=key,
                ticker=r["ticker"],
                currency=r["currency"],
                gross=r["gross"],
                net=r["net"],
            )


def cad_cash_usd(state):
    value = money(book(state)["cash_cad"])
    return value * rate(state, "CAD") if value else D(0)


def fx_required(state, snapshots):
    a = book(state)
    return bool(
        money(a["cash_cad"])
        or any(p.get("currency", "USD") == "CAD" for p in state["positions"].values())
        or any(
            r["currency"] == "CAD" and not r.get("paid")
            for r in a["receivables"].values()
        )
        or any(s.get("market", {}).get("currency") == "CAD" for s in snapshots.values())
    )


def research_snapshot(state, snapshot):
    out = copy.deepcopy(snapshot)
    market = out.get("market", {})
    ccy = market.get("currency", "USD")
    if ccy == "USD":
        return out
    if ccy != "CAD" or market.get("exchange") not in ("TSX", "TSXV"):
        raise ValueError("Unsupported market currency")
    multiplier = rate(state, ccy)
    for row in out["history"]:
        for key in ("o", "h", "l", "c", "ac"):
            row[key] = float(money(row[key]) * multiplier)
    for source in out["sources"]:
        if source["role"] == "price" and source.get("value") is not None:
            source["value"] = float(money(source["value"]) * multiplier)
    fccy = market.get("fundamentals_currency")
    if fccy not in ("USD", "CAD"):
        raise ValueError("CAD listing needs explicit fundamentals currency")
    if fccy == "CAD":
        for key in (
            "fcf_avg3",
            "mcap",
            "net_income",
            "ocf",
            "net_debt",
            "revenue",
            "dividends_paid",
        ):
            if out["context"]["fund"].get(key) is not None:
                out["context"]["fund"][key] = float(
                    money(out["context"]["fund"][key]) * multiplier
                )
    out["normalization"] = dict(
        quote_currency="CAD", risk_currency="USD", fx=copy.deepcopy(book(state)["fx"])
    )
    return out


def summary(state):
    a = book(state)
    foreign_position_fx = D(0)
    for p in state["positions"].values():
        if p.get("currency", "USD") == "CAD" and p.get("last_mark") is not None:
            foreign_position_fx += (
                money(p["last_mark"])
                * p["shares"]
                * (rate(state, "CAD") - money(p.get("entry_fx", rate(state, "CAD"))))
            )
    return dict(
        usd_cash=state["cash"],
        cad_cash=a["cash_cad"],
        cad_cash_usd=str(cad_cash_usd(state)),
        receivables_usd=str(receivable_value(state)),
        cad_cash_unrealized_fx_usd=str(cad_cash_usd(state) - money(a["cad_basis_usd"])),
        realized_cash_fx_usd=a["realized_fx_usd"],
        cash_fx_revaluation_usd=a["fx_revaluation_usd"],
        position_fx_usd=str(foreign_position_fx),
        fx_status=a["fx_status"],
        fx=copy.deepcopy(a["fx"]),
    )


def normalized_history(state, snapshot):
    """Convert explicitly raw split histories to today's share units exactly once."""
    ticker = snapshot["context"]["ticker"]
    splits = [
        r["terms"]
        for r in book(state)["actions"].values()
        if r["applied"]
        and r["terms"]["kind"] == "split"
        and r["terms"]["ticker"] == ticker
    ]
    if not splits:
        return snapshot
    basis = snapshot.get("market", {}).get("history_basis")
    if basis not in ("raw", "split_adjusted"):
        raise ValueError(
            "Known splits need explicit raw or split_adjusted history_basis"
        )
    if basis == "split_adjusted":
        return snapshot
    out = copy.deepcopy(snapshot)
    for row in out["history"]:
        factor = D(1)
        for split in splits:
            if row["d"] < split["effective_date"]:
                factor *= money(split["ratio"])
        for key in ("o", "h", "l", "c", "ac"):
            row[key] = float(money(row[key]) / factor)
        row["v"] = float(money(row["v"]) * factor)
    out["market"]["history_basis"] = "split_adjusted"
    return out


def validate_accounting(state):
    """Validate persisted extensions; legacy USD-only books remain readable."""
    a = state.get("accounting")
    for p in state["positions"].values():
        if (
            p.get("currency", "USD") not in ("USD", "CAD")
            or money(p.get("entry_fx", "1")) <= 0
        ):
            raise ValueError("Invalid position currency or entry FX")
    if a is None:
        if any(p.get("currency") == "CAD" for p in state["positions"].values()):
            raise ValueError("CAD position needs accounting state")
        return
    if not isinstance(a, dict):
        raise ValueError("Invalid accounting state")
    for key in ("cash_cad", "cad_basis_usd"):
        if money(a[key]) < 0:
            raise ValueError("Accounting balances must be nonnegative")
    for key in ("realized_fx_usd", "fx_revaluation_usd"):
        money(a[key])
    if a.get("fx_status") not in (
        "NOT_REQUIRED",
        "MISSING",
        "CURRENT",
        "PROVISIONAL_STALE",
    ):
        raise ValueError("Invalid FX status")
    for key in ("receivables", "actions", "conversions"):
        if not isinstance(a.get(key), dict):
            raise ValueError("Invalid accounting registry")
    for r in a["receivables"].values():
        if (
            r["currency"] not in ("USD", "CAD")
            or type(r["paid"]) is not bool
            or not 0 <= money(r["net"]) <= money(r["gross"])
        ):
            raise ValueError("Invalid receivable")
        date.fromisoformat(r["pay_date"])
    if a["fx"] is not None:
        fx = a["fx"]
        if (
            money(fx["rate"]) <= 0
            or fx.get("synthetic") is not state["synthetic"]
            or not timestamp(fx["observed_at"]) <= timestamp(fx["available_at"])
        ):
            raise ValueError("Invalid persisted FX observation")
    elif money(a["cash_cad"]) or any(
        p.get("currency") == "CAD" for p in state["positions"].values()
    ):
        raise ValueError("CAD exposure needs persisted FX observation")
