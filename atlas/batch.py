"""Offline, operator-defined peer universes; no inherited universe or approvals."""

import copy
import hashlib
import json
import statistics
from pathlib import Path

from engine import aplus, indicators
from .core import InputError, evaluate_snapshot, normalize_history, timestamp


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _returns(rows):
    # The entire interval must match: an absent session is never a daily zero
    # return, nor is a multi-session return paired with a one-session return.
    window = rows[-253:]
    return {(a["d"], b["d"]): b["ac"] / a["ac"] - 1 for a, b in zip(window, window[1:])}


def evaluate_batch(snapshots, *, held, as_of, fx=None):
    """Evaluate a complete caller-defined universe with computed peer context.

    Returned provenance describes supplied attestations, never verification.
    Caller objects are not mutated. All portfolio figures remain USD.
    """
    now = timestamp(as_of)
    if not isinstance(snapshots, list) or not 1 <= len(snapshots) <= 1000:
        raise InputError("Batch requires between 1 and 1000 snapshots.")
    if not isinstance(held, list) or any(not isinstance(t, str) or not t for t in held):
        raise InputError("held must be an explicit ticker array.")
    if len(set(held)) != len(held):
        raise InputError("Duplicate held ticker.")
    prepared, initial, histories, originals = {}, {}, {}, {}
    session = mode = portfolio = None
    for original in snapshots:
        if not isinstance(original, dict) or not isinstance(
            original.get("context"), dict
        ):
            raise InputError("Each batch snapshot needs an object context.")
        snapshot = copy.deepcopy(original)
        # Claimed derived context is neither used nor required to be valid.
        snapshot.setdefault("context", {})["val_stats"] = {}
        snapshot["context"]["max_corr"] = None
        result = evaluate_snapshot(snapshot, as_of=as_of)
        ticker = result["ticker"]
        if ticker in prepared:
            raise InputError("Duplicate batch ticker.")
        if result["price_date"] > now.date().isoformat():
            raise InputError("Batch histories cannot include future sessions.")
        if session is not None and (
            session != result["price_date"] or mode != result["synthetic"]
        ):
            raise InputError("Batch snapshots must share a session and synthetic mode.")
        current_portfolio = snapshot["context"]["portfolio"]
        if portfolio is not None and portfolio != current_portfolio:
            raise InputError("Batch snapshots must share one portfolio context.")
        session, mode, portfolio = (
            result["price_date"],
            result["synthetic"],
            current_portfolio,
        )
        prepared[ticker], initial[ticker] = snapshot, result
        originals[ticker] = original
    if set(held) - set(prepared):
        raise InputError("Every held ticker needs its own supplied snapshot.")
    if portfolio["open_positions"] != len(held):
        raise InputError("held must match the shared portfolio position count.")

    # Explicit dated FX is necessary for CAD prices and USD research sizing.
    from .paper import initialize
    from .accounting import fx_mark, research_snapshot, book

    fx_state = initialize("1", synthetic=mode)
    fx_mark(fx_state, fx, as_of=as_of)
    for ticker, snapshot in prepared.items():
        if snapshot.get("market", {}).get("currency", "USD") == "CAD":
            if book(fx_state)["fx_status"] != "CURRENT":
                raise InputError("CAD batch research needs fresh explicit FX.")
            prepared[ticker] = research_snapshot(fx_state, snapshot)
        histories[ticker] = normalize_history(prepared[ticker]["history"])

    eligibility = {}
    multiples, utilities, volatilities, sectors = [], [], [], {}
    for ticker in sorted(prepared):
        gates = initial[ticker]["gates"]
        # Keep failures in the actual result, while preventing unusable peer
        # observations from changing other names' valuation thresholds.
        reasons = [
            g
            for g in gates
            if g.startswith("Source ")
            or "price attestations" in g
            or "filing source attestation" in g
        ]
        if prepared[ticker]["context"]["fund"].get("available") is not True:
            reasons.append("fundamentals_unavailable")
        eligibility[ticker] = dict(eligible=not reasons, reasons=reasons)
        if reasons:
            continue
        context = prepared[ticker]["context"]
        multiple = context["fund"].get("ev_ebitda")
        if multiple is not None and multiple > 0:
            multiples.append(multiple)
            segment = aplus.segment(context["row"])
            sectors.setdefault(segment, []).append(multiple)
            if segment in ("utility_regulated", "ipp"):
                utilities.append(multiple)
        volatility = indicators.compute(histories[ticker]).get("vol260")
        if volatility is not None and volatility > 0:
            volatilities.append(volatility)
    multiples.sort()
    medians = {
        key: statistics.median(values) if len(values) >= 5 else None
        for key, values in sorted(sectors.items())
    }
    medians["utility_ipp"] = (
        statistics.median(utilities) if len(utilities) >= 5 else None
    )
    stats = dict(
        median_ev_ebitda=medians,
        ev_ebitda_p90=(
            multiples[int(0.9 * (len(multiples) - 1))] if len(multiples) >= 10 else None
        ),
        vol260_median=(
            statistics.median(volatilities) if len(volatilities) >= 10 else None
        ),
    )

    correlations, results = {}, []
    returns = {ticker: _returns(rows) for ticker, rows in histories.items()}
    for ticker in sorted(prepared):
        pairs = []
        for peer in sorted(set(held) - {ticker}):
            matched = len(set(returns[ticker]) & set(returns[peer]))
            eligible = eligibility[ticker]["eligible"] and eligibility[peer]["eligible"]
            value = (
                indicators.correlation(returns[ticker], returns[peer])
                if eligible
                else None
            )
            if value is not None:
                value = max(-1.0, min(1.0, value))
            pairs.append(
                dict(
                    ticker=peer,
                    matched_intervals=matched,
                    correlation=value,
                    reason=(
                        None
                        if value is not None
                        else (
                            "ineligible_peer_evidence"
                            if not eligible
                            else (
                                "insufficient_intervals"
                                if matched < 60
                                else "zero_variance"
                            )
                        )
                    ),
                )
            )
        maximum = (
            max(p["correlation"] for p in pairs)
            if pairs and all(p["correlation"] is not None for p in pairs)
            else None
        )
        correlations[ticker] = dict(max_corr=maximum, pairs=pairs)
        prepared[ticker]["context"]["val_stats"] = copy.deepcopy(stats)
        prepared[ticker]["context"]["max_corr"] = maximum
        results.append(evaluate_snapshot(prepared[ticker], as_of=as_of))
    return dict(
        schema_version=1,
        mode="RESEARCH_ONLY",
        as_of=now.isoformat(),
        session=session,
        synthetic=mode,
        universe=sorted(prepared),
        held=sorted(held),
        val_stats=stats,
        peer_counts=dict(
            ev_ebitda=len(multiples),
            utility_ipp=len(utilities),
            vol260=len(volatilities),
            segments={k: len(v) for k, v in sorted(sectors.items())},
        ),
        eligibility=eligibility,
        correlations=correlations,
        provenance={
            t: dict(
                input_sha256=_digest(originals[t]),
                sources=copy.deepcopy(originals[t]["sources"]),
                chain_sources=copy.deepcopy(originals[t]["chain_sources"]),
            )
            for t in sorted(prepared)
        },
        fx=copy.deepcopy(fx),
        results=results,
        execution_enabled=False,
        limitations=[
            "Peer statistics describe only the supplied universe; selection bias is possible.",
            "Source metadata and fundamentals remain operator attestations.",
            "Correlations use local adjusted-price returns, not USD FX-adjusted returns.",
        ],
    )


def add_commands(commands):
    parser = commands.add_parser("batch", help="Evaluate an offline snapshot universe")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", type=Path, required=True)


def _load(path):
    if path.stat().st_size > 10_000_000:
        raise InputError("Batch input exceeds the 10 MB limit.")
    return json.loads(path.read_text(encoding="utf-8"))


def execute(args):
    manifest = _load(args.manifest)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise InputError("Batch manifest schema_version must be 1.")
    paths = manifest.get("snapshots")
    if (
        not isinstance(paths, list)
        or not 1 <= len(paths) <= 1000
        or any(not isinstance(p, str) or not p for p in paths)
    ):
        raise InputError("Manifest snapshots must be a nonempty path array.")
    snapshots = [_load(args.manifest.parent / path) for path in paths]
    bundle = evaluate_batch(
        snapshots, held=manifest.get("held"), as_of=args.as_of, fx=manifest.get("fx")
    )
    from .demo import write_results

    write_results(bundle["results"], args.output)
    (args.output / "batch.json").write_text(
        json.dumps(bundle, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        "Offline batch evaluated; batch.json, results.json and report.html written. Execution disabled."
    )
    return bundle
