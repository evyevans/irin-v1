"""Generic SEC and FRED observations; supplied evidence remains an attestation."""

import csv, hashlib, html, io, json, math, os, re, time, urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from .core import timestamp
from .cloud import NoRedirect

ANNUAL = ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A")
FLOW = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "Revenue",
    ],
    "operating_income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLossAttributableToOwnersOfParent",
        "ProfitLoss",
    ],
    "ocf": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "CashFlowsFromUsedInOperatingActivities",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    ],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "d_and_a": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "Depreciation",
    ],
    "rnd": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "interest_expense": [
        "InterestExpense",
        "InterestExpenseNonoperating",
        "InterestExpenseDebt",
        "InterestAndDebtExpense",
        "InterestPaidNet",
        "FinanceCosts",
    ],
    "dividends_paid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        "DividendsCommonStockCash",
        "DividendsPaidClassifiedAsFinancingActivities",
    ],
}
INSTANT = {
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashAndCashEquivalents",
    ],
    "debt_total": [
        "LongTermDebt",
        "DebtLongtermAndShorttermCombinedAmount",
        "Borrowings",
    ],
    "debt_noncurrent": [
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
    ],
    "debt_current": [
        "LongTermDebtCurrent",
        "DebtCurrent",
        "LongTermDebtAndCapitalLeaseObligationsCurrent",
    ],
    "short_term_borrowings": ["ShortTermBorrowings", "CommercialPaper"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "Equity",
    ],
    "current_assets": ["AssetsCurrent", "CurrentAssets"],
    "current_liabilities": ["LiabilitiesCurrent", "CurrentLiabilities"],
    "rpo": ["RevenueRemainingPerformanceObligation"],
}

# LongTermDebt does not include separately disclosed short-term borrowing.
# Keep it separate from explicitly combined debt to prevent double counting.
INSTANT["debt_total"] = ["DebtLongtermAndShorttermCombinedAmount", "Borrowings"]
INSTANT["debt_longterm"] = ["LongTermDebt"]
NONNEGATIVE = {
    "capex",
    "cash",
    "debt_total",
    "debt_longterm",
    "debt_noncurrent",
    "debt_current",
    "short_term_borrowings",
    "diluted_shares",
}


def _number(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or abs(value) > 1e24
    ):
        raise ValueError("Expected a finite numeric observation")
    return value


def _companyfacts_shape(payload):
    def obj(value, label):
        if not isinstance(value, dict):
            raise ValueError(label + " must be an object")
        return value

    facts = obj(obj(payload, "companyfacts").get("facts", {}), "facts")
    for namespace, tags in facts.items():
        for concept, record in obj(tags, "taxonomy namespace").items():
            units = obj(obj(record, "concept").get("units", {}), "units")
            for unit, rows in units.items():
                if not isinstance(rows, list):
                    raise ValueError("Unit observations must be an array")
                for row in rows:
                    obj(row, "observation")
    return facts


def extract_companyfacts(payload, *, as_of, currency="USD", price=None):
    """Select coherent annual facts filed BEFORE the UTC evaluation date.

    SEC companyfacts has filing dates rather than public dissemination timestamps.
    Excluding same-day filings avoids claiming unsupported intraday availability.
    Values are never joined across fiscal end dates or currency units.
    """
    cutoff = timestamp(as_of).date()
    if currency not in ("USD", "CAD"):
        raise ValueError("currency must be USD or CAD")
    if price is not None and _number(price) <= 0:
        raise ValueError("price must be positive in the selected currency")
    series, provenance = {}, {}
    facts = _companyfacts_shape(payload)
    for field, concepts in {**FLOW, **INSTANT}.items():
        unit = (
            "shares"
            if field == "diluted_shares"
            else currency + "/shares" if field == "eps_diluted" else currency
        )
        candidates = {}
        for namespace in ("us-gaap", "ifrs-full"):
            for rank, concept in enumerate(concepts):
                for row in (
                    facts.get(namespace, {})
                    .get(concept, {})
                    .get("units", {})
                    .get(unit, [])
                ):
                    if (
                        any(
                            not isinstance(row.get(k), str)
                            for k in ("end", "filed", "form")
                        )
                        or "val" not in row
                    ):
                        raise ValueError("Observation needs end, filed, form and val")
                    end = date.fromisoformat(row["end"])
                    filed = date.fromisoformat(row["filed"])
                    if (
                        row.get("form") not in ANNUAL
                        or filed >= cutoff
                        or end > filed
                        or end >= cutoff
                    ):
                        continue
                    if field in FLOW:
                        if (
                            not isinstance(row.get("start"), str)
                            or not 330
                            <= (end - date.fromisoformat(row["start"])).days
                            <= 400
                        ):
                            continue
                    value = _number(row["val"])
                    if field in NONNEGATIVE and value < 0:
                        raise ValueError(
                            "Negative "
                            + field
                            + " requires explicit reviewed taxonomy normalization"
                        )
                    key = row["end"]
                    selection = (
                        (-rank, row["filed"], namespace, row.get("accn", ""))
                        if field == "debt_total"
                        else (row["filed"], -rank, namespace, row.get("accn", ""))
                    )
                    if key not in candidates or selection > candidates[key][0]:
                        candidates[key] = (
                            selection,
                            value,
                            dict(
                                concept=concept,
                                taxonomy=namespace,
                                unit=unit,
                                accession=row.get("accn"),
                                filed=row["filed"],
                                period_end=key,
                                start=row.get("start"),
                            ),
                        )
        keys = sorted(candidates)[-11:]
        series[field] = {k: candidates[k][1] for k in keys}
        provenance[field] = {k: candidates[k][2] for k in keys}
    out = dict(
        status="derived_observations",
        currency=currency,
        as_of=as_of,
        series=series,
        provenance=provenance,
        availability_policy="filings_before_evaluation_utc_date",
        warning="Standard taxonomy mappings require review; issuer extensions and segment facts are not inferred.",
    )
    out["metrics"] = derive_metrics(series, price=price)
    out["debt_basis"] = out["metrics"].pop("debt_basis")
    return out


def derive_metrics(series, *, price=None):
    """Annual metrics at the latest available revenue fiscal end; None means missing."""
    for field, values in series.items():
        for value in values.values():
            _number(value)
            if field in NONNEGATIVE and value < 0:
                raise ValueError(
                    "Negative "
                    + field
                    + " requires explicit reviewed taxonomy normalization"
                )
    ends = sorted(series.get("revenue", {}))
    end = ends[-1] if ends else None

    def at(field, period=end):
        return series.get(field, {}).get(period)

    def ratio(a, b):
        return a / b if a is not None and b is not None and b > 0 else None

    def add(a, b):
        return a + b if a is not None and b is not None else None

    def sub(a, b):
        return a - b if a is not None and b is not None else None

    def growth(values, years):
        keys = sorted(values)
        if len(keys) < years + 1:
            return None
        selected = keys[-years - 1 :]
        # Require genuinely annual observations, rather than treating gaps as years.
        if any(
            not 300 <= (date.fromisoformat(b) - date.fromisoformat(a)).days <= 430
            for a, b in zip(selected, selected[1:])
        ):
            return None
        a, b = values[selected[0]], values[selected[-1]]
        return (b / a) ** (1 / years) - 1 if a > 0 and b > 0 else None

    def streak(values):
        n = 0
        previous = None
        for k in sorted(values, reverse=True):
            if (
                values[k] <= 0
                or previous
                and not 300
                <= (date.fromisoformat(previous) - date.fromisoformat(k)).days
                <= 430
            ):
                break
            n += 1
            previous = k
        return n

    rev, oi, ni, ocf, capex, cash, eq, da = (
        at(k)
        for k in (
            "revenue",
            "operating_income",
            "net_income",
            "ocf",
            "capex",
            "cash",
            "equity",
            "d_and_a",
        )
    )
    debt = at("debt_total")
    debt_basis = "explicit_combined" if debt is not None else None
    if debt is None and at("debt_longterm") is not None:
        debt = at("debt_longterm")
        debt_basis = "long_term_only"
        if at("short_term_borrowings") is not None:
            debt += at("short_term_borrowings")
            debt_basis = "long_term_plus_separate_short_term"
    if debt is None:
        debt = add(at("debt_current"), at("debt_noncurrent"))
        if debt is not None:
            debt_basis = "current_plus_noncurrent"
    # A combined/current amount already includes its borrowing components.
    shares = at("diluted_shares")
    fcf = sub(ocf, capex)
    nd = sub(debt, cash)
    mcap = (
        price * shares
        if price is not None and shares is not None and shares > 0
        else None
    )
    ev = add(mcap, nd)
    ebitda = add(oi, da)
    fcf_series = {
        k: v - series["capex"][k]
        for k, v in series.get("ocf", {}).items()
        if k in series.get("capex", {})
    }
    fcfps = {
        k: v / series["diluted_shares"][k]
        for k, v in fcf_series.items()
        if series.get("diluted_shares", {}).get(k, 0) > 0
    }

    def rolling_keys(*fields):
        common = set(series.get(fields[0], {}))
        for field in fields[1:]:
            common &= set(series.get(field, {}))
        keys = sorted(k for k in common if end is not None and k <= end)[-3:]
        if len(keys) != 3 or keys[-1] != end:
            return []
        if any(
            not 300 <= (date.fromisoformat(b) - date.fromisoformat(a)).days <= 430
            for a, b in zip(keys, keys[1:])
        ):
            return []
        return keys

    fy_keys = rolling_keys("ocf", "capex")
    tax = ratio(at("income_tax"), at("pretax_income"))
    invested = sub(add(eq, debt), cash)
    roe_keys = rolling_keys("net_income", "equity")
    roe = [ratio(series["net_income"][k], series["equity"][k]) for k in roe_keys]
    sbc_keys = rolling_keys("sbc", "ocf", "capex")
    sbc = [ratio(series["sbc"][k], fcf_series[k]) for k in sbc_keys]
    div = at("dividends_paid")
    div = abs(div) if div is not None else None
    interest = at("interest_expense")
    ds = series.get("diluted_shares", {})
    dkeys = sorted(ds)
    burn = (
        -(fcf if fcf is not None else ocf)
        if (fcf if fcf is not None else ocf) is not None
        else None
    )
    ocfs = series.get("ocf", {})
    rpo = series.get("rpo", {})
    rk = sorted(rpo)
    result = dict(
        available=end is not None,
        fy_end=end,
        revenue=rev,
        ebit=oi,
        ebitda=ebitda,
        net_income=ni,
        ocf=ocf,
        capex=capex,
        fcf=fcf,
        fcf_avg3=sum(fcf_series[k] for k in fy_keys) / 3 if len(fy_keys) == 3 else None,
        cash=cash,
        debt=debt,
        debt_basis=debt_basis,
        net_debt=nd,
        equity=eq,
        shares=shares,
        mcap=mcap,
        ev=ev,
        ocf_years=len(ocfs),
        ocf_all_positive_10y=len(ocfs) >= 10 and streak(ocfs) >= 10,
        ocf_positive_years=sum(v > 0 for v in ocfs.values()),
        roe3=sum(roe) / 3 if len(roe) == 3 and None not in roe else None,
        sbc_to_fcf_3y=sbc if len(sbc) == 3 and None not in sbc else None,
        dilution_cagr=(
            growth(ds, 5)
            if len(ds) >= 6
            else growth(ds, len(ds) - 1) if len(ds) >= 4 else None
        ),
        current_ratio=ratio(at("current_assets"), at("current_liabilities")),
        nd_ebitda=ratio(nd, ebitda),
        ev_ebitda=ratio(ev, ebitda),
        ev_ebit=ratio(ev, oi),
        pe=ratio(mcap, ni),
        ebit_ev=ratio(oi, ev),
        fcf_yield=ratio(fcf, mcap),
        fcf_ev=ratio(fcf, ev),
        roic=ratio(
            (
                oi * (1 - min(max(tax, 0), 0.35))
                if oi is not None and tax is not None
                else None
            ),
            invested,
        ),
        eps_cagr3=growth(series.get("eps_diluted", {}), 3),
        fcfps_cagr3=growth(fcfps, 3),
        rev_cagr3=growth(series.get("revenue", {}), 3),
        rpo_growth=(
            ratio(rpo[rk[-1]], rpo[rk[-2]]) - 1
            if len(rk) >= 2 and rpo[rk[-2]] > 0
            else None
        ),
        rnd_capex_to_rev=ratio(add(at("rnd"), capex), rev),
        rnd_to_rev=ratio(at("rnd"), rev),
        interest_expense=interest,
        de=ratio(debt, eq),
        interest_cov=ratio(oi, abs(interest)) if interest is not None else None,
        ps=ratio(mcap, rev),
        pb=ratio(mcap, eq),
        dividends_paid=div,
        div_yield=ratio(div, mcap),
        payout=ratio(div, ni),
        share_change_1y=(
            ratio(ds[dkeys[-1]], ds[dkeys[-2]]) - 1
            if len(dkeys) >= 2 and ds[dkeys[-2]] > 0
            else None
        ),
        earn_pos_streak=streak(series.get("net_income", {})),
        ocf_pos_streak=streak(ocfs),
        dividend_years=sum(
            v != 0 for k, v in sorted(series.get("dividends_paid", {}).items())[-5:]
        ),
        runway_years=ratio(cash, burn),
    )
    return result


PATTERNS = {
    "going_concern": r"substantial doubt[^.]{0,200}going concern|going concern[^.]{0,200}substantial doubt",
    "material_weakness": r"(?:identified|disclosed|have|has) (?:a |two |several )?material weakness|material weakness(?:es)? (?:was|were|has been|have been) identified|(?:internal control over financial reporting|disclosure controls and procedures) (?:was|were) not effective",
    "restatement": r"restate(?:d|ment)[^.]{0,120}(?:previously issued|prior period financial statements)",
    "covenant_breach": r"not in compliance with[^.]{0,120}covenant|event of default[^.]{0,80}(?:has|had) occurred",
    "enforcement": r"wells notice|(?:formal|ongoing) (?:sec )?investigation by the (?:sec|securities and exchange commission)|subpoena[^.]{0,80}securities and exchange commission",
}


def scan_filing(text, *, filed, as_of, source=None):
    if date.fromisoformat(filed) >= timestamp(as_of).date():
        raise ValueError("Filing must predate evaluation UTC date")
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 10_000_000:
        raise ValueError("Nonempty filing text up to 10 MB required")
    clean = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
    hits = {k: len(re.findall(pattern, clean, re.I)) for k, pattern in PATTERNS.items()}
    related = len(re.findall(r"related part", clean, re.I))
    return dict(
        status="heuristic_scan",
        filed=filed,
        as_of=as_of,
        source=source,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        chars=len(clean),
        hits=hits,
        related_party_mentions=related,
        flags=sorted(
            [k for k, v in hits.items() if v]
            + (["related_party"] if related > 25 else [])
        ),
        warning="Regex flags require contextual review; no matches does not establish absence of risk.",
    )


def _fetch(url, *, sec=False):
    ua = os.environ.get("SEC_USER_AGENT", "") if sec else "BottleneckAtlas/1.0"
    if sec and (not ua.strip() or "@" not in ua or "\n" in ua or "\r" in ua):
        raise ValueError(
            "Set SEC_USER_AGENT to operator organization and contact email"
        )
    req = urllib.request.Request(
        url, headers={"User-Agent": ua, "Accept-Encoding": "identity"}
    )
    if sec:
        time.sleep(0.11)
    with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
        raw = response.read(10_000_001)
    if len(raw) > 10_000_000:
        raise ValueError("Provider response exceeds 10 MB")
    return raw


def fetch_companyfacts(cik):
    cik = str(cik)
    if not re.fullmatch(r"[0-9]{1,10}", cik):
        raise ValueError("CIK must have 1 to 10 digits")
    url = "https://data.sec.gov/api/xbrl/companyfacts/CIK" + cik.zfill(10) + ".json"
    raw = _fetch(url, sec=True)
    return dict(
        companyfacts=json.loads(raw),
        source=url,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def fetch_filing(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.sec.gov"
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(
            r"/Archives/edgar/data/[0-9]+/[0-9]+/[A-Za-z0-9_.-]+\.(?:htm|html|txt)",
            parsed.path,
        )
    ):
        raise ValueError(
            "Only canonical HTTPS www.sec.gov EDGAR archive document URLs allowed"
        )
    raw = _fetch(url, sec=True)
    return dict(
        text=raw.decode("utf-8", "replace"),
        source=url,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def evaluate_regime(payload, *, as_of):
    cutoff = timestamp(as_of)
    unknown = dict(
        known=False,
        adverse=True,
        as_of=as_of,
        historical_vintage_verified=False,
        reason="Missing, stale or unavailable observation evidence",
        warning="Current FRED values may contain revisions; no historical vintage certification.",
    )
    try:
        retrieved = timestamp(payload["retrieved_at"])
        if retrieved > cutoff:
            return unknown
        parsed = []
        for key, age in [("real_yield", 10), ("industrial_production", 80)]:
            rows = payload[key]
            if not isinstance(rows, list):
                raise ValueError("Series must be lists")
            values = []
            prior = None
            for row in rows:
                day = date.fromisoformat(row["date"])
                value = _number(row["value"])
                if key == "industrial_production" and value <= 0:
                    return unknown
                if prior and day <= prior:
                    raise ValueError("Series dates must increase uniquely")
                prior = day
                if day > retrieved.date():
                    raise ValueError("Observation postdates retrieval")
                if day <= cutoff.date():
                    values.append((day, value))
            if not values or (cutoff.date() - values[-1][0]).days > age:
                return unknown
            parsed.append(values)
        ry, ip = parsed
        if len(ry) < 64 or len(ip) < 4 or ip[-4][1] <= 0:
            return unknown
        if any((b[0] - a[0]).days > 7 for a, b in zip(ry[-64:], ry[-63:])):
            return unknown
        if any(not 25 <= (b[0] - a[0]).days <= 35 for a, b in zip(ip[-4:], ip[-3:])):
            return unknown
        dry = ry[-1][1] - ry[-64][1]
        dip = ip[-1][1] / ip[-4][1] - 1
        return dict(
            known=True,
            adverse=dry > 0.25 and dip < 0,
            as_of=as_of,
            retrieved_at=payload["retrieved_at"],
            real_yield_change_63_observations_bp=dry * 100,
            industrial_production_change_3m=dip,
            sources=payload.get("sources", []),
            historical_vintage_verified=False,
            warning=unknown["warning"],
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return unknown


def fetch_regime():
    out = dict(sources=[])
    for field, series in [
        ("real_yield", "DFII10"),
        ("industrial_production", "INDPRO"),
    ]:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series
        raw = _fetch(url)
        rows = list(csv.reader(io.StringIO(raw.decode())))
        out[field] = [
            dict(date=d, value=float(v))
            for d, v in rows[1:]
            if v not in ("", ".", "NA")
        ]
        out["sources"].append(dict(url=url, sha256=hashlib.sha256(raw).hexdigest()))
    out["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    return out


def add_commands(commands):
    parser = commands.add_parser(
        "research-data",
        help="Generic SEC fundamentals, filing heuristics and FRED observations",
    )
    subs = parser.add_subparsers(dest="research_action", required=True)
    for action in ("fundamentals", "filing", "regime"):
        p = subs.add_parser(action)
        p.add_argument("input", nargs="?", type=Path)
        p.add_argument("--as-of", required=True)
        p.add_argument("--output", required=True, type=Path)
        if action == "fundamentals":
            p.add_argument("--cik")
            p.add_argument("--currency", choices=("USD", "CAD"), default="USD")
            p.add_argument("--price", type=float)
        elif action == "filing":
            p.add_argument("--url")
            p.add_argument("--filed", required=True)
        else:
            p.add_argument("--fetch", action="store_true")
    return parser


def execute(args):
    action = args.research_action
    network = bool(
        getattr(args, "cik", None)
        or getattr(args, "url", None)
        or getattr(args, "fetch", False)
    )
    if bool(args.input) == network:
        raise ValueError("Choose exactly one local input or fetch option")
    if args.input and args.input.stat().st_size > 10_000_000:
        raise ValueError("Input exceeds 10 MB")
    evidence = None
    if action == "fundamentals":
        evidence = fetch_companyfacts(args.cik) if network else None
        data = (
            evidence["companyfacts"] if evidence else json.loads(args.input.read_text())
        )
        result = extract_companyfacts(
            data, as_of=args.as_of, currency=args.currency, price=args.price
        )
    elif action == "filing":
        evidence = fetch_filing(args.url) if network else None
        text = evidence["text"] if evidence else args.input.read_text()
        result = scan_filing(text, filed=args.filed, as_of=args.as_of, source=args.url)
    else:
        data = fetch_regime() if network else json.loads(args.input.read_text())
        result = evaluate_regime(data, as_of=args.as_of)
        result["observations"] = data
    if evidence:
        result["retrieval"] = {
            k: v for k, v in evidence.items() if k not in ("text", "companyfacts")
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            dict(
                output=str(args.output),
                status=result.get("status"),
                known=result.get("known"),
            )
        )
    )
