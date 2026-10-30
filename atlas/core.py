"""Validate local snapshots before applying the pure equity research rules.

Provenance is operator-supplied metadata, never independent verification.
This module has no network, database, messaging, or execution capability.
"""

import copy
from datetime import date, datetime, timezone
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

from engine import aplus, indicators


class InputError(ValueError):
    """A snapshot cannot be interpreted safely."""


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise InputError(
            "Timestamps must be ISO 8601 with an explicit timezone."
        ) from None


def number(value, label, minimum=None, maximum=None, integer=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or abs(value) > 1e24
        or not math.isfinite(value)
    ):
        raise InputError(f"{label} must be a finite number.")
    if (
        minimum is not None
        and value < minimum
        or maximum is not None
        and value > maximum
    ):
        raise InputError(f"{label} is outside its allowed range.")
    if integer and int(value) != value:
        raise InputError(f"{label} must be an integer.")
    return value


def finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise InputError("Nonfinite numbers are not accepted.")
    if isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)


def mapping(value, label):
    if not isinstance(value, dict):
        raise InputError(f"{label} must be an object.")
    return value


def normalize_history(rows):
    if not isinstance(rows, list) or not rows or len(rows) > 10000:
        raise InputError("history must contain between 1 and 10000 daily rows.")
    normalized, prior = [], None
    for row in rows:
        mapping(row, "history row")
        try:
            day = date.fromisoformat(row["d"]).isoformat()
        except (KeyError, ValueError, TypeError):
            raise InputError("History dates must be YYYY-MM-DD.") from None
        if prior and day <= prior:
            raise InputError("History dates must be unique and increasing.")
        if any(k not in row for k in ("o", "h", "l", "c", "ac", "v")):
            raise InputError("Each history row needs o, h, l, c, ac and v.")
        for field in ("o", "h", "l", "c", "ac"):
            number(row[field], f"history.{field}", minimum=1e-12)
        number(row["v"], "history.v", minimum=0)
        if row["h"] < max(row["o"], row["c"], row["l"]) or row["l"] > min(
            row["o"], row["c"]
        ):
            raise InputError("History OHLC bounds are inconsistent.")
        normalized.append({k: row[k] for k in ("d", "o", "h", "l", "c", "ac", "v")})
        normalized[-1]["xok"] = False  # recomputed from provenance below
        prior = day
    return normalized


def evaluate_snapshot(snapshot, *, as_of):
    mapping(snapshot, "snapshot")
    finite_tree(snapshot)
    if (
        snapshot.get("schema_version") != 1
        or type(snapshot.get("synthetic")) is not bool
    ):
        raise InputError(
            "schema_version 1 and an explicit synthetic boolean are required."
        )
    now = timestamp(as_of)
    rows = normalize_history(snapshot.get("history"))
    ctx = copy.deepcopy(mapping(snapshot.get("context"), "context"))
    for field in (
        "row",
        "fund",
        "portfolio",
        "flags",
        "val_stats",
        "regime",
        "fe_counts",
        "chain",
    ):
        mapping(ctx.get(field), f"context.{field}")
    for field in ("ticker", "name"):
        if not isinstance(ctx.get(field), str) or not 1 <= len(ctx[field]) <= 160:
            raise InputError(
                f"context.{field} must be a nonempty string, at most 160 characters."
            )
    for field in ("layer", "subsector", "focus_segment", "business_model", "stage"):
        if (
            field in ctx["row"]
            and ctx["row"][field] is not None
            and not isinstance(ctx["row"][field], str)
        ):
            raise InputError(f"row.{field} must be a string or null.")
    if any(
        ord(char) < 32 or ord(char) == 127
        for field in ("ticker", "name")
        for char in ctx[field]
    ):
        raise InputError(
            "Names and tickers may not contain terminal control characters."
        )
    if type(ctx["row"].get("us_listed")) is not bool:
        raise InputError("context.row.us_listed must be a boolean.")
    pf = ctx["portfolio"]
    number(pf.get("equity_usd"), "portfolio.equity_usd", minimum=1e-9)
    for field in ("drawdown_pct", "invested_pct"):
        number(pf.get(field), f"portfolio.{field}", minimum=0, maximum=100)
    number(
        pf.get("open_positions"),
        "portfolio.open_positions",
        minimum=0,
        maximum=10000,
        integer=True,
    )
    number(
        pf.get("trades_created"), "portfolio.trades_created", minimum=0, integer=True
    )
    mapping(pf.get("layer_weight_pct"), "portfolio.layer_weight_pct")
    for value in pf["layer_weight_pct"].values():
        number(value, "portfolio.layer_weight_pct", minimum=0, maximum=100)
    if (
        "paused_until_month_end" in pf
        and type(pf["paused_until_month_end"]) is not bool
    ):
        raise InputError("paused_until_month_end must be a boolean.")
    score = number(ctx.get("score"), "context.score", minimum=0, maximum=100)
    for field in ("dc", "dc_quant"):
        if field in ctx["fe_counts"]:
            number(
                ctx["fe_counts"][field], f"fe_counts.{field}", minimum=0, integer=True
            )
    boolean_facts = {"available", "ocf_all_positive_10y"}
    nonnegative_facts = {
        "mcap",
        "revenue",
        "de",
        "current_ratio",
        "pe",
        "ps",
        "ev_ebit",
        "ev_ebitda",
        "div_yield",
        "payout",
        "dividends_paid",
        "rnd_to_rev",
        "rnd_capex_to_rev",
        "runway_years",
        "earn_pos_streak",
        "ocf_pos_streak",
    }
    for field, value in ctx["fund"].items():
        if value is None:
            continue
        if field in boolean_facts:
            if type(value) is not bool:
                raise InputError(f"fund.{field} must be a boolean or null.")
        elif field == "sbc_to_fcf_3y":
            if not isinstance(value, list) or len(value) != 3:
                raise InputError(
                    "sbc_to_fcf_3y requires exactly three annual numeric ratios."
                )
            for member in value:
                number(member, "sbc_to_fcf_3y", minimum=0)
        else:
            number(
                value,
                f"fund.{field}",
                minimum=0 if field in nonnegative_facts else None,
                integer=field in {"earn_pos_streak", "ocf_pos_streak"},
            )
    if ctx.get("spread_pct") is not None:
        number(ctx["spread_pct"], "spread_pct", minimum=0, maximum=100)
    if ctx.get("max_corr") is not None:
        number(ctx["max_corr"], "max_corr", minimum=-1, maximum=1)
    for field in ("ev_ebitda_p90", "vol260_median"):
        if ctx["val_stats"].get(field) is not None:
            number(ctx["val_stats"][field], f"val_stats.{field}", minimum=0)
    mapping(ctx["val_stats"].get("median_ev_ebitda", {}), "val_stats.median_ev_ebitda")
    for value in ctx["val_stats"].get("median_ev_ebitda", {}).values():
        if value is not None:
            number(value, "val_stats.median_ev_ebitda", minimum=0)
    flags = ctx["flags"].get("flags")
    if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
        raise InputError("flags.flags must be a string array.")
    for field in ("known", "adverse"):
        if type(ctx["regime"].get(field)) is not bool:
            raise InputError(f"regime.{field} must be a boolean.")
    sources = snapshot.get("sources")
    if not isinstance(sources, list) or len(sources) > 200:
        raise InputError("sources must be an array of at most 200 records.")
    valid, ids, provenance_failures = [], set(), []
    for source in sources:
        mapping(source, "source")
        sid = source.get("id")
        if not isinstance(sid, str) or not sid or sid in ids:
            raise InputError("Source IDs must be nonempty and unique.")
        ids.add(sid)
        for key in ("publisher", "upstream", "url", "label", "content_sha256"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                raise InputError(f"Each source requires {key}.")
        if not re.fullmatch("[a-f0-9]{64}", source["content_sha256"]):
            raise InputError(
                "Source content_sha256 must contain 64 lowercase hexadecimal characters."
            )
        if source.get("role") not in ("price", "filing", "bottleneck"):
            raise InputError("Source role must be price, filing or bottleneck.")
        try:
            url = urlsplit(source["url"])
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError
        except ValueError:
            raise InputError(
                "Source URLs must be HTTPS without credentials, queries or fragments."
            ) from None
        observed, available = timestamp(source.get("observed_at")), timestamp(
            source.get("available_at")
        )
        synthetic_source = (
            source["label"] == "synthetic"
            or url.hostname.endswith(".invalid")
            or source["content_sha256"] == "0" * 64
        )
        valid_label = source["label"] == (
            "synthetic" if snapshot["synthetic"] else "operator_attested"
        )
        max_age = {"price": 96, "filing": 24 * 395, "bottleneck": 24 * 730}[
            source["role"]
        ]
        age = (now - observed).total_seconds() / 3600
        okay = (
            valid_label
            and (snapshot["synthetic"] or not synthetic_source)
            and observed <= available <= now
            and 0 <= age <= max_age
        )
        if source["role"] == "price":
            okay = okay and observed.date().isoformat() == rows[-1]["d"]
            if not snapshot["synthetic"] and valid_label and not synthetic_source:
                value = number(source.get("value"), "source.value", minimum=1e-12)
                reference = rows[-1]["c"]
                okay = (
                    okay and abs(value - reference) / ((value + reference) / 2) <= 0.005
                )
        if okay:
            valid.append(source)
        else:
            provenance_failures.append(
                f"Source {sid}: stale, future, synthetic/real mismatch, or invalid availability."
            )

    def independent(role):
        chosen = [s for s in valid if s["role"] == role]
        # Both publisher and declared upstream must differ. Metadata remains an attestation.
        return min(
            len({s["publisher"].strip().casefold() for s in chosen}),
            len({s["upstream"].strip().casefold() for s in chosen}),
        )

    price_ok = independent("price") >= 2 and rows[-1]["d"] <= now.date().isoformat()
    bottleneck_count = independent("bottleneck")
    filings = {s["id"] for s in valid if s["role"] == "filing"}
    links = mapping(snapshot.get("chain_sources"), "chain_sources")
    required = ("ai_demand", "customer_contract", "revenue_backlog", "margin_cash_flow")
    complete_chain = all(
        isinstance(ctx["chain"].get(key), str)
        and bool(ctx["chain"][key].strip())
        and isinstance(links.get(key), list)
        and links[key]
        and all(isinstance(sid, str) and sid in filings for sid in links[key])
        for key in required
    )
    gates = []
    if not price_ok:
        gates.append(
            "Two fresh independent price attestations are required (96-hour maximum age)."
        )
    if bottleneck_count < 2:
        gates.append("Two independent bottleneck source attestations are required.")
    if not filings:
        gates.append(
            "A current filing source attestation is required (395-day maximum age)."
        )
    if not complete_chain:
        gates.append(
            "The complete demand-to-cash-flow chain must link to eligible filing evidence."
        )
    gates.extend(provenance_failures)
    # Canadian eligibility is derived from the market contract, never a caller-supplied flag.
    market = snapshot.get("market", {})
    ctx["row"]["allowed_listing"] = bool(
        market.get("currency") == "CAD" and market.get("exchange") in ("TSX", "TSXV")
    )
    # Never accept precomputed technicals, claimed verification counts, or looser policy caps.
    rows[-1]["xok"] = price_ok
    try:
        ctx["ind"] = indicators.compute(rows)
        finite_tree(ctx["ind"])
    except (OverflowError, ZeroDivisionError):
        raise InputError("History produced invalid derived indicators.") from None
    ctx["price_status"] = "VERIFIED_DELAYED" if price_ok else "UNVERIFIED"
    ctx["chain_missing"] = [] if complete_chain else list(required)
    ctx["chain"] = (
        {key: "Verified fact (operator attestation only)" for key in required}
        if complete_chain
        else {}
    )
    ctx["bottleneck_sources"] = bottleneck_count
    ctx["score_tier_a"] = score >= 85
    ctx["direct_material"] = ctx.get("direct_material") is True and complete_chain
    ctx["fe_counts"]["dc_quant"] = (
        ctx["fe_counts"].get("dc_quant", 0) if filings and complete_chain else 0
    )
    ctx["fe_snippet"] = None
    ctx["focus_db"] = {}  # no inherited approvals or database assertions
    if filings and complete_chain:
        ctx["focus_db"] = {
            "focus_segment": ctx["row"].get("focus_segment"),
            "relevance_material": ctx["direct_material"],
            "grade_a_relevance_source": True,
        }
    project = ctx.get("project_evidence", {})
    mapping(project, "project_evidence")
    for field in ("financing", "permitting"):
        evidence = project.get(field)
        credible = False
        if evidence is not None:
            mapping(evidence, "project_evidence." + field)
            refs = evidence.get("source_ids")
            if (
                type(evidence.get("credible")) is not bool
                or not isinstance(refs, list)
                or any(not isinstance(sid, str) for sid in refs)
            ):
                raise InputError(
                    "Project evidence needs credible boolean and source_ids array"
                )
            credible = bool(evidence["credible"] and refs and set(refs) <= filings)
        ctx["row"][field + "_credible"] = credible
        if ctx["focus_db"]:
            ctx["focus_db"][field + "_credible"] = credible
    if not filings:
        ctx["flags"]["status"] = "unavailable"
    ctx["db"] = dict(
        max_risk_pct_tier_b=0.5,
        freq_max_initial_weight_pct=5,
        max_total_weight_pct=10,
        max_open_positions=7,
        min_cash_pct=20,
        ramp_factor=0.5,
        ramp_first_n_trades=4,
    )
    try:
        result = aplus.evaluate(ctx, aplus.load_config())
    except (TypeError, ValueError, KeyError, ZeroDivisionError, OverflowError):
        raise InputError(
            "Context fields do not satisfy the equity input contract. See docs/INPUTS.md."
        ) from None
    # Published output uses descriptive checks, not named-investor endorsements or "verified" market claims.
    return dict(
        version="1.2.0",
        mode="RESEARCH_ONLY",
        status="RULES_PASS" if not gates and not result["failing"] else "NO_TRADE",
        synthetic=snapshot["synthetic"],
        evidence_status=(
            "SYNTHETIC"
            if snapshot["synthetic"]
            else "OPERATOR_ATTESTED_NOT_INDEPENDENTLY_VERIFIED"
        ),
        as_of=now.isoformat(),
        ticker=ctx["ticker"],
        name=ctx["name"],
        price_date=rows[-1]["d"],
        input_sha256=hashlib.sha256(
            json.dumps(
                snapshot, sort_keys=True, allow_nan=False, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        config_sha256=result["config_sha256"],
        rule_version=result["rule_version"],
        grade=result["grade"],
        gates=gates,
        checks=result["checks"],
        failing=result["failing"],
        reasons=result["plain_fail"],
        hypothetical_sizing=result["sizing"],
        execution_enabled=False,
        limitations=[
            "Input attestations are not independently verified.",
            "RULES_PASS is not an order, prediction, endorsement or return estimate.",
            "This standalone research result is not a paper order; use explicit paper commands for the separate simulated ledger.",
        ],
    )
