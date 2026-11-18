"""Valuation / quality / momentum metrics and the long-term and short-term scores."""
import numpy as np
import pandas as pd

from . import config as C


def _div(a, b):
    a, b = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
    return a / b.where(b != 0)


def add_fundamental_metrics(df):
    d = df.copy()
    num = lambda c: pd.to_numeric(d.get(c), errors="coerce")  # noqa: E731
    price = num("price")
    mcap_sec = price * num("shares_out")
    ratio = mcap_sec / num("mcap_nasdaq")
    d["market_cap"] = np.where(ratio.between(0.33, 3), mcap_sec, num("mcap_nasdaq"))
    mc = d["market_cap"]
    d["ev"] = mc + num("debt").fillna(0) + num("nci").fillna(0) - num("cash").fillna(0)
    ev = d["ev"].where(d["ev"] > 0)
    d["ebitda"] = num("ebit") + num("da").fillna(0)
    d["fcf"] = num("cfo") - num("capex").abs().fillna(0)
    d["net_debt"] = num("debt").fillna(0) - num("cash").fillna(0)

    d["ebit_ev"] = _div(d["ebit"], ev)
    d["fcf_yield"] = _div(d["fcf"], mc)
    d["earnings_yield"] = _div(d["net_income"], mc)
    d["shareholder_yield"] = _div(num("dividends").fillna(0) + num("buybacks").fillna(0), mc)
    d["sales_ev"] = _div(d["revenue"], ev)
    d["pe"] = _div(mc, d["net_income"].where(d["net_income"] > 0))
    d["ev_ebitda"] = _div(ev, d["ebitda"].where(d["ebitda"] > 0))
    d["ev_ebit"] = _div(ev, d["ebit"].where(d["ebit"] > 0))
    d["p_fcf"] = _div(mc, d["fcf"].where(d["fcf"] > 0))
    ic = num("debt").fillna(0) + num("equity") - num("cash").fillna(0)
    d["roic"] = _div(d["ebit"] * (1 - C.TAX_RATE), ic.where(ic > 0))
    d["gp_assets"] = _div(d["gross_profit"], d["assets"])
    d["accruals"] = _div(d["net_income"] - d["cfo"], d["assets"])
    d["net_debt_ebitda"] = _div(d["net_debt"], d["ebitda"].where(d["ebitda"] > 0))
    intr = num("interest")
    d["interest_cover"] = _div(d["ebit"], intr.where(intr > 0))
    d["rev_growth"] = _div(d["revenue"], d["revenue_prior"].where(d["revenue_prior"] > 0)) - 1
    d["gross_margin"] = _div(d["gross_profit"], d["revenue"])
    d["oper_margin"] = _div(d["ebit"], d["revenue"])
    fcf_pos = d["fcf"].where(d["fcf"] > 0)
    r = C.COST_OF_EQUITY
    d["implied_fcf_growth"] = (r * mc - fcf_pos) / (mc + fcf_pos)
    d["fscore"], d["fscore_tests"] = _fscore(d)
    return d


def _fscore(d):
    num = lambda c: pd.to_numeric(d[c], errors="coerce")  # noqa: E731
    roa = _div(num("net_income"), num("assets"))
    roa0 = _div(num("net_income_prior"), num("assets_prior"))
    lev, lev0 = _div(num("lt_debt"), num("assets")), _div(num("lt_debt_prior"), num("assets_prior"))
    cr, cr0 = _div(num("cur_assets"), num("cur_liab")), _div(num("cur_assets_prior"), num("cur_liab_prior"))
    gm, gm0 = _div(num("gross_profit"), num("revenue")), _div(num("gross_profit_prior"), num("revenue_prior"))
    at, at0 = _div(num("revenue"), num("assets")), _div(num("revenue_prior"), num("assets_prior"))
    tests = [
        roa > 0, num("cfo") > 0, roa > roa0, num("cfo") > num("net_income"),
        lev <= lev0, cr > cr0, num("wdil_shares") <= num("wdil_shares_prior") * 1.005,
        gm > gm0, at > at0,
    ]
    avail = [roa.notna(), num("cfo").notna(), roa.notna() & roa0.notna(),
             num("cfo").notna() & num("net_income").notna(), lev.notna() & lev0.notna(),
             cr.notna() & cr0.notna(), num("wdil_shares").notna() & num("wdil_shares_prior").notna(),
             gm.notna() & gm0.notna(), at.notna() & at0.notna()]
    passed = sum((t & a).astype(int) for t, a in zip(tests, avail))
    n = sum(a.astype(int) for a in avail)
    score = (passed / n.where(n >= 6) * 9).round()
    return score, n


def add_market_metrics(d):
    d = d.copy()
    num = lambda c: pd.to_numeric(d.get(c), errors="coerce")  # noqa: E731
    d["fwd_earnings_yield"] = _div(num("forward_eps"), num("price"))
    d["target_upside"] = _div(num("target_mean"), num("price")) - 1
    return d


# ------------------------------------------------------------------ ranking
def _rank(d, col, direction, group):
    s = pd.to_numeric(d[col], errors="coerce") * direction
    overall = s.rank(pct=True)
    by_sector = s.groupby(d[group]).rank(pct=True)
    size = s.groupby(d[group]).transform("count")
    w = C.SECTOR_WEIGHT
    out = np.where(size >= C.MIN_SECTOR_SIZE, w * by_sector + (1 - w) * overall, overall)
    return pd.Series(out, index=d.index).where(s.notna()) * 100


def _composite(d, metrics, group, min_n):
    ranks = pd.DataFrame({m: _rank(d, m, sgn, group) for m, sgn in metrics.items() if m in d})
    avg = ranks.mean(axis=1).where(ranks.notna().sum(axis=1) >= min_n)
    return avg.rank(pct=True) * 100


def _blend(parts, weights):
    num = sum(parts[k].fillna(0) * w for k, w in weights.items())
    den = sum(parts[k].notna() * w for k, w in weights.items())
    return (num / den.where(den >= 0.5)).rank(pct=True) * 100


def score(d):
    d = d.copy()
    d["rank_group"] = d["y_sector"].fillna(d["sector"]) if "y_sector" in d else d["sector"]
    g = "rank_group"
    d["value_score"] = _composite(d, C.VALUE_METRICS, g, 3)
    d["quality_score"] = _composite(d, C.QUALITY_METRICS, g, 3)
    d["momentum_score"] = _composite(d, C.MOMENTUM_METRICS, g, 2)
    d["revisions_score"] = _composite(d, C.REVISION_METRICS, g, 1)
    d["sentiment_score"] = _composite(d, C.SENTIMENT_METRICS, g, 1)
    parts = {"value": d["value_score"], "quality": d["quality_score"], "momentum": d["momentum_score"],
             "revisions": d["revisions_score"], "sentiment": d["sentiment_score"]}
    d["lt_score"] = _blend(parts, C.LT_WEIGHTS)
    d["st_score"] = _blend(parts, C.ST_WEIGHTS)

    lt = (d["lt_score"] >= C.LT_FLAG["min_lt_score"]) & (d["value_score"] >= C.LT_FLAG["min_value"]) \
        & (d["fscore"] >= C.LT_FLAG["min_fscore"])
    st = (d["st_score"] >= C.ST_FLAG["min_st_score"]) & (d["value_score"] >= C.ST_FLAG["min_value"]) \
        & (d["ret_12_1"] > 0) & ((d["revisions_score"] >= C.ST_FLAG["min_revisions"]) | d["revisions_score"].isna())
    trap = (d["value_score"] >= C.TRAP_FLAG["min_value"]) & (d["quality_score"] < C.TRAP_FLAG["max_quality"])
    d["flag_lt"], d["flag_st"], d["flag_trap"] = lt, st, trap
    d["signal"] = np.select([lt & st, lt, st, trap],
                            ["Both", "Long-term value", "Short-term setup", "Value-trap risk"], "")
    return d
