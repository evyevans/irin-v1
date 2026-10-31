"""IRIN v3.0 — A+ setup engine. Pure, deterministic functions: same inputs -> same grade. PAPER SIMULATION ONLY.
Retains the project-authored A+ heuristics (see docs/LIMITATIONS.md) with the existing 12-lens committee: the 7 score lenses
(Buffett, Klarman, Graham, Greenblatt, Fisher, Lynch, Munger), 3 sizing lenses (Marks, Dalio, Bogle), 2 timing lenses
(Tudor Jones, Soros) and the 3 vetoes (Graham, Munger, Tudor Jones). Where the spec and an existing constitutional / DB rule
differ, the STRICTER rule wins (see CONFLICTS). Missing data for a check -> the check FAILS ("insufficient evidence").
v3.2: a 13th lens, a Rothery-inspired heuristic (see docs/LIMITATIONS.md): hard balance-sheet veto + score + sanity check + size tilt; the lens
threshold becomes 9 of 13. Under-US$10 names face check C4 (Rothery small-stock rules, stricter) and junior dilution / runway vetoes.
Every lens also reports a strength (0-1) and a plain reason (lens_detail) used for the client "who would look at it" line."""
import json, math, os, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config", "rules.json")
def load_config(path=CFG_PATH):
    with open(path, "rb") as handle: raw = handle.read()
    c = json.loads(raw); c["_sha256"] = hashlib.sha256(raw).hexdigest(); return c

# spec vs existing rule: (topic, spec, existing, resolution) — the stricter rule wins
CONFLICTS = [
 ("Risk per trade", "S1 1% of equity", "DB tier A (score >= 85) 1.0%, tier B 0.5%", "min(spec, DB tier): names scoring below 85 risk 0.5%"),
 ("Position cost cap", "S2 cost <= 20% of equity", "DB starter cap 5% (freq_max_initial_weight_pct), single name 10% (max_total_weight_pct)", "initial cost <= 5% of equity; any add keeps the name <= 10%"),
 ("Theme concentration", "S3 <= 40% per theme layer", "DB subsector <= 25% (max_subsector_weight_pct)", "both apply: layer <= 40% and subsector <= 25%"),
 ("Liquidity", "S4 average daily dollar volume >= US$1m (0.5% risk if < US$2m)", "DB median 20-day ADV >= C$1m and order <= 5% of ADV", "both apply; US$1m (~C$1.42m) is the binding floor"),
 ("Cash floor", "S5 >= 20% cash with >= 4 positions; 40% if drawdown > 15%", "DB min cash 10%", "max of the applicable floors"),
 ("Drawdown 10%", "S6 risk 0.75%", "DB: tier B entries blocked, size x0.5 at >= 10%", "DB rule (stricter): only tier A names, half size, risk <= 0.75%"),
 ("Drawdown 15%", "S6 risk 0.5%, only A+ uncorrelated adds", "DB: all entries blocked at >= 15%", "DB rule (stricter): no entries"),
 ("Drawdown 20%", "S6 50-100% cash, pause entries for the rest of the month", "DB breaker ladder 10/15/20 on peak equity", "spec on a weekly high-water mark AND DB peak rule; pause to month end"),
 ("Max positions", "7 positions, invested <= 80%", "DB max_open_positions 20", "7 positions, <= 80% invested"),
 ("Frequency", "not specified", "DB: 1 new trade per 7 days, 2 per calendar month, 3 per 28 days", "DB limits kept"),
 ("Initial stop", "X1 stop = max(entry x 0.80, entry - 2.5 x ATR20)", "DB: stops may only be tightened", "X1 at entry; later changes only raise the stop"),
 ("Reward:risk", "Tudor Jones >= 3:1 with a +30% target", "DB reward_risk recorded per dossier", ">= 3:1 required, so the X1 stop must sit within 10% of entry"),
 ("Entry timing", "A+ E1 and (E2 or E3)", "v2.7 timing gate 'no entry rule adopted' (Tudor Jones 'wait')", "A+ timing replaces the missing rule; Tudor Jones supports only when E1 and E2/E3 pass"),
 ("Fill", "not specified", "session gate: an end-of-day signal fills no earlier than the next session", "signal day T -> re-checked and filled at the next session's verified close"),
 ("Tradable focus", "utilities, grid OEMs, miners, DC REITs", "DB v2.1 focus: 'context_only' names cannot trade; infra needs grade-A relevance", "both apply; context-only names stay research-only"),
 ("Juniors / FX", "not specified", "juniors <= 2% each / 10% total; 25 bp simulated FX friction on non-U.S. listings", "kept"),
 ("Research score", "not specified", "DB: a trade needs a research score >= 70 (ck_score_gate)", "kept as A+ check C2; 60-69 counts as marginal for the watchlist"),
 ("Focus gate timing", "not specified", "DB checks the grade-A relevance / developer credibility gate only at trade open", "v3.0.1: evaluated before the trade as check C3 (same condition, no loosening)"),
 ("Bottleneck evidence", "two independent dated sources", "Phase 1: only verified facts support a decision", "v3.0.1: only Verified-fact, A/B-grade, independent sources dated within 24 months count, by distinct publisher in the primary layer"),
 ("Single-name size", "S2 cost <= 20% of equity", "Rothery: single stock <= 15%; DB 10% total / 5% initial", "v3.2: 15% replaces 20% in the engine; the DB 10% / 5% caps stay binding"),
 ("Theme concentration (v3.2)", "S3 <= 40% per theme layer", "Rothery: sub-theme <= 25%; DB subsector <= 25%", "v3.2: layer <= 25% (stricter) and subsector <= 25%"),
 ("Number of positions", "7 positions", "Rothery prefers 10-20 holdings", "7 kept (smaller account; the stricter/smaller cap wins)"),
 ("Liquidity (Rothery)", "S4 ADDV >= US$1m", "Rothery ADV >= US$500k (US$750k under US$10)", "ours (US$1m) is stricter and stays"),
 ("Under US$10", "not specified", "juniors <= 2% each / 10% total", "v3.2 check C4: D/E <= 0.5, current ratio >= 2.5, interest cover >= 4, 3 positive years of earnings and cash flow, spread <= 1.5% verified, no pure explorers or story stocks; cost <= min(5% of equity, US$300, junior 2%)"),
 ("Lens count", "8 of 12 lenses positive", "Rothery added as the 13th lens", "v3.2: 9 of 13"),
 ("Unmapped segments", "valuation rules for 4 segments", "contractors, cooling/power-conversion OEMs, refiners, semis not covered", "contractors and thermal/power OEMs use grid-equipment thresholds; refiners use miner thresholds; semis/cloud have no rule -> valuation check fails"),
]

def segment(row):
    sub = (row.get("subsector") or "").lower(); layer = row.get("layer"); fs = row.get("focus_segment"); bm = (row.get("business_model") or "").lower()
    if "reit" in sub: return "dc_reit"
    if "regulated utility" in sub or "t&d utility" in sub or "water infrastructure" in sub: return "utility_regulated"
    if "power generation & nuclear" in sub or "natural gas" in sub or "onsite power" in sub: return "ipp"
    if layer == "A" or fs in ("critical_mineral_producer", "gold_pm", "royalty_streaming"):
        return "miner_developer" if fs == "developer_financed_permitted" else "miner_producer"
    if layer == "B" or fs == "refiner_processor": return "miner_producer"
    if layer in ("C", "D", "E", "F") and sub not in ("data-centre operator",): return "grid_equipment"
    return "unmapped"
def moat(row):
    s = (row.get("subsector") or "").lower() + " " + (row.get("business_model") or "").lower()
    return "regulated" in s or "nuclear" in s or "t&d" in s

def intrinsic(fund, cfg):
    """conservative owner-earnings value (inference): 3-year average FCF grown at min(3y revenue CAGR, cap) and capitalised at 10%."""
    v = cfg["valuation"]["all"]; f3, mcap = fund.get("fcf_avg3"), fund.get("mcap")
    if not f3 or f3 <= 0 or not mcap: return None
    g = max(0.0, min(fund.get("rev_cagr3") if fund.get("rev_cagr3") is not None else 0.0, v["growth_cap"]))
    iv = f3 * (1 + g) / (v["discount_rate"] - g)
    irr = f3 / mcap + max(0.0, min(fund.get("rev_cagr3") or 0.0, 0.08))   # base case: FCF yield + growth at a constant multiple
    return dict(iv=iv, mos=1 - mcap / iv, upside=iv / mcap - 1, irr=irr, g=g, method="3y avg FCF x (1+g)/(r-g), r=10%, g<=4%; IRR = FCF yield + growth (<=8%)")

PLAIN_METRIC = {"EV/EBITDA": "price versus yearly operating cash earnings", "FCF yield": "free cash flow for the price paid",
                "FCF/EV": "free cash flow for the whole company's value", "net debt/EBITDA": "debt load", "margin of safety": "a 25% cushion below a cautious value estimate",
                "segment median": "comparison with similar utilities", "forward P/FFO": "REIT cash earnings (no data)",
                "segment rule": "a valuation rule for this kind of business", "net cash or committed financing": "cash or committed financing"}
VETO_PLAIN = {"graham": "balance-sheet safety (Graham)", "munger": "accounting quality (Munger)", "tudor_jones": "price trend and payoff (Tudor Jones)",
              "rothery": "debt, liquidity and real profits (Rothery)"}

def pct(x): return f"{100 * x:.0f}%"
def rothery(f, ind, seg, flags, scanned, cfg, vol_med):
    """Norm Rothery lens (v3.2). Returns dict(veto, grade A/B/C/None, positive, fails, tilt, size_bucket, half_size, detail)."""
    R = cfg["lenses"]["rothery"]; V, S, Q, Z = R["veto"], R["score"], R["sanity"], R["size"]
    de, cr, cov, ni, ocf, mcap = f.get("de"), f.get("current_ratio"), f.get("interest_cov"), f.get("net_income"), f.get("ocf"), f.get("mcap")
    util = seg == "utility_regulated"; fails = []
    if de is None or de > V["de_max"]: fails.append("debt above 0.75 times equity" if de is not None else "debt not reported in a form we can check")
    if cr is None or cr < (V["current_ratio_min_utility"] if util else V["current_ratio_min"]): fails.append("current assets below twice its short-term bills" if cr is not None else "current ratio unknown")
    if cov is None or cov < V["interest_cov_min"]: fails.append("operating profit below three times its interest bill" if cov is not None else "interest cover unknown")
    if not (ni is not None and ni > 0 and ocf is not None and ocf > 0): fails.append("no positive earnings and operating cash flow in the latest year")
    if not scanned or set(V["red_flags"]) & set(flags): fails.append("annual-report red flag (or report not scanned)")
    if mcap is None or mcap < V["mcap_min_usd"]: fails.append("market value under US$300 million")
    veto = bool(fails)
    ps, pe, dy, po, shc = f.get("ps"), f.get("pe"), f.get("div_yield") or 0.0, f.get("payout"), f.get("share_change_1y")
    pe_cap = S["pe_max_utility"] if seg in ("utility_regulated", "ipp") else S["pe_max_cyclical"]
    mature = (f.get("dividends_paid") or 0) > 0
    if mature: style_ok = (dy >= S["mature_div_yield_min"] and po is not None and po <= S["mature_payout_max"]) or (shc is not None and shc < 0)
    else: style_ok = de is not None and de <= S["growth_de_max"] and ps is not None and ps <= S["growth_ps_max"] and pe is not None and pe <= S["growth_pe_max"]
    score_ok = ps is not None and ps <= S["ps_pass"] and pe is not None and pe <= pe_cap and style_ok
    v260, r12, r6 = ind.get("vol260"), ind.get("ret_12m"), ind.get("ret_6m")
    sane = None not in (v260, r12, r6) and vol_med is not None and v260 <= Q["vol260_vs_median_max"] * vol_med and r12 >= Q["ret_12m_min"] and r6 >= Q["ret_6m_min"]
    grade = None if veto else ("A" if score_ok and sane and ps <= S["ps_a"] else "B" if score_ok and sane else "C")
    bucket = "core" if mcap and mcap >= Z["mcap_core_usd"] else "experimental" if mcap and mcap >= Z["mcap_experimental_usd"] else "none"
    tilt = {"A": Z["tilt_a"], "B": Z["tilt_b"], "C": Z["tilt_c"]}.get(grade, 0.0)
    return dict(veto=veto, grade=grade, positive=grade in ("A", "B"), fails=fails, score_ok=bool(score_ok), sane=bool(sane), mature=mature, tilt=tilt,
                size_bucket=bucket, half_size=de is not None and de > R["half_size_if_de_above"],
                values=dict(de=de, current_ratio=cr, interest_cov=cov, ps=ps, pe=pe, div_yield=dy, payout=po, share_change_1y=shc, vol260=v260, vol260_median=vol_med, ret_12m=r12, ret_6m=r6, mcap=mcap))

def fisher_why(ratio, rnd_to_rev=None, segment=None):
    """v3.3.4: plain Fisher reason from the data. Research when R&D is most of the reinvestment; new mines and plants for
    miners/producers (or new plants and capacity otherwise) when it is mostly capital spending; both when mixed or unknown."""
    share = (rnd_to_rev / ratio) if rnd_to_rev is not None and ratio else None
    if share is not None and share >= 0.6: what = "research"
    elif share is not None and share <= 0.25: what = "new mines and plants" if segment == "miner_producer" else "new plants and capacity"
    else: what = "research and new capacity"
    return f"about {pct(ratio)} of sales goes back into {what}" if ratio <= 1 else f"it spends more than its sales on {what} while it builds"

def lens_detail(lens, f, ind, iv, rr, roth, L, seg=None):
    """strength 0-1 (how far past its own threshold the company is) + a plain reason with real numbers, for every POSITIVE lens.
    Lenses that only confirm the absence of a problem (Dalio, Soros, Bogle, Marks) get a low fixed strength so they rarely lead."""
    c = lambda x: max(0.0, min(1.0, x)); out = {}
    if lens.get("buffett") and f.get("roe3") is not None:
        out["buffett"] = (c(0.5 + (f["roe3"] - L["buffett"]["roe_min"]) / 0.3), f"cash from operations every year for ten years, and about {pct(f['roe3'])} a year earned on shareholders' money")
    if lens.get("graham"):
        m = min(x for x in (f.get("ev_ebit"), f.get("pe")) if x is not None) if any(x is not None for x in (f.get("ev_ebit"), f.get("pe"))) else None
        if m is not None and m <= L["graham"]["ev_ebit_or_pe_max"]:
            out["graham"] = (c(0.5 + (L["graham"]["ev_ebit_or_pe_max"] - m) / 15), f"about {m:.0f} times its yearly profits, with a sound balance sheet")
        else:
            out["graham"] = (0.5, f"little debt, and current assets about {f.get('current_ratio') or 0:.1f} times its short-term bills")
    if lens.get("lynch"):
        gr = max([x for x in (f.get("eps_cagr3"), f.get("fcfps_cagr3")) if x is not None] or [None]) if any(x is not None for x in (f.get("eps_cagr3"), f.get("fcfps_cagr3"))) else None
        if gr is not None and gr >= L["lynch"]["growth_min"]:
            out["lynch"] = (c(0.5 + (gr - L["lynch"]["growth_min"]) / 0.4), f"profit per share up about {pct(gr)} a year for three years, tied to data-centre demand in its filings")
        else:
            out["lynch"] = (c(0.5 + ((f.get("rpo_growth") or 0) - L["lynch"]["backlog_growth_min"]) / 0.4), f"order book up about {pct(f.get('rpo_growth') or 0)} last year, tied to data-centre demand in its filings")
    if lens.get("fisher") and f.get("rnd_capex_to_rev") is not None:
        out["fisher"] = (c(0.4 + (f["rnd_capex_to_rev"] - L["fisher"]["rnd_capex_to_revenue_min"]) / 0.2), fisher_why(f["rnd_capex_to_rev"], f.get("rnd_to_rev"), seg))
    if lens.get("greenblatt") and f.get("roic") is not None and f.get("ebit_ev") is not None:
        out["greenblatt"] = (c(0.5 + (f["roic"] - L["greenblatt"]["roic_min"]) / 0.4 + (f["ebit_ev"] - L["greenblatt"]["ebit_ev_min"]) / 0.2),
                             f"about {pct(f['roic'])} return on capital and an operating-profit yield of about {pct(f['ebit_ev'])}")
    if lens.get("klarman") and iv:
        out["klarman"] = (c(0.5 + (iv["upside"] - L["klarman"]["upside_min"]) / 1.0), f"our cautious value estimate is about {pct(iv['upside'])} above the price")
    if lens.get("munger") and f.get("sbc_to_fcf_3y"):
        out["munger"] = (c(0.35 + (L["munger"]["sbc_fcf_max"] - max(f["sbc_to_fcf_3y"])) / 0.6), "no red flags in its annual report, and modest stock pay")
    if lens.get("tudor_jones") and rr:
        out["tudor_jones"] = (c(0.55 + (rr - L["tudor_jones"]["min_reward_risk"]) / 6), f"a rising price trend, with a payoff about {rr:.1f} times the risk")
    if lens.get("rothery") and roth:
        v = roth["values"]
        out["rothery"] = (0.85 if roth["grade"] == "A" else 0.65,
                          f"a big, steady company with modest debt and real profits, priced at about {v['ps']:.1f} times sales and {v['pe']:.0f} times earnings"
                          + (f", paying a {pct(v['div_yield'])} dividend" if roth["mature"] and v["div_yield"] >= 0.01 else ""))
    if lens.get("marks"): out["marks"] = (0.2, "the price has not run far ahead of its value")
    if lens.get("bogle"): out["bogle"] = (0.15, "its filings show a sourced link from data-centre demand to its cash")
    if lens.get("dalio"): out["dalio"] = (0.1, "interest rates and the dollar are not working against it")
    if lens.get("soros"): out["soros"] = (0.1, "the market has not bid it to extremes")
    return {k: dict(strength=round(v[0], 3), why=v[1]) for k, v in out.items()}

def chk(cid, name, ok, plain, value=None, need=None, cat="", marginal=False):
    return dict(id=cid, name=name, pass_=bool(ok), plain=plain, value=value, need=need, category=cat, marginal=bool(marginal and not ok))

def evaluate(ctx, cfg):
    """ctx keys: ticker, name, row, ind, fund, flags, fe_counts, chain, chain_missing, direct_material, score, price_status, portfolio,
    regime, val_stats, bottleneck_sources, db (limits/policy), score_tier_a"""
    E, Sz, L = cfg["entry"], cfg["sizing"], cfg["lenses"]
    t = ctx["ticker"]; row = ctx["row"]; ind = ctx.get("ind") or {}; f = ctx.get("fund") or {}; fl = ctx.get("flags") or {}
    seg = segment(row); pf = ctx["portfolio"]; db = ctx["db"]; checks = []
    g = lambda k: ind.get(k)
    # ---------- entry rules ----------
    close, s50, s200, r12 = g("close"), g("sma50"), g("sma200"), g("ret_12m")
    e1 = None not in (close, s50, s200, r12) and close > s200 and s50 > s200 and r12 > E["E1"]["ret_12m_min"]
    e2 = bool(e1) and None not in (g("high20_prior"), g("vol20_avg")) and close > g("high20_prior") and g("volume") >= g("vol20_avg") * E["E2"]["volume_vs_avg20_min"]
    e3 = False
    if e1 and None not in (g("high60"), g("low")):
        pb = 1 - close / g("high60"); X = E["E3"]
        e3 = (X["pullback_from_high60_min"] <= pb <= X["pullback_from_high60_max"]
              and s50 * (1 - X["low_below_sma50_max"]) <= g("low") <= s50     # touched the 50-day average, or dipped at most 2% below it
              and close >= s50)
    # ---------- stop, target, reward:risk ----------
    atr = g("atr20"); entry = close
    stop = max(entry * (1 - cfg["exits"]["X1"]["max_loss_pct"]), entry - cfg["exits"]["X1"]["atr_mult"] * atr) if entry and atr else None
    risk_frac = (entry - stop) / entry if stop else None
    rr = Sz["target_gain"] / risk_frac if risk_frac else None
    # ---------- valuation ----------
    iv = intrinsic(f, cfg) if f.get("available") else None
    vr = cfg["valuation"].get(seg); vchecks = []; marginal_ok = True
    def vb(name, val, lim, le=True):
        nonlocal marginal_ok
        if val is None: vchecks.append((name, False, "no data")); marginal_ok = False; return
        ok = val <= lim if le else val >= lim
        if not ok:
            band = cfg["B_grade"]["marginal_multiple_band"]
            near = (val <= lim * (1 + band)) if le else (val >= lim * (1 - band))
            if not near: marginal_ok = False
        vchecks.append((name, ok, round(val, 3)))
    if seg in ("utility_regulated", "ipp"):
        cap = vr["ev_ebitda_max_moat"] if moat(row) else vr["ev_ebitda_max"]
        med = (ctx.get("val_stats") or {}).get("median_ev_ebitda", {}).get("utility_ipp")
        vb("EV/EBITDA", f.get("ev_ebitda"), min(cap, med) if med else cap)
        if med is None: vchecks.append(("segment median", False, "no data")); marginal_ok = False
        vb("FCF/EV", f.get("fcf_ev"), vr["fcf_ev_min"], le=False); vb("net debt/EBITDA", f.get("nd_ebitda"), vr["nd_ebitda_max"])
    elif seg == "grid_equipment":
        growth_ok = (f.get("rev_cagr3") or 0) > vr["growth_min"] and (f.get("rpo_growth") or 0) > 0 and (ctx.get("fe_counts") or {}).get("dc_quant", 0) >= 1
        vb("EV/EBITDA", f.get("ev_ebitda"), vr["ev_ebitda_max_growth"] if growth_ok else vr["ev_ebitda_max"])
        vb("FCF yield", f.get("fcf_yield"), vr["fcf_yield_min"], le=False); vb("net debt/EBITDA", f.get("nd_ebitda"), vr["nd_ebitda_max"])
    elif seg == "miner_producer":
        vb("EV/EBITDA", f.get("ev_ebitda"), vr["ev_ebitda_max"]); vb("FCF yield", f.get("fcf_yield"), vr["fcf_yield_min"], le=False); vb("net debt/EBITDA", f.get("nd_ebitda"), vr["nd_ebitda_max"])
    elif seg == "miner_developer":
        ok = (f.get("net_debt") is not None and f["net_debt"] < 0) or bool(row.get("financing_credible"))
        vchecks.append(("net cash or committed financing", ok, f.get("net_debt"))); marginal_ok = marginal_ok and ok
    elif seg == "dc_reit":
        vchecks.append(("forward P/FFO", False, "no FFO data")); marginal_ok = False
    else:
        vchecks.append(("segment rule", False, "no valuation rule for this segment")); marginal_ok = False
    mos = iv["mos"] if iv else None
    if mos is None: vchecks.append(("margin of safety", False, "no data")); marginal_ok = False
    else:
        vchecks.append(("margin of safety", mos >= cfg["valuation"]["all"]["mos_min"], round(mos, 3)))
        if mos < cfg["valuation"]["all"]["mos_b_floor"]: marginal_ok = False
    val_ok = all(v[1] for v in vchecks)
    # ---------- lenses ----------
    commodity = seg in ("miner_producer", "miner_developer")
    sbc = f.get("sbc_to_fcf_3y")
    lens = {}; veto = {}; yellow = []
    flags = set(fl.get("flags") or []); scanned = fl.get("status") == "scanned"
    lens["buffett"] = (seg != "unmapped" and bool(f.get("ocf_all_positive_10y")) and f.get("dilution_cagr") is not None and f["dilution_cagr"] <= L["buffett"]["max_dilution_cagr"]
                       and (commodity or (f.get("roe3") is not None and f["roe3"] >= L["buffett"]["roe_min"])))
    sbc_bad_all = sbc is not None and all(x > L["munger"]["sbc_fcf_max"] for x in sbc)
    sbc_bad_any = sbc is not None and any(x > L["munger"]["sbc_fcf_max"] for x in sbc)
    lens["munger"] = scanned and sbc is not None and not sbc_bad_any and not ({"material_weakness", "restatement", "related_party"} & flags)
    veto["munger"] = (not scanned) or sbc_bad_all or bool({"material_weakness", "restatement"} & flags)
    if sbc_bad_any and not sbc_bad_all: yellow.append("munger: one or two of the last 3 years had stock pay above 30% of free cash flow")
    cheap = (f.get("ev_ebit") is not None and f["ev_ebit"] <= L["graham"]["ev_ebit_or_pe_max"]) or (f.get("pe") is not None and f["pe"] <= L["graham"]["ev_ebit_or_pe_max"])
    fortress = (f.get("rev_cagr3") or 0) > L["graham"]["growth_exception"] and f.get("nd_ebitda") is not None and f["nd_ebitda"] <= L["graham"]["fortress_nd_ebitda_max"] \
               and (f.get("current_ratio") or 0) >= L["graham"]["fortress_current_ratio_min"]
    cr_ok = seg in ("utility_regulated", "ipp") or (f.get("current_ratio") is not None and f["current_ratio"] >= L["graham"]["current_ratio_min"])
    lens["graham"] = (cheap or fortress) and cr_ok
    veto["graham"] = (not scanned) or bool({"going_concern", "covenant_breach"} & flags) or \
                     (seg == "grid_equipment" and f.get("nd_ebitda") is not None and f["nd_ebitda"] > cfg["valuation"]["grid_equipment"]["nd_ebitda_graham_veto"])
    if seg == "grid_equipment" and f.get("nd_ebitda") is not None and 2.5 < f["nd_ebitda"] <= 3.0: yellow.append("graham: debt between 2.5x and 3x yearly cash earnings")
    driver = (ctx.get("fe_counts") or {}).get("dc_quant", 0) >= 1
    gr = [x for x in (f.get("eps_cagr3"), f.get("fcfps_cagr3")) if x is not None]
    lens["lynch"] = driver and (any(x >= L["lynch"]["growth_min"] for x in gr) or (f.get("rpo_growth") is not None and f["rpo_growth"] > L["lynch"]["backlog_growth_min"]))
    lens["fisher"] = scanned and f.get("rnd_capex_to_rev") is not None and f["rnd_capex_to_rev"] >= L["fisher"]["rnd_capex_to_revenue_min"] and not ({"enforcement", "material_weakness", "restatement"} & flags)
    lens["greenblatt"] = f.get("ebit_ev") is not None and f["ebit_ev"] >= L["greenblatt"]["ebit_ev_min"] and f.get("roic") is not None and f["roic"] >= L["greenblatt"]["roic_min"]
    lens["klarman"] = iv is not None and iv["irr"] >= L["klarman"]["irr_min"] and iv["upside"] >= L["klarman"]["upside_min"]
    theme_ok = pf.get("layer_weight_pct", {}).get(row.get("layer"), 0) + 0 <= Sz["S3_max_theme_layer_pct"]
    lens["marks"] = r12 is not None and mos is not None and not (r12 > L["marks"]["hot_ret_12m"] and mos < cfg["valuation"]["all"]["mos_min"]) and theme_ok
    dalio_applies = commodity or (seg in ("utility_regulated", "ipp") and (f.get("nd_ebitda") or 0) > 3)
    regime = ctx.get("regime") or {}
    adverse = regime.get("adverse") if regime.get("known") else True
    lens["dalio"] = not (dalio_applies and adverse)
    lens["bogle"] = driver and not ctx.get("chain_missing")
    lens["tudor_jones"] = bool(e1) and (e2 or e3) and rr is not None and rr >= L["tudor_jones"]["min_reward_risk"]
    veto["tudor_jones"] = not (bool(e1) and rr is not None and rr >= L["tudor_jones"]["min_reward_risk"])
    top_dec = (ctx.get("val_stats") or {}).get("ev_ebitda_p90")
    lens["soros"] = r12 is not None and not (r12 > L["soros"]["ret_12m_max"] and f.get("ev_ebitda") is not None and top_dec is not None and f["ev_ebitda"] >= top_dec)
    # v3.2: Rothery (13th lens; hard balance-sheet veto)
    roth = rothery(f, ind, seg, flags, scanned, cfg, (ctx.get("val_stats") or {}).get("vol260_median"))
    lens["rothery"] = roth["positive"]; veto["rothery"] = roth["veto"]
    # v3.2: under-US$10 / junior dilution and cash-runway vetoes (Graham / Munger; stricter only)
    U10 = cfg.get("under10") or {}
    small = (close is not None and close < U10.get("price_max_usd", 10)) or bool(row.get("is_speculative_junior")) or (row.get("stage") or "").split("/")[0] in ("explorer", "developer", "speculative")
    if small:
        if f.get("dilution_cagr") is not None and f["dilution_cagr"] > U10.get("dilution_cagr_max", 0.10): veto["munger"] = True; yellow.append("munger: share count growing more than 10% a year")
        if f.get("runway_years") is not None and f["runway_years"] < U10.get("runway_years_min", 1.5): veto["graham"] = True; yellow.append("graham: cash covers less than 18 months of cash burn")
    npos = sum(1 for v in lens.values() if v)
    # ---------- sizing ----------
    eq = pf["equity_usd"]; dd = pf.get("drawdown_pct", 0.0); addv = g("addv20")
    risk = Sz["S1_risk_pct"]
    if not ctx.get("score_tier_a"): risk = min(risk, db.get("max_risk_pct_tier_b", 0.5))
    if addv is not None and addv < Sz["S4_borderline_addv_usd"]: risk = min(risk, Sz["S4_borderline_risk_pct"])
    if dd >= 10: risk = min(risk, Sz["S6"]["dd10_risk_pct"])
    if dd >= 15: risk = min(risk, Sz["S6"]["dd15_risk_pct"])
    mult = db.get("ramp_factor", 0.5) if pf.get("trades_created", 0) < db.get("ramp_first_n_trades", 4) else 1.0
    if dalio_applies and adverse: mult *= 0.5
    if dd >= 10: mult = min(mult, 0.5)
    # v3.2 Rothery tilt: C 0.75x applies; the A 1.25x tilt is recorded but clamped to 1.0x, because the per-trade risk cap (S1, tier-B
    # and borderline limits), the ramp and drawdown cuts are existing caps that a tilt may not exceed ("inside existing caps").
    tilt_applied = min(roth["tilt"], 1.0) if roth["grade"] else 1.0
    mult *= tilt_applied
    if roth["half_size"]: mult *= 0.5                       # full size needs D/E <= 0.5
    shares = math.floor(eq * risk / 100 / (entry - stop) * mult) if stop and entry and entry > stop else 0
    cost_cap_pct = min(Sz["S2_max_cost_pct"], db.get("freq_max_initial_weight_pct", 5), db.get("max_total_weight_pct", 10))
    if roth["size_bucket"] == "experimental": cost_cap_pct = min(cost_cap_pct, cfg["lenses"]["rothery"]["size"]["experimental_max_weight_pct"])
    cost_cap_usd = None
    if small:
        cost_cap_pct = min(cost_cap_pct, U10.get("max_weight_pct", 5), U10.get("junior_single_pct", 2), db.get("max_junior_single_pct", 2))
        cost_cap_usd = U10.get("max_position_usd", 300)
    if entry: shares = min(shares, math.floor(eq * cost_cap_pct / 100 / entry))
    if entry and cost_cap_usd: shares = min(shares, math.floor(cost_cap_usd / entry))
    cost = shares * entry if entry else 0; weight = 100 * cost / eq if eq else 0
    entries_allowed = dd < 15 and not pf.get("paused_until_month_end") and (dd < 10 or ctx.get("score_tier_a"))
    invested_after = pf.get("invested_pct", 0) + weight
    npos_after = pf.get("open_positions", 0) + 1
    cash_floor = max(db.get("min_cash_pct", 10), Sz["S5_cash_min_pct_4plus"] if npos_after >= 4 else 0, Sz["S5_cash_min_pct_dd15"] if dd > 15 else 0)
    corr = ctx.get("max_corr")
    # ---------- C3: the v2.1 DB focus gate, evaluated before any trade (same condition the original private trade guard enforces at open) ----------
    fdb = ctx.get("focus_db")   # None = DB not consulted; {} = company not in the DB (open_trade would refuse it)
    seg_db = row.get("focus_segment") if fdb is None else (fdb.get("focus_segment") if fdb else None)
    snip = ctx.get("fe_snippet") or {}
    filing_a = bool(snip.get("url") and snip.get("accession") and (snip.get("label") or "Verified fact").startswith("Verified"))
    if seg_db == "power_grid_infrastructure":
        on_file = bool(fdb and fdb.get("relevance_material") and fdb.get("grade_a_relevance_source"))
        c3_ok = on_file or filing_a
        c3_plain = "no top-grade (SEC filing) source on file yet shows that data-centre demand is material to it"
        c3_obs, c3_need = dict(segment=seg_db, db_grade_a_source=on_file, sec_filing_with_accession=filing_a), "grade-A relevance source (DB) or a dated SEC filing excerpt"
    elif seg_db == "developer_financed_permitted":
        c3_ok = bool(fdb and fdb.get("financing_credible") and fdb.get("permitting_credible"))
        c3_plain = "its project financing and permits are not yet confirmed as credible"
        c3_obs, c3_need = dict(segment=seg_db, financing=(fdb or {}).get("financing_credible"), permitting=(fdb or {}).get("permitting_credible")), "financing and permitting credible (DB)"
    elif seg_db in (None, "context_only"):
        c3_ok, c3_plain, c3_obs, c3_need = True, "", dict(segment=seg_db, note="not tradable at all: covered by C1"), "n/a (C1)"
    else:
        c3_ok, c3_plain, c3_obs, c3_need = True, "", dict(segment=seg_db), "no extra focus evidence for this segment"
    # ---------- C4: under-US$10 Rothery small-stock rules (stricter than the core lens) ----------
    u10_fails = []
    if small:
        de, cr, cov = f.get("de"), f.get("current_ratio"), f.get("interest_cov")
        if de is None or de > U10["de_max"]: u10_fails.append("debt above half of equity" if de is not None else "debt not reported in a form we can check")
        if cr is None or cr < U10["current_ratio_min"]: u10_fails.append("current assets below 2.5 times short-term bills" if cr is not None else "current ratio unknown")
        if cov is None or cov < U10["interest_cov_min"]: u10_fails.append("operating profit below four times interest" if cov is not None else "no operating profit to cover interest")
        if (f.get("earn_pos_streak") or 0) < U10["positive_years_min"] or (f.get("ocf_pos_streak") or 0) < U10["positive_years_min"]: u10_fails.append("not three straight years of profits and operating cash flow")
        if addv is None or addv < U10["addv_min_usd"]: u10_fails.append("trades less than US$1 million a day")
        sp = ctx.get("spread_pct")
        if sp is None: u10_fails.append("bid-ask spread not verified from a free source (watch only)")
        elif sp > U10["spread_max_pct"]: u10_fails.append(f"bid-ask spread {sp:.1f}% above 1.5%")
        stage = (row.get("stage") or "").lower(); bmod = (row.get("business_model") or "").lower()
        if stage.startswith("explorer") or "explorer" in bmod: u10_fails.append("pure exploration company")
        if (f.get("revenue") or 0) <= 0: u10_fails.append("no revenue from producing assets yet")
        if (ctx.get("fe_counts") or {}).get("dc", 0) >= 3 and not ctx.get("direct_material"): u10_fails.append("its data-centre story is not matched by data-centre revenue in its filings")
    u10_ok = not u10_fails
    # ---------- checklist ----------
    U = lambda x: x is not None
    checks += [
     chk(1, "Permitted listing, checked price", (row.get("us_listed") or row.get("allowed_listing")) and ctx.get("price_status") == "VERIFIED_DELAYED" and ind.get("xcheck_last"),
         "its latest price is not confirmed by two free sources", ctx.get("price_status"), "VERIFIED_DELAYED", "listing"),
     chk(2, "Theme revenue", ctx.get("direct_material"), "AI/data-centre demand is not yet shown to be a direct, material part of its revenue", ctx.get("direct_material"), True, "theme"),
     chk(3, "Filings link", driver, "its filings do not put numbers on data-centre demand", (ctx.get("fe_counts") or {}).get("dc_quant"), ">= 1", "theme"),
     chk(4, "Evidence chain cited and dated", not ctx.get("chain_missing") and all(v and "Inference" not in v for k, v in (ctx.get("chain") or {}).items() if k != "bottleneck"),
         "a step from demand to cash flow is missing a dated source", ctx.get("chain_missing"), "[]", "evidence", marginal=True),
     chk(5, "Two independent bottleneck sources", (ctx.get("bottleneck_sources") or 0) >= 2,
         "the bottleneck it serves is not yet confirmed by two independent dated sources", ctx.get("bottleneck_sources"), ">= 2", "evidence", marginal=True),
     chk(6, "Trend filter (E1)", e1, "its price trend is not up (needs price above its 200-day average, 50-day above 200-day, and a positive 12-month return)",
         dict(close=close, sma50=s50 and round(s50, 2), sma200=s200 and round(s200, 2), ret_12m=r12 and round(r12, 3)), "all true", "timing", marginal=True),
     chk(7, "Entry signal (E2 breakout or E3 pullback)", e2 or e3, "no clean entry point yet (no 20-day breakout on volume and no orderly 5-15% pullback to the 50-day average)",
         dict(E2=e2, E3=e3), "either", "timing", marginal=True),
     chk(8, "Reward at least 3x risk", U(rr) and rr >= Sz["min_reward_risk"], "the safety stop would sit too far below the price for a 3-to-1 payoff",
         rr and round(rr, 2), ">= 3.0", "risk", marginal=True),
     chk(9, "Initial stop (X1)", U(stop) and stop >= entry * (1 - cfg["exits"]["X1"]["max_loss_pct"]) - 1e-9, "no safety stop could be computed (price history too short)",
         stop and round(stop, 2), "max(entry x 0.80, entry - 2.5 ATR)", "risk"),
     chk(10, "Position size (S1-S4)", shares >= 1 and U(addv) and addv >= Sz["S4_min_addv_usd"] and theme_ok,
         "a safe position size cannot be built (too little trading volume, theme limit, or less than one share)", dict(shares=shares, addv20=addv and round(addv)), ">= 1 share, ADDV >= US$1m", "risk",
         marginal=U(addv) and addv >= Sz["S4_min_addv_usd"] and theme_ok),
     chk(11, "Drawdown state allows entries (S6)", entries_allowed, "new entries are paused by the drawdown rules", round(dd, 2), "< 10% (or tier-A at 10-15%)", "risk"),
     chk(12, "Valuation for its segment", val_ok, "the price is not low enough for its type of business (fails: " + "; ".join(PLAIN_METRIC.get(n, n) for n, ok, _ in vchecks if not ok) + ")",
         [dict(metric=n, ok=ok, value=v) for n, ok, v in vchecks], "segment thresholds + margin of safety >= 25%", "valuation", marginal=marginal_ok),
     chk(13, "No Graham, Munger, Tudor Jones or Rothery veto", not any(veto.values()), "a safety veto applies: " + ", ".join(VETO_PLAIN[k] for k, v in veto.items() if v), {k: v for k, v in veto.items()}, "none", "veto"),
     chk(14, "At least 9 of 13 lenses positive", npos >= L["min_positive"], f"only {npos} of the 13 investor lenses are positive", npos, ">= 9", "lenses",
         marginal=npos >= cfg["B_grade"]["min_positive_lenses"]),
     chk(15, "Portfolio room (<= 7 positions, <= 80% invested)", npos_after <= min(Sz["max_positions"], db.get("max_open_positions", 20)) and invested_after <= Sz["max_invested_pct"]
         and 100 - invested_after >= cash_floor, "the portfolio has no room for another position", dict(positions_after=npos_after, invested_after=round(invested_after, 1)), "<= 7 and <= 80%", "portfolio"),
     chk(16, "Not too correlated with holdings", pf.get("open_positions", 0) == 0 or (U(corr) and corr <= cfg["correlation_max"]),
         "it moves too closely with something already held", corr, "<= 0.80", "portfolio", marginal=True),
     chk("C1", "Tradable under existing system focus rules", row.get("focus_segment") not in (None, "context_only") and seg_db not in (None, "context_only"),
         "the system's focus rules keep this type of company research-only", row.get("focus_segment"), "not context_only", "system"),
     chk("C3", "Focus gate evidence on file (existing DB rule, checked before trade)", c3_ok, c3_plain, c3_obs, c3_need, "system"),
     chk("C4", "Under US$10: Rothery small-stock rules (v3.2)", (not small) or u10_ok, "as a small, cheap stock it fails the extra safety rules (" + "; ".join(u10_fails) + ")",
         dict(applies=small, fails=u10_fails, spread=ctx.get("spread_pct")), "D/E <= 0.5, current ratio >= 2.5, cover >= 4, 3 positive years, ADDV >= US$1m, spread <= 1.5% verified, producing", "system",
         marginal=u10_fails == ["bid-ask spread not verified from a free source (watch only)"]),
     chk("C2", "Research score at least 70 (existing DB rule)", (ctx.get("score") or 0) >= 70,
         "its research score is below the 70 the system needs before any trade", ctx.get("score"), ">= 70", "system", marginal=(ctx.get("score") or 0) >= 60),
    ]
    fails = [c for c in checks if not c["pass_"]]
    if not fails: grade, action = "A+", "paper_trade"
    # B (watchlist): listing, theme and filings pass, no quality veto (Graham/Munger; the Tudor Jones timing veto only delays),
    # every other failure is marginal (timing, evidence, near-threshold valuation, correlation) and >= 6 lenses are positive
    elif all(c["pass_"] for c in checks if c["id"] in (1, 2, 3)) and not (veto["graham"] or veto["munger"] or veto["rothery"]) \
         and all(c["marginal"] or c["id"] in ("C1", 13) for c in fails) and npos >= cfg["B_grade"]["min_positive_lenses"]:
        grade, action = "B", "watchlist"
    else: grade, action = "Reject", "research"
    return dict(ticker=t, name=ctx.get("name"), segment=seg, grade=grade, action=action, rule_version=cfg["rule_version"], config_sha256=cfg["_sha256"],
                checks=checks, failing=[c["id"] for c in fails], plain_fail=[c["plain"] for c in fails], lenses=lens, positive_lenses=npos, vetoes=veto, yellow=yellow,
                lens_detail=lens_detail(lens, f, ind, iv, rr, roth, L, seg), rothery=roth, under10=dict(applies=small, fails=u10_fails),
                entry=dict(E1=bool(e1), E2=bool(e2), E3=bool(e3)), sizing=dict(entry=entry, stop=stop and round(stop, 4), target=entry and round(entry * (1 + Sz["target_gain"]), 4),
                risk_pct=risk, multiplier=mult, rothery_tilt=roth["tilt"], rothery_tilt_applied=tilt_applied, shares=shares, cost_usd=round(cost, 2), weight_pct=round(weight, 2), reward_risk=rr and round(rr, 2)),
                valuation=dict(checks=vchecks, intrinsic=iv), indicators={k: (round(v, 4) if isinstance(v, float) else v) for k, v in ind.items()})
