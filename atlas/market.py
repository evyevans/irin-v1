"""Optional public EOD observation fetcher. Never certifies upstream independence.

These vendor interfaces are best-effort and can change or restrict access.
No credentials, dataset redistribution or live execution are provided.
"""

import copy, hashlib, json, re, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .core import normalize_history, timestamp
from .cloud import NoRedirect


def parse_yahoo(data):
    result = data["chart"]["result"][0]
    q = result["indicators"]["quote"][0]
    adjusted = result["indicators"]["adjclose"][0]["adjclose"]
    rows = []
    for i, ts in enumerate(result["timestamp"]):
        if (
            any(q[k][i] is None for k in ("open", "high", "low", "close", "volume"))
            or adjusted[i] is None
        ):
            continue
        day = (
            datetime.fromtimestamp(ts, ZoneInfo("America/New_York")).date().isoformat()
        )
        rows.append(
            dict(
                d=day,
                o=q["open"][i],
                h=q["high"][i],
                l=q["low"][i],
                c=q["close"][i],
                ac=adjusted[i],
                v=q["volume"][i],
            )
        )
    return (
        result["meta"]["currency"],
        normalize_history(rows),
        bool(result.get("events", {}).get("splits")),
    )


def parse_nasdaq(data):
    return {
        datetime.strptime(r["date"], "%m/%d/%Y")
        .date()
        .isoformat(): float(str(r["close"]).replace("$", "").replace(",", ""))
        for r in data["data"]["tradesTable"]["rows"]
    }


def compare(rows, secondary):
    common = [r for r in rows if r["d"] in secondary][-10:]

    def agrees(r):
        a, b = r["c"], secondary[r["d"]]
        return a > 0 and b > 0 and abs(a - b) / ((a + b) / 2) <= 0.005

    eligible = bool(
        len(common) == 10
        and common[-1]["d"] == rows[-1]["d"] == max(secondary)
        and agrees(common[-1])
        and sum(agrees(r) for r in common) >= 8
    )
    return dict(
        eligible=eligible,
        common_sessions=len(common),
        agree=sum(agrees(r) for r in common),
        tolerance_pct=0.5,
    )


def fetch_json(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        raw = response.read(10_000_001)
    if len(raw) > 10_000_000:
        raise ValueError("Provider response exceeds limit")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def refresh(dossier, *, session_close, next_session):
    # Caller chooses ticker and point-in-time research; no hidden universe or favorable defaults.
    if dossier.get("synthetic") is not False:
        raise ValueError("Live refresh requires an explicitly real research dossier")
    ticker = dossier["context"]["ticker"]
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", ticker):
        raise ValueError("Unsupported US symbol")
    now = datetime.now(timezone.utc)
    close = timestamp(session_close)
    if close > now:
        raise ValueError("Session has not closed")
    ybase = "https://query1.finance.yahoo.com/v8/finance/chart/" + ticker
    nbase = "https://api.nasdaq.com/api/quote/" + ticker + "/historical"
    y, yhash = fetch_json(
        ybase + "?range=2y&interval=1d&events=div%2Csplits&includeAdjustedClose=true"
    )
    n, nhash = fetch_json(
        nbase
        + "?assetclass=stocks&limit=9999&fromdate="
        + close.date().replace(year=close.year - 2).isoformat()
    )
    currency, rows, splits = parse_yahoo(y)
    secondary = parse_nasdaq(n)
    rows = [r for r in rows if r["d"] <= close.date().isoformat()]
    if currency != "USD" or not rows or rows[-1]["d"] != close.date().isoformat():
        raise ValueError("Missing requested USD session")
    check = compare(rows, secondary)
    if not check["eligible"] or splits:
        raise ValueError(
            "Price conflict, insufficient cross-check history or split that needs manual reconciliation"
        )
    out = copy.deepcopy(dossier)
    out["history"] = rows
    # Never turn search results into financial facts or certify unknown vendor upstreams.
    out["sources"] = [s for s in out["sources"] if s["role"] != "price"]
    for sid, publisher, url, digest in [
        ("yahoo", "Yahoo Finance", ybase, yhash),
        ("nasdaq", "Nasdaq", nbase, nhash),
    ]:
        out["sources"].append(
            dict(
                id="price-" + sid,
                role="price",
                publisher=publisher,
                upstream="UNVERIFIED_SHARED_US_MARKET_DATA",
                url=url,
                observed_at=close.isoformat(),
                available_at=now.isoformat(),
                label="operator_attested",
                content_sha256=digest,
                value=rows[-1]["c"] if sid == "yahoo" else secondary[rows[-1]["d"]],
            )
        )
    out["market"] = dict(
        currency="USD",
        exchange=dossier.get("market", {}).get("exchange"),
        session_close=close.isoformat(),
        next_session=next_session,
        corporate_actions_checked=True,
        upstream_independence_verified=False,
    )
    out["refresh"] = dict(
        retrieved_at=now.isoformat(),
        cross_check=check,
        warning="Both upstream IDs remain shared/unverified. A qualified analyst must establish genuine independence; do not relabel to force a pass.",
    )
    return out
