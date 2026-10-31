"""IRIN v3.0 — deterministic technical indicators on daily rows (oldest first). Missing history -> None (the rule then FAILS)."""
def _closes(rows, key="c"): return [r[key] for r in rows]
def sma(vals, n):
    return None if len(vals) < n else sum(vals[-n:]) / n
def atr(rows, n=20):
    if len(rows) < n + 1: return None
    trs = [max(r["h"] - r["l"], abs(r["h"] - p["c"]), abs(r["l"] - p["c"])) for p, r in zip(rows[-n - 1:-1], rows[-n:])]
    return sum(trs) / n
def month_end_closes(rows):
    """last close of each calendar month (the current month only if the last row is its final trading day is unknown -> excluded)."""
    out = {}
    for r in rows: out[r["d"][:7]] = r
    keys = sorted(out)
    return [out[k] for k in keys[:-1]]   # completed months only

def compute(rows):
    """returns every input the v3.0 rules need; None where history is too short (fail closed)."""
    n = len(rows); c = _closes(rows)
    if n == 0: return dict(n=0)
    last = rows[-1]
    prior20 = c[-21:-1] if n >= 21 else None
    vol20 = sum(r["v"] for r in rows[-21:-1]) / 20 if n >= 21 else None
    me = month_end_closes(rows)
    out = dict(
        n=n, date=last["d"], close=last["c"], open=last["o"], high=last["h"], low=last["l"], volume=last["v"],
        sma50=sma(c, 50), sma200=sma(c, 200),
        ret_12m=(last["ac"] / rows[-253]["ac"] - 1) if n >= 253 else None,          # total return, 252 sessions, dividend-adjusted
        high20_prior=max(prior20) if prior20 else None,                                # highest CLOSE of the prior 20 sessions
        vol20_avg=vol20,
        high60=max(r["h"] for r in rows[-60:]) if n >= 60 else None,
        atr20=atr(rows, 20),
        addv20=(sum(r["c"] * r["v"] for r in rows[-20:]) / 20) if n >= 20 else None,   # average daily dollar volume
        sma10m=(sum(r["c"] for r in me[-10:]) / 10) if len(me) >= 10 else None,
        last_month_end_close=me[-1]["c"] if me else None, last_month_end=me[-1]["d"] if me else None,
        xcheck_last=last.get("xok"), xcheck_pct_252=(100 * sum(1 for r in rows[-252:] if r.get("xok")) / min(n, 252)),
    )
    # v3.2 Rothery sanity inputs: 260-session volatility (annualised stdev of daily total returns) and 6-month return
    if n >= 261:
        rr = [rows[i]["ac"] / rows[i - 1]["ac"] - 1 for i in range(n - 260, n)]; mu = sum(rr) / len(rr)
        out["vol260"] = (sum((x - mu) ** 2 for x in rr) / (len(rr) - 1)) ** 0.5 * (252 ** 0.5)
    else: out["vol260"] = None
    out["ret_6m"] = (last["ac"] / rows[-127]["ac"] - 1) if n >= 127 else None
    out["enough_history"] = n >= 253
    return out

def returns(rows, n=252):
    c = [r["ac"] for r in rows[-(n + 1):]]
    return {rows[-len(c) + i + 1]["d"]: c[i + 1] / c[i] - 1 for i in range(len(c) - 1)}

def correlation(a, b):
    ks = sorted(set(a) & set(b))
    if len(ks) < 60: return None
    x = [a[k] for k in ks]; y = [b[k] for k in ks]; mx = sum(x) / len(x); my = sum(y) / len(y)
    sx = sum((v - mx) ** 2 for v in x) ** 0.5; sy = sum((v - my) ** 2 for v in y) ** 0.5
    return None if not sx or not sy else sum((p - mx) * (q - my) for p, q in zip(x, y)) / (sx * sy)
