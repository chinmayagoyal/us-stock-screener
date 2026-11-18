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
    d["fcf_after_sbc"] = d["fcf"] - num("sbc").fillna(0)
    d["net_debt"] = num("debt").fillna(0) - num("cash").fillna(0)

    d["ebit_ev"] = _div(d["ebit"], ev)
    d["ebit_ev_norm"] = _div(num("ebit_norm"), ev)
    d["ev_ebit_norm"] = _div(ev, num("ebit_norm").where(num("ebit_norm") > 0))
    d["fcf_yield"] = _div(d["fcf_after_sbc"], mc)
    d["earnings_yield"] = _div(d["net_income"], mc)
    # net shareholder yield: dividends plus the year-on-year fall in diluted share count (issuance counts against)
    net_buyback = 1 - _div(num("wdil_shares"), num("wdil_shares_prior"))
    gross_buyback = _div(num("buybacks").fillna(0), mc)
    d["shareholder_yield"] = _div(num("dividends").fillna(0), mc) + net_buyback.fillna(gross_buyback)
    d["sales_ev"] = _div(d["revenue"], ev)
    d["pe"] = _div(mc, d["net_income"].where(d["net_income"] > 0))
    d["ev_ebitda"] = _div(ev, d["ebitda"].where(d["ebitda"] > 0))
    d["ev_ebit"] = _div(ev, d["ebit"].where(d["ebit"] > 0))
    d["p_fcf"] = _div(mc, d["fcf"].where(d["fcf"] > 0))
    ic = num("debt").fillna(0) + num("equity") - num("cash").fillna(0)
    # cash-rich firms can show negative net invested capital; fall back to gross (debt + equity)
    ic = ic.where(ic > 0, num("debt").fillna(0) + num("equity"))
    d["roic"] = _div(d["ebit"] * (1 - C.TAX_RATE), ic.where(ic > 0))
    d["gp_assets"] = _div(d["gross_profit"], d["assets"])
    d["accruals"] = _div(d["net_income"] - d["cfo"], d["assets"])
    d["net_debt_ebitda"] = _div(d["net_debt"], d["ebitda"].where(d["ebitda"] > 0))
    intr = num("interest")
    d["interest_cover"] = _div(d["ebit"], intr.where(intr > 0))
    d["rev_growth"] = _div(d["revenue"], d["revenue_prior"].where(d["revenue_prior"] > 0)) - 1
    d["gross_margin"] = _div(d["gross_profit"], d["revenue"])
    d["oper_margin"] = _div(d["ebit"], d["revenue"])
    fcf_pos = d["fcf_after_sbc"].where(d["fcf_after_sbc"] > 0)
    r = C.COST_OF_EQUITY
    d["implied_fcf_growth"] = (r * mc - fcf_pos) / (mc + fcf_pos)
    d["fscore"], d["fscore_tests"] = _fscore(d)
    d["rd_intensity"] = _div(num("rd"), d["revenue"])
    nopat = d["ebit"] * (1 - C.TAX_RATE)
    reinvest = num("capex").abs().fillna(0) - num("da").fillna(0) + num("acquisitions").fillna(0) + num("rd").fillna(0)
    d["reinvestment_rate"] = _div(reinvest, (nopat + num("rd").fillna(0)).where(nopat > 0))
    cagr = pd.to_numeric(d.get("rev_cagr_3y"), errors="coerce")
    d["ev_ebit_per_growth"] = _div(d["ev_ebit"], (cagr * 100).where(cagr > 0))
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
def _rank(d, col, direction, group, w):
    s = pd.to_numeric(d[col], errors="coerce") * direction
    overall = s.rank(pct=True)
    by_sector = s.groupby(d[group]).rank(pct=True)
    size = s.groupby(d[group]).transform("count")
    out = np.where(size >= C.MIN_SECTOR_SIZE, w * by_sector + (1 - w) * overall, overall)
    return pd.Series(out, index=d.index).where(s.notna()) * 100


def _composite(d, metrics, group, min_n, w):
    ranks = pd.DataFrame({m: _rank(d, m, sgn, group, w) for m, sgn in metrics.items() if m in d})
    avg = ranks.mean(axis=1).where(ranks.notna().sum(axis=1) >= min_n)
    return avg.rank(pct=True) * 100


def _blend(parts, weights):
    num = sum(parts[k].fillna(0) * w for k, w in weights.items())
    den = sum(parts[k].notna() * w for k, w in weights.items())
    return (num / den.where(den >= 0.5)).rank(pct=True) * 100


def _cap_per_industry(d, flag, score_col):
    """Keep at most MAX_PER_INDUSTRY flagged names per industry (highest score first)."""
    ind = d["y_industry"].fillna(d["industry"]) if "y_industry" in d else d["industry"]
    order = d[flag].assign(_ind=ind[flag]).sort_values(score_col, ascending=False)
    keep = order.groupby("_ind").cumcount() < C.MAX_PER_INDUSTRY
    out = pd.Series(False, index=d.index)
    out[order.index[keep.values]] = True
    return out


def score(d):
    d = d.copy()
    d["rank_group"] = d["y_sector"].fillna(d["sector"]) if "y_sector" in d else d["sector"]
    g = "rank_group"
    W = C.SECTOR_WEIGHTS
    d["value_score"] = _composite(d, C.VALUE_METRICS, g, 3, W["value"])
    d["quality_score"] = _composite(d, C.QUALITY_METRICS, g, 3, W["quality"])
    d["momentum_score"] = _composite(d, C.MOMENTUM_METRICS, g, 2, W["momentum"])
    d["revisions_score"] = _composite(d, C.REVISION_METRICS, g, 1, W["revisions"])
    d["sentiment_score"] = _composite(d, C.SENTIMENT_METRICS, g, 1, W["sentiment"])
    parts = {"value": d["value_score"], "quality": d["quality_score"], "momentum": d["momentum_score"],
             "revisions": d["revisions_score"], "sentiment": d["sentiment_score"]}
    d["lt_score"] = _blend(parts, C.LT_WEIGHTS)
    d["st_score"] = _blend(parts, C.ST_WEIGHTS)

    L, S_, T = C.LT_FLAG, C.ST_FLAG, C.TRAP_FLAG
    lt = (d["lt_score"] >= L["min_lt_score"]) & (d["value_score"] >= L["min_value"]) \
        & (d["fscore"] >= L["min_fscore"]) & (d["implied_fcf_growth"] <= L["max_implied_growth"])
    st = (d["st_score"] >= S_["min_st_score"]) & (d["value_score"] >= S_["min_value"]) \
        & (d["ret_12_1"] > 0) & ((d["revisions_score"] >= S_["min_revisions"]) | d["revisions_score"].isna())
    lt = _cap_per_industry(d, lt, "lt_score")
    st = _cap_per_industry(d, st, "st_score")
    trap = (d["value_score"] >= T["min_value"]) & (
        (d["quality_score"] < T["max_quality"])
        | ((d["momentum_score"] < T["max_momentum"]) & (d["revisions_score"] < T["max_revisions"])))
    d["flag_lt"], d["flag_st"], d["flag_trap"] = lt, st, trap & ~lt & ~st
    d["signal"] = np.select([lt & st, lt, st, trap],
                            ["Both", "Long-term value", "Short-term setup", "Value-trap risk"], "")
    return d


def score_compounders(p):
    """Percentile scores within the compounder pool (market-wide: the pool is small)."""
    p = p.copy()
    if p.empty:
        for c in ["comp_score", "comp_growth_score", "comp_returns_score", "comp_valuation_score",
                  "comp_alignment_score"]:
            p[c] = pd.Series(dtype=float)
        p["flag_comp"] = pd.Series(dtype=bool)
        return p
    parts = {}
    for name, metrics in C.COMP_METRICS.items():
        ranks = pd.DataFrame({m: (pd.to_numeric(p[m], errors="coerce") * sgn).rank(pct=True) * 100
                              for m, sgn in metrics.items() if m in p})
        parts[name] = ranks.mean(axis=1).where(ranks.notna().sum(axis=1) >= 1)
        p[f"comp_{name}_score"] = parts[name].rank(pct=True) * 100
    p["comp_score"] = _blend({k: p[f"comp_{k}_score"] for k in parts}, C.COMP_WEIGHTS)
    top = p["comp_score"].rank(ascending=False) <= C.COMP_FLAG_TOP * 2
    capped = _cap_per_industry(p, top, "comp_score")
    keep = p.loc[capped, "comp_score"].sort_values(ascending=False).head(C.COMP_FLAG_TOP).index
    p["flag_comp"] = p.index.isin(keep)
    return p
