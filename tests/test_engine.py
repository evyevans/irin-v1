"""Regression tests retained from the original deterministic equity rules."""

import copy, datetime as dt, unittest
from engine import aplus, indicators, exits


def series(n=300, start=50.0, step=0.2, vol=1000000, start_date=dt.date(2025, 6, 2)):
    rows, d, p = ([], start_date, start)
    while len(rows) < n:
        if d.weekday() < 5:
            rows.append(
                dict(
                    d=d.isoformat(),
                    o=p,
                    h=p * 1.01,
                    l=p * 0.99,
                    c=p,
                    ac=p,
                    v=vol,
                    xok=True,
                )
            )
            p += step
        d += dt.timedelta(days=1)
    return rows


CFG = aplus.load_config()

FUND_OK = dict(
    available=True,
    fcf_avg3=900000000.0,
    mcap=5000000000.0,
    de=0.3,
    interest_cov=10.0,
    net_income=400000000.0,
    ocf=900000000.0,
    ps=0.9,
    dividends_paid=0.0,
    rev_cagr3=0.12,
    ocf_all_positive_10y=True,
    dilution_cagr=0.0,
    roe3=0.2,
    sbc_to_fcf_3y=[0.1, 0.1, 0.1],
    ev_ebit=10.0,
    pe=12.0,
    nd_ebitda=0.5,
    current_ratio=2.0,
    eps_cagr3=0.2,
    fcfps_cagr3=0.2,
    rpo_growth=0.2,
    rnd_capex_to_rev=0.08,
    ebit_ev=0.1,
    roic=0.2,
    ev_ebitda=9.0,
    fcf_yield=0.12,
    fcf_ev=0.1,
    net_debt=100000000.0,
)


def ctx(rows, **kw):
    c = dict(
        ticker="TST",
        name="Test Co",
        row=dict(
            layer="D",
            subsector="Grid & electrical equipment",
            focus_segment="power_grid_infrastructure",
            us_listed=True,
        ),
        ind=indicators.compute(rows),
        fund=copy.deepcopy(FUND_OK),
        flags=dict(status="scanned", flags=[]),
        fe_counts=dict(dc_quant=2),
        fe_snippet=dict(
            url="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/x.htm",
            accession="0000000001-26-000001",
            label="Verified fact",
        ),
        chain=dict(
            ai_demand="Verified fact",
            customer_contract="Verified fact",
            revenue_backlog="Verified fact",
            margin_cash_flow="Verified fact",
            bottleneck="Verified fact",
        ),
        chain_missing=[],
        direct_material=True,
        score=86,
        price_status="VERIFIED_DELAYED",
        portfolio=dict(
            equity_usd=100000.0,
            drawdown_pct=0.0,
            open_positions=0,
            invested_pct=0.0,
            layer_weight_pct={},
            trades_created=10,
        ),
        regime=dict(known=True, adverse=False),
        val_stats=dict(
            median_ev_ebitda=dict(utility_ipp=None),
            ev_ebitda_p90=40.0,
            vol260_median=1.0,
        ),
        bottleneck_sources=2,
        db=dict(
            max_risk_pct_tier_b=0.5,
            freq_max_initial_weight_pct=5,
            max_total_weight_pct=10,
            max_open_positions=20,
            min_cash_pct=10,
            ramp_factor=0.5,
            ramp_first_n_trades=4,
        ),
        score_tier_a=True,
        max_corr=None,
    )
    c.update(kw)
    return c


def breakout(rows):
    """last session closes above the prior 20-session high on 2x volume."""
    r = dict(rows[-1])
    r["c"] = r["ac"] = max((x["c"] for x in rows[-21:-1])) * 1.03
    r["h"] = r["c"] * 1.005
    r["o"] = r["c"] * 0.99
    r["l"] = r["c"] * 0.985
    r["v"] = 2000000
    return rows[:-1] + [r]


class Indicators(unittest.TestCase):

    def test_sma_atr_history(self):
        rows = series(300)
        ind = indicators.compute(rows)
        self.assertTrue(ind["enough_history"])
        self.assertAlmostEqual(ind["sma50"], sum((r["c"] for r in rows[-50:])) / 50)
        self.assertIsNotNone(ind["atr20"])
        self.assertGreater(ind["ret_12m"], 0)

    def test_short_history_fails_closed(self):
        ind = indicators.compute(series(100))
        self.assertIsNone(ind["sma200"])
        self.assertIsNone(ind["ret_12m"])
        self.assertFalse(ind["enough_history"])

    def test_month_end_excludes_current_month(self):
        rows = series(300)
        me = indicators.month_end_closes(rows)
        self.assertNotEqual(me[-1]["d"][:7], rows[-1]["d"][:7])


class Entry(unittest.TestCase):

    def test_e1_e2_breakout(self):
        r = aplus.evaluate(ctx(breakout(series(300))), CFG)
        self.assertTrue(r["entry"]["E1"])
        self.assertTrue(r["entry"]["E2"])

    def test_downtrend_fails_e1(self):
        r = aplus.evaluate(ctx(series(300, start=200, step=-0.2)), CFG)
        self.assertFalse(r["entry"]["E1"])
        self.assertIn(6, r["failing"])

    def test_e3_pullback(self):
        rows = series(300, start=50, step=0.25)
        hi = max((r["h"] for r in rows[-60:]))
        s50 = sum((r["c"] for r in rows[-50:])) / 50
        last = dict(rows[-1])
        last["c"] = last["ac"] = max(s50 * 1.001, hi * 0.92)
        last["l"] = s50 * 0.995
        last["o"] = last["c"]
        last["h"] = last["c"] * 1.01
        rows = rows[:-1] + [last]
        ind = indicators.compute(rows)
        pb = 1 - ind["close"] / ind["high60"]
        r = aplus.evaluate(ctx(rows), CFG)
        self.assertEqual(
            r["entry"]["E3"],
            0.05 <= pb <= 0.15
            and ind["sma50"] * 0.98 <= ind["low"] <= ind["sma50"]
            and (ind["close"] >= ind["sma50"])
            and r["entry"]["E1"],
        )


class FocusGateC3(unittest.TestCase):
    """v3.0.1: the DB focus gate is evaluated before a trade (check C3), never loosened."""

    def test_all_pass_is_aplus(self):
        r = aplus.evaluate(ctx(breakout(series(300))), CFG)
        self.assertEqual(r["failing"], [])
        self.assertEqual(r["grade"], "A+")

    def test_infra_without_filing_or_db_source_fails(self):
        r = aplus.evaluate(
            ctx(
                breakout(series(300)),
                fe_snippet=None,
                focus_db=dict(
                    focus_segment="power_grid_infrastructure",
                    relevance_material=False,
                    grade_a_relevance_source=False,
                ),
            ),
            CFG,
        )
        self.assertIn("C3", r["failing"])
        self.assertNotEqual(r["grade"], "A+")
        self.assertNotEqual(r["grade"], "B")

    def test_infra_with_db_grade_a_source_passes(self):
        r = aplus.evaluate(
            ctx(
                breakout(series(300)),
                fe_snippet=None,
                focus_db=dict(
                    focus_segment="power_grid_infrastructure",
                    relevance_material=True,
                    grade_a_relevance_source=True,
                ),
            ),
            CFG,
        )
        self.assertNotIn("C3", r["failing"])

    def test_developer_needs_financing_and_permits(self):
        row = dict(
            layer="A",
            subsector="Lithium",
            focus_segment="developer_financed_permitted",
            us_listed=True,
        )
        r = aplus.evaluate(
            ctx(
                breakout(series(300)),
                row=row,
                focus_db=dict(
                    focus_segment="developer_financed_permitted",
                    financing_credible=True,
                    permitting_credible=False,
                ),
            ),
            CFG,
        )
        self.assertIn("C3", r["failing"])

    def test_unknown_in_db_fails_closed(self):
        r = aplus.evaluate(ctx(breakout(series(300)), focus_db={}), CFG)
        self.assertIn("C1", r["failing"])
        self.assertNotEqual(r["grade"], "A+")

    def test_db_context_only_overrides_file(self):
        r = aplus.evaluate(
            ctx(breakout(series(300)), focus_db=dict(focus_segment="context_only")), CFG
        )
        self.assertIn("C1", r["failing"])


class StopsSizing(unittest.TestCase):

    def test_x1_stop_formula(self):
        rows = breakout(series(300))
        ind = indicators.compute(rows)
        r = aplus.evaluate(ctx(rows), CFG)
        e = ind["close"]
        self.assertAlmostEqual(
            r["sizing"]["stop"],
            round(max(e * 0.8, e - 2.5 * ind["atr20"]), 4),
            places=3,
        )

    def test_cost_cap_5pct_and_risk(self):
        r = aplus.evaluate(ctx(breakout(series(300))), CFG)
        s = r["sizing"]
        self.assertLessEqual(s["weight_pct"], 5.0 + 1e-09)
        self.assertLessEqual(s["risk_pct"], 1.0)

    def test_ramp_and_tier_b(self):
        r = aplus.evaluate(
            ctx(
                breakout(series(300)),
                score_tier_a=False,
                portfolio=dict(
                    equity_usd=100000.0,
                    drawdown_pct=0.0,
                    open_positions=0,
                    invested_pct=0.0,
                    layer_weight_pct={},
                    trades_created=0,
                ),
            ),
            CFG,
        )
        self.assertEqual(r["sizing"]["risk_pct"], 0.5)
        self.assertEqual(r["sizing"]["multiplier"], 0.5)

    def test_drawdown_15_blocks(self):
        c = ctx(breakout(series(300)))
        c["portfolio"]["drawdown_pct"] = 16.0
        r = aplus.evaluate(c, CFG)
        self.assertIn(11, r["failing"])
        self.assertNotEqual(r["grade"], "A+")

    def test_max_positions(self):
        c = ctx(breakout(series(300)))
        c["portfolio"]["open_positions"] = 7
        c["max_corr"] = 0.1
        r = aplus.evaluate(c, CFG)
        self.assertIn(15, r["failing"])


class Grades(unittest.TestCase):

    def test_full_pass_is_aplus(self):
        r = aplus.evaluate(ctx(breakout(series(300))), CFG)
        self.assertEqual(r["failing"], [], r["plain_fail"])
        self.assertEqual(r["grade"], "A+")
        self.assertEqual(r["action"], "paper_trade")

    def test_missing_fundamentals_fail(self):
        r = aplus.evaluate(ctx(breakout(series(300)), fund=dict(available=False)), CFG)
        self.assertIn(12, r["failing"])
        self.assertNotEqual(r["grade"], "A+")

    def test_unscanned_filing_is_a_veto(self):
        r = aplus.evaluate(ctx(breakout(series(300)), flags=None), CFG)
        self.assertTrue(r["vetoes"]["munger"])
        self.assertEqual(r["grade"], "Reject")

    def test_bottleneck_sources_required(self):
        r = aplus.evaluate(ctx(breakout(series(300)), bottleneck_sources=1), CFG)
        self.assertIn(5, r["failing"])
        self.assertEqual(r["grade"], "B")

    def test_context_only_never_aplus(self):
        c = ctx(breakout(series(300)))
        c["row"]["focus_segment"] = "context_only"
        r = aplus.evaluate(c, CFG)
        self.assertEqual(r["failing"], ["C1"])
        self.assertEqual(r["grade"], "B")

    def test_timing_only_is_watchlist(self):
        r = aplus.evaluate(ctx(series(300, start=200, step=-0.2)), CFG)
        self.assertNotEqual(r["grade"], "A+")

    def test_unmapped_segment_valuation_fails(self):
        c = ctx(breakout(series(300)))
        c["row"].update(
            layer="G",
            subsector="Semiconductors",
            focus_segment="power_grid_infrastructure",
        )
        r = aplus.evaluate(c, CFG)
        self.assertEqual(r["segment"], "unmapped")
        self.assertIn(12, r["failing"])

    def test_low_research_score_blocks(self):
        r = aplus.evaluate(ctx(breakout(series(300)), score=65), CFG)
        self.assertEqual(r["failing"], ["C2"])
        self.assertEqual(r["grade"], "B")

    def test_deterministic(self):
        rows = breakout(series(300))
        self.assertEqual(
            aplus.evaluate(ctx(rows), CFG)["checks"],
            aplus.evaluate(ctx(rows), CFG)["checks"],
        )

    def test_conflicts_documented(self):
        self.assertGreaterEqual(len(aplus.CONFLICTS), 15)
        for t in aplus.CONFLICTS:
            self.assertEqual(len(t), 4)


class Exits(unittest.TestCase):

    def pos(self, rows, **kw):
        p = dict(
            ticker="TST",
            entry_price=rows[-30]["c"],
            stop_price=rows[-30]["c"] * 0.9,
            entry_date=rows[-30]["d"],
            highest_close=None,
        )
        p.update(kw)
        return p

    def test_x1_stop_hit(self):
        rows = series(300)
        last = dict(rows[-1])
        p = self.pos(rows)
        last["o"] = p["stop_price"] * 1.02
        last["l"] = p["stop_price"] * 0.99
        m = exits.manage(p, rows[:-1] + [last], CFG)
        self.assertEqual(m["action"], "exit_now")
        self.assertEqual(m["price"], p["stop_price"])

    def test_x1_gap_fills_at_open(self):
        rows = series(300)
        last = dict(rows[-1])
        p = self.pos(rows)
        last["o"] = p["stop_price"] * 0.95
        last["l"] = last["o"] * 0.99
        m = exits.manage(p, rows[:-1] + [last], CFG)
        self.assertEqual(m["price"], last["o"])

    def test_x2_below_sma200_queues(self):
        rows = series(300, start=200, step=-0.2)
        p = self.pos(rows, stop_price=1.0)
        m = exits.manage(p, rows, CFG)
        self.assertEqual(m["action"], "queue_exit")
        self.assertIn("X2", m["reason"])

    def test_x4_breakeven_then_trail_never_lower(self):
        rows = series(300, step=0.6)
        p = self.pos(
            rows,
            entry_price=rows[-1]["c"] / 1.35,
            stop_price=rows[-1]["c"] / 1.35 * 0.9,
        )
        m = exits.manage(p, rows, CFG)
        self.assertEqual(m["action"], "raise_stop")
        self.assertGreaterEqual(m["new_stop"], p["entry_price"])
        p2 = dict(p, stop_price=m["new_stop"] + 100)
        m2 = exits.manage(p2, rows, CFG)
        self.assertNotEqual(m2["action"], "raise_stop")

    def test_x3_time_stop(self):
        rows = series(300, step=0.001)
        p = self.pos(
            rows,
            entry_price=rows[-200]["c"],
            entry_date=rows[-200]["d"],
            stop_price=rows[-200]["c"] * 0.9,
        )
        m = exits.manage(p, rows, CFG)
        self.assertEqual(m["action"], "queue_exit")
        self.assertIn("X3", m["reason"])

    def test_pending_exit_fills_at_open(self):
        rows = series(300)
        m = exits.manage(self.pos(rows), rows, CFG, pending_exit="X2 test")
        self.assertEqual((m["action"], m["price"]), ("exit_now", rows[-1]["o"]))
