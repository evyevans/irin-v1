"""Pure, point-in-time benchmark comparisons from operator-supplied index levels.

No instrument defaults, downloads, selections, or execution are performed here.
See docs/BENCHMARKS.md for schemas, formulas, and unavailable-data semantics.
"""

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Context, Decimal, DecimalException, InvalidOperation, localcontext
from fractions import Fraction
import re

_CURRENCIES = ("USD", "CAD")
_RETURN_TYPES = ("TOTAL_RETURN", "PRICE_RETURN")
_METRICS = (
    "local_return_pct",
    "fx_return_pct",
    "reporting_return_pct",
    "annualized_volatility_pct",
    "max_drawdown_pct",
    "portfolio_return_pct",
    "relative_return_pct",
    "downside_capture_pct",
)


def _positive(value, label):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{label} must be a finite positive number")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{label} must be a finite positive number") from None
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return number


def _session(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("session must be an ISO YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("session must be a valid ISO date") from None


def _timestamp(value, label):
    if not isinstance(value, str) or len(value) < 17 or value[10:11] != "T":
        raise ValueError(f"{label} must be an ISO timestamp with timezone")
    _session(value[:10])
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        return stamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError(f"{label} must be an ISO timestamp with timezone") from None


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


def _rows(rows, value_key, *, observations=False, cutoff=None):
    if not isinstance(rows, list):
        raise ValueError("history must be a list")
    parsed = []
    prior = None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("history rows must be objects")
        session = row.get("session")
        day = _session(session)
        if prior is not None and session <= prior:
            raise ValueError("sessions must be unique and strictly increasing")
        prior = session
        item = dict(session=session, value=_positive(row.get(value_key), value_key))
        if "fx_usdcad" in row:
            item["fx_usdcad"] = _positive(row["fx_usdcad"], "fx_usdcad")
        if observations:
            available = _timestamp(row.get("available_at"), "available_at")
            if available.date() < day:
                raise ValueError("available_at cannot precede the observation session")
            item["available_at"] = available
        elif day > cutoff.date():
            raise ValueError("portfolio cannot include future sessions")
        parsed.append(item)
    return parsed


def _registry_entry(entry, portfolio):
    if not isinstance(entry, dict):
        raise ValueError("registry entries must be objects")
    for key in ("id", "category", "methodology"):
        _text(entry.get(key), key)
    if entry.get("currency") not in _CURRENCIES:
        raise ValueError("benchmark currency must be USD or CAD")
    if entry.get("return_type") not in _RETURN_TYPES:
        raise ValueError("benchmark return_type must be TOTAL_RETURN or PRICE_RETURN")
    source = entry.get("source")
    if isinstance(source, str):
        _text(source, "source")
    elif isinstance(source, dict) and source:
        for key, value in source.items():
            _text(key, "source key")
            _text(value, "source value")
    else:
        raise ValueError("source must be nonempty text or an object of nonempty text")
    if ("observations" in entry) == ("components" in entry):
        raise ValueError("provide exactly one of observations or components")
    if "observations" in entry:
        return _rows(entry["observations"], "value", observations=True)
    return _basket(entry, portfolio)


def _basket(entry, portfolio):
    components = entry["components"]
    if not isinstance(components, list) or not components:
        raise ValueError("components must be a nonempty list")
    parsed, seen = [], set()
    for component in components:
        if not isinstance(component, dict):
            raise ValueError("basket components must be objects")
        component_id = _text(component.get("id"), "component id")
        if component_id in seen:
            raise ValueError("component ids must be unique within a basket")
        seen.add(component_id)
        for key in ("currency", "return_type"):
            if key in component and component[key] != entry[key]:
                raise ValueError("components inherit basket currency and return_type")
        weight = _positive(component.get("weight"), "component weight")
        rows = _rows(component.get("observations"), "value", observations=True)
        parsed.append((weight, {row["session"]: row for row in rows}))
    if sum((Fraction(weight) for weight, _ in parsed), Fraction(0)) != 1:
        raise ValueError("initial component weights must sum exactly to one")
    if not portfolio or any(portfolio[0]["session"] not in rows for _, rows in parsed):
        return []
    first = [rows[portfolio[0]["session"]] for _, rows in parsed]
    baseline_availability = max(row["available_at"] for row in first)
    combined = []
    try:
        with localcontext(Context(prec=40)):
            for point in portfolio:
                if any(point["session"] not in rows for _, rows in parsed):
                    continue
                current = [rows[point["session"]] for _, rows in parsed]
                level = sum(
                    weight * row["value"] / initial["value"]
                    for (weight, _), row, initial in zip(parsed, current, first)
                )
                item = dict(
                    session=point["session"],
                    value=level,
                    available_at=max(
                        baseline_availability, *(row["available_at"] for row in current)
                    ),
                )
                rates = {row["fx_usdcad"] for row in current if "fx_usdcad" in row}
                if len(rates) > 1:
                    raise ValueError(
                        "basket components must share each session's fx_usdcad"
                    )
                if all("fx_usdcad" in row for row in current):
                    item["fx_usdcad"] = rates.pop()
                combined.append(item)
    except DecimalException:
        raise ValueError("basket arithmetic exceeds supported Decimal range") from None
    return combined


def _string(value):
    # Decimal strings preserve precision and serialize without non-finite JSON floats.
    return "0" if value == 0 else str(value.normalize())


def _returns(levels):
    return [after / before - 1 for before, after in zip(levels, levels[1:])]


def _conversion(row, currency, report_currency):
    if currency == report_currency:
        return Decimal(1)
    fx = row["fx_usdcad"]
    return fx if currency == "USD" else 1 / fx


def _metrics(result, rows, portfolio, currency, report_currency, periods_per_year):
    local = [row["value"] for row in rows]
    factors = [_conversion(row, currency, report_currency) for row in rows]
    benchmark = [level * factor for level, factor in zip(local, factors)]
    equity = [
        row["value"] * _conversion(row, "USD", report_currency) for row in portfolio
    ]
    benchmark_returns = _returns(benchmark)
    portfolio_returns = _returns(equity)
    metrics = dict(
        local_return_pct=100 * (local[-1] / local[0] - 1),
        fx_return_pct=100 * (factors[-1] / factors[0] - 1),
        reporting_return_pct=100 * (benchmark[-1] / benchmark[0] - 1),
        portfolio_return_pct=100 * (equity[-1] / equity[0] - 1),
    )
    metrics["relative_return_pct"] = (
        metrics["portfolio_return_pct"] - metrics["reporting_return_pct"]
    )
    peak, drawdown = benchmark[0], Decimal(0)
    for level in benchmark:
        peak = max(peak, level)
        drawdown = max(drawdown, 1 - level / peak)
    metrics["max_drawdown_pct"] = 100 * drawdown
    if len(benchmark_returns) >= 2:
        mean = sum(benchmark_returns) / len(benchmark_returns)
        variance = sum((value - mean) ** 2 for value in benchmark_returns) / (
            len(benchmark_returns) - 1
        )
        metrics["annualized_volatility_pct"] = (
            100 * (variance * periods_per_year).sqrt()
        )
    else:
        result["metric_reasons"]["annualized_volatility_pct"] = ["insufficient_periods"]
    downside = [(p, b) for p, b in zip(portfolio_returns, benchmark_returns) if b < 0]
    result["downside_periods"] = len(downside)
    if downside:
        # The counts cancel in the ratio of arithmetic means on the same periods.
        metrics["downside_capture_pct"] = (
            100 * sum(p for p, _ in downside) / sum(b for _, b in downside)
        )
    else:
        result["metric_reasons"]["downside_capture_pct"] = [
            "no_negative_benchmark_periods"
        ]
    result.update({name: _string(value) for name, value in metrics.items()})


def evaluate_benchmarks(
    portfolio: list[dict],
    registry: list[dict],
    *,
    as_of: str,
    report_currency="USD",
    portfolio_return_type="TOTAL_RETURN",
    periods_per_year=252,
) -> list[dict]:
    """Evaluate every configured benchmark on the exact portfolio session grid.

    Invalid schemas raise ValueError. Missing/incomparable data yields an explicit
    unavailable result with None metrics, preserving registry order and metadata.
    Input portfolio equities are always USD. Outputs use percentage units.
    """
    cutoff = _timestamp(as_of, "as_of")
    if report_currency not in _CURRENCIES:
        raise ValueError("report_currency must be USD or CAD")
    if portfolio_return_type not in _RETURN_TYPES:
        raise ValueError("portfolio_return_type must be TOTAL_RETURN or PRICE_RETURN")
    if type(periods_per_year) is not int or periods_per_year <= 0:
        raise ValueError("periods_per_year must be a positive integer")
    if not isinstance(registry, list):
        raise ValueError("registry must be a list")
    parsed_portfolio = _rows(portfolio, "equity", cutoff=cutoff)
    parsed_registry = []
    seen = set()
    for entry in registry:
        rows = _registry_entry(entry, parsed_portfolio)
        if entry["id"] in seen:
            raise ValueError("registry ids must be unique")
        seen.add(entry["id"])
        parsed_registry.append((entry, rows))
    results = []
    for entry, rows in parsed_registry:
        result = {
            key: deepcopy(entry[key])
            for key in (
                "id",
                "category",
                "currency",
                "return_type",
                "methodology",
                "source",
            )
        }
        result["construction"] = (
            "FIXED_WEIGHT_BUY_AND_HOLD" if "components" in entry else "OBSERVATIONS"
        )
        if "components" in entry:
            result["components"] = [
                dict(id=component["id"], weight=str(component["weight"]))
                for component in entry["components"]
            ]
        result.update(
            status="unavailable",
            report_currency=report_currency,
            portfolio_return_type=portfolio_return_type,
            as_of=cutoff.isoformat(),
            sessions=[row["session"] for row in parsed_portfolio],
            reasons=[],
            metric_reasons={},
            missing_sessions=[],
            unavailable_sessions=[],
            downside_periods=0,
        )
        result.update({metric: None for metric in _METRICS})
        if len(parsed_portfolio) < 2:
            result["reasons"].append("insufficient_history")
        if entry["return_type"] != portfolio_return_type:
            result["reasons"].append("return_type_mismatch")
        by_session = {row["session"]: row for row in rows}
        matched = []
        for point in parsed_portfolio:
            observation = by_session.get(point["session"])
            if observation is None:
                result["missing_sessions"].append(point["session"])
            elif observation["available_at"] > cutoff:
                result["unavailable_sessions"].append(point["session"])
            else:
                matched.append(observation)
        if result["missing_sessions"]:
            result["reasons"].append("missing_sessions")
        if result["unavailable_sessions"]:
            result["reasons"].append("observations_not_yet_available")
        if entry["currency"] != report_currency and any(
            "fx_usdcad" not in row for row in matched
        ):
            result["reasons"].append("missing_benchmark_fx")
        if report_currency == "CAD" and any(
            "fx_usdcad" not in row for row in parsed_portfolio
        ):
            result["reasons"].append("missing_portfolio_fx")
        if not result["reasons"]:
            try:
                with localcontext(Context(prec=40)):
                    _metrics(
                        result,
                        matched,
                        parsed_portfolio,
                        entry["currency"],
                        report_currency,
                        periods_per_year,
                    )
            except DecimalException:
                raise ValueError(
                    "benchmark arithmetic exceeds supported Decimal range"
                ) from None
            result["status"] = "available"
        results.append(result)
    return results
