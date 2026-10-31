"""IRIN v3.0 — deterministic exit management for open paper positions (X1–X5). Stops only ever move UP (DB rule).
Input rows are daily OHLC rows (oldest first) through the latest verified session."""
import datetime as dt, math
from .indicators import compute

def manage(pos, rows, cfg, thesis_break=None, catalysts_done=False, pending_exit=None):
    """pos: dict(ticker, entry_price, stop_price, entry_date, highest_close). Returns dict(action, reason, price, new_stop, notes).
    action: 'exit_now' (fill at the given price today), 'queue_exit' (fill at next session open), 'raise_stop', 'hold'."""
    X = cfg["exits"]; ind = compute(rows); last = rows[-1]; out = dict(ticker=pos["ticker"], date=last["d"], action="hold", reason=None, price=None, new_stop=None, notes=[])
    entry = pos["entry_price"]; stop = pos["stop_price"]
    # a queued exit (X2 trend / X3 time / X5 thesis) fills at this session's open
    if pending_exit:
        out.update(action="exit_now", reason=pending_exit, price=last["o"]); return out
    # X1 / protective stop: gap below -> open; intraday touch -> stop
    if last["o"] <= stop: out.update(action="exit_now", reason="X1 stop (gap below stop)", price=last["o"]); return out
    if last["l"] <= stop: out.update(action="exit_now", reason="X1 stop", price=stop); return out
    # X5 thesis break -> next session
    if thesis_break: out.update(action="queue_exit", reason=f"X5 thesis break: {thesis_break}"); return out
    # X2 trend exits -> next session
    if ind.get("sma200") is not None and last["c"] < ind["sma200"]:
        out.update(action="queue_exit", reason="X2 close below 200-day average"); return out
    # X2 monthly: on the first session of a new month, a prior month-end close below the 10-month average exits at this open
    if len(rows) >= 2 and rows[-1]["d"][:7] != rows[-2]["d"][:7] and rows[-2]["d"] >= pos["entry_date"] \
       and ind.get("sma10m") is not None and ind.get("last_month_end_close") is not None and ind["last_month_end_close"] < ind["sma10m"]:
        out.update(action="exit_now", reason="X2 month-end close below 10-month average", price=last["o"]); return out
    # X3 time stop
    held = (dt.date.fromisoformat(last["d"]) - dt.date.fromisoformat(pos["entry_date"])).days
    gain = last["c"] / entry - 1
    if held >= X["X3"]["months"] * 30.4 and gain < X["X3"]["min_gain"] and not catalysts_done:
        out.update(action="queue_exit", reason="X3 time stop (6 months without +10% and no catalyst)"); return out
    # X4 stop raises (never lower)
    hi = max(pos.get("highest_close") or entry, last["c"]); new = stop
    if gain >= X["X4"]["breakeven_at"]: new = max(new, entry)
    if hi / entry - 1 >= X["X4"]["trail_at"] and ind.get("atr20"): new = max(new, hi - X["X4"]["trail_atr_mult"] * ind["atr20"])
    if new > stop + 1e-9: out.update(action="raise_stop", new_stop=math.ceil(new * 1e4 - 1e-6) / 1e4,   # rounded up: never below breakeven
                    reason="X4 breakeven" if new == entry else "X4 trailing stop")
    out["highest_close"] = hi
    return out
