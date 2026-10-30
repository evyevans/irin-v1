"""Deterministic, point-in-time research leaderboard and headline scoring."""

import math
import re
from datetime import timedelta
from urllib.parse import urlsplit
from .core import timestamp
from engine import indicators

POS = re.compile(
    r"\b(beat|beats|upgrade|upgraded|wins|awarded|contract|growth|strong|approval|approved|expansion)\b",
    re.I,
)
NEG = re.compile(
    r"\b(miss|misses|downgrade|downgraded|lawsuit|investigation|delay|delays|loss|losses|default|dilution|fraud|outage)\b",
    re.I,
)


def news_score(items, *, as_of):
    now = timestamp(as_of)
    if not isinstance(items, list):
        raise ValueError("Headlines must be a list")
    fresh = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str):
            raise ValueError("Headline title required")
        published, available = timestamp(item.get("published_at")), timestamp(
            item.get("available_at")
        )
        url = urlsplit(item.get("url", ""))
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Headline source must be HTTPS")
        if published > available:
            raise ValueError("Headline availability predates publication")
        if published <= available <= now and now - published <= timedelta(days=30):
            fresh.append(item)
    pos = sum(bool(POS.search(x["title"])) for x in fresh)
    neg = sum(bool(NEG.search(x["title"])) for x in fresh)
    return dict(
        score=round(5 + 5 * math.tanh((pos - neg) / 3), 1) if len(fresh) >= 2 else 5.0,
        count=len(fresh),
        positive=pos,
        negative=neg,
        status="scored" if len(fresh) >= 2 else "insufficient_news_neutral",
        sources=fresh,
    )


def rank(results, snapshots, *, as_of, headlines=None, previous=None, limit=10):
    headlines = headlines or {}
    previous = previous or {}
    rows = []
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Invalid leaderboard limit")
    for result in results:
        t = result["ticker"]
        snap = snapshots[t]
        checks = {str(c["id"]): c for c in result["checks"]}
        get = lambda n: checks.get(str(n), {})
        ind = indicators.compute(snap["history"])
        fund = snap["context"]["fund"]
        if (
            result["gates"]
            or not get(1).get("pass_")
            or not get("C1").get("pass_")
            or (ind.get("addv20") or 0) < 1e6
            or not ind.get("enough_history")
        ):
            continue
        valuation = get(12).get("value") or []
        veto = get(13).get("value") or {}
        quality = 0 if veto.get("rothery") else 4
        # Grade is not exposed by the public research result; retain an explicit conservative value.
        demand = (
            6 * bool(get(2).get("pass_"))
            + 4 * bool(get(3).get("pass_"))
            + 4 * bool(get(4).get("pass_"))
            + (
                6
                if (get(5).get("value") or 0) >= 2
                else 3 if (get(5).get("value") or 0) == 1 else 0
            )
        )
        profit = (
            5 * bool((fund.get("pe") or 0) > 0)
            + 5 * any(v.get("metric") == "FCF yield" and v.get("ok") for v in valuation)
            + 5
            * bool(fund.get("interest_cov") is not None and fund["interest_cov"] >= 4)
        )
        value = min(15, round(15 * sum(bool(v.get("ok")) for v in valuation) / 4, 1))
        trend = (
            8 * bool(get(6).get("pass_"))
            + 4 * bool((ind.get("ret_6m") or 0) > 0)
            + 3 * bool(ind.get("sma50") and ind.get("close") > ind["sma50"])
        )
        news = news_score(headlines.get(t, []), as_of=as_of)
        components = dict(
            demand=demand,
            balance=quality,
            profit=profit,
            value=value,
            trend=trend,
            lenses=round(10 * (get(14).get("value") or 0) / 13, 1),
            news=news["score"],
        )
        rows.append(
            dict(
                ticker=t,
                name=result["name"],
                score=round(sum(components.values()), 1),
                components=components,
                news=news,
                status=result["status"],
                failing=result["failing"],
            )
        )
    rows.sort(key=lambda x: (-x["score"], -x["components"]["demand"], x["ticker"]))
    for i, row in enumerate(rows[:limit], 1):
        old = previous.get(row["ticker"])
        row.update(rank=i, previous_rank=old, move=None if old is None else old - i)
    return dict(
        rows=rows[:limit],
        eligible_count=len(rows),
        as_of=as_of,
        method="public-adapted-v4",
        warning="Research ranking only; source metadata is operator attested, balance grade unavailable, and neutral news is not evidence. Never a trade trigger.",
    )
