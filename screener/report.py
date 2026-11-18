"""Output tables: candidate columns, day-over-day changes, and the Excel workbook."""
import glob
import os

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import config as C

CANDIDATE_COLUMNS = [
    "ticker", "company", "exchange", "sector", "industry", "country", "signal",
    "lt_score", "st_score", "value_score", "quality_score", "momentum_score", "revisions_score", "sentiment_score",
    "price", "market_cap", "ev",
    "pe", "forward_pe", "ev_ebitda", "ev_ebit", "ev_ebit_norm", "p_fcf",
    "ebit_ev", "ebit_ev_norm", "fcf_yield", "earnings_yield", "fwd_earnings_yield", "shareholder_yield", "sales_ev",
    "implied_fcf_growth",
    "roic", "gp_assets", "gross_margin", "oper_margin", "margin_volatility", "fscore", "accruals", "net_debt_ebitda",
    "interest_cover", "rev_growth",
    "ret_1m", "ret_3m", "ret_6_1", "ret_12_1", "px_vs_200d", "pct_off_52w_high", "vol_3m",
    "eps_rev_cy_90d", "eps_rev_ny_90d", "rev_breadth_30d", "eps_surprise_last", "eps_surprise_avg",
    "target_upside", "recommendation_mean", "n_analysts", "short_pct_float", "insider_net_pct",
    "next_earnings", "dividend_yield",
    "revenue", "ebit", "ebit_norm", "net_income", "fcf", "fcf_after_sbc", "sbc", "net_debt", "dollar_vol_60d",
    "sic", "sic_description", "period_end", "price_date", "flag_lt", "flag_st", "flag_trap", "cik",
    "rev_cagr_3y", "gm_trend", "roic_trend", "rd_intensity", "reinvestment_rate", "insider_own",
    "flag_comp", "comp_score", "conviction", "conviction_label", "review_date",
]

COMPOUNDER_COLUMNS = [
    "ticker", "company", "exchange", "sector", "industry", "country", "comp_score", "comp_growth_score",
    "comp_returns_score", "comp_valuation_score", "comp_alignment_score", "flag_comp", "in_core",
    "price", "market_cap", "rev_cagr_3y", "rev_growth", "gross_margin", "gm_trend", "oper_margin", "roic",
    "roic_trend", "reinvestment_rate", "rd_intensity", "ev_ebit", "ev_ebit_per_growth", "pe", "forward_pe",
    "fcf_yield", "implied_fcf_growth", "net_debt_ebitda", "insider_own", "ret_12_1", "ret_6_1",
    "eps_rev_cy_90d", "short_pct_float", "next_earnings", "conviction", "conviction_label", "review_date",
    "revenue", "ebit", "period_end", "price_date", "cik",
]

PCT = {"ebit_ev", "ebit_ev_norm", "margin_volatility", "rev_cagr_3y", "gm_trend", "roic_trend", "rd_intensity",
       "reinvestment_rate", "insider_own", "fcf_yield", "earnings_yield", "fwd_earnings_yield", "shareholder_yield", "implied_fcf_growth",
       "roic", "gp_assets", "gross_margin", "oper_margin", "accruals", "rev_growth", "ret_1m", "ret_3m", "ret_6_1",
       "ret_12_1", "px_vs_200d", "pct_off_52w_high", "vol_3m", "eps_rev_cy_90d", "eps_rev_ny_90d",
       "rev_breadth_30d", "eps_surprise_last", "eps_surprise_avg", "target_upside", "short_pct_float",
       "insider_net_pct", "dividend_yield", "group_return", "candidates_return", "spy_return",
       "excess_vs_candidates", "pct_names_beating_candidates", "avg_group_return", "avg_candidates_return",
       "avg_spy_return", "avg_excess", "snapshot_hit_rate", "name_hit_rate"}
MULT = {"pe", "forward_pe", "ev_ebitda", "ev_ebit", "ev_ebit_norm", "ev_ebit_per_growth", "conviction", "p_fcf", "sales_ev", "net_debt_ebitda", "interest_cover",
        "recommendation_mean"}
BIG = {"market_cap", "ev", "revenue", "ebit", "ebit_norm", "net_income", "fcf", "fcf_after_sbc", "sbc", "net_debt",
       "dollar_vol_60d"}
SCORES = {"lt_score", "st_score", "value_score", "quality_score", "momentum_score", "revisions_score",
          "sentiment_score", "comp_score", "comp_growth_score", "comp_returns_score", "comp_valuation_score",
          "comp_alignment_score"}

METHOD = [
    ("What this is", "Daily screen of every US-listed stock. An initial filter keeps investable, profitable, "
                     "solvent companies; survivors are scored for long-term undervaluation and short-term setups."),
    ("Initial filter", "Common stock only (no ETFs/funds/preferreds/warrants/SPACs); market cap >= $%.0fB; price >= "
                       "$%g; 60-day median dollar volume >= $%.0fM; >= 1 year of trading; excludes banks, lenders, "
                       "brokers, asset managers, insurers and REITs by SEC SIC code (exchanges and data/ratings firms "
                       "stay in); SEC US-GAAP financials in USD no older than %d days; TTM operating income > 0 and "
                       "operating cash flow > 0; net debt/EBITDA <= %.0fx (or net cash) and interest cover >= %.0fx."
     % (C.MIN_MARKET_CAP / 1e9, C.MIN_PRICE, C.MIN_DOLLAR_VOLUME / 1e6, C.MAX_FILING_AGE_DAYS,
        C.MAX_NET_DEBT_TO_EBITDA, C.MIN_INTEREST_COVERAGE)),
    ("Ranking", "Every metric becomes a 0-100 percentile, blending sector-relative and market-wide ranks "
                "(sector share: value %d%%, quality %d%%, momentum %d%%, revisions %d%%, sentiment %d%%). Composites "
                "average the available metric ranks and are re-ranked 0-100."
     % tuple(int(C.SECTOR_WEIGHTS[k] * 100) for k in ["value", "quality", "momentum", "revisions", "sentiment"])),
    ("Value composite", "Cycle-adjusted EBIT/EV (average of TTM and last 3 fiscal years), free-cash-flow yield after "
                        "stock compensation, forward earnings yield, net shareholder yield (dividends + fall in "
                        "diluted share count)."),
    ("Quality composite", "ROIC, gross profit/assets, Piotroski F-score, accruals (lower better), net debt/EBITDA "
                          "(lower better), operating-margin volatility over 5 years (lower better), revenue growth."),
    ("Momentum composite", "12-1 month return, 6-1 month return, price vs 200-day average."),
    ("Revisions composite", "90-day change in current- and next-year consensus EPS, latest and 4-quarter average EPS "
                            "surprise, 30-day revision breadth."),
    ("Sentiment composite", "Short interest % of float (lower better), net insider buying (6 months)."),
    ("Long-term score (1-3 yrs)", "%.0f%% value + %.0f%% quality." % (C.LT_WEIGHTS["value"] * 100,
                                                                     C.LT_WEIGHTS["quality"] * 100)),
    ("Short-term score (1-6 mo)", "%.0f%% momentum + %.0f%% revisions + %.0f%% value + %.0f%% sentiment."
     % tuple(C.ST_WEIGHTS[k] * 100 for k in ["momentum", "revisions", "value", "sentiment"])),
    ("Long-term value flag", "LT score >= %d, value >= %d, F-score >= %d, and the price implies <= %.0f%% perpetual "
                             "owner-FCF growth. At most %d names per industry."
     % (C.LT_FLAG["min_lt_score"], C.LT_FLAG["min_value"], C.LT_FLAG["min_fscore"],
        C.LT_FLAG["max_implied_growth"] * 100, C.MAX_PER_INDUSTRY)),
    ("Short-term setup flag", "ST score >= %d, value >= %d, positive 12-1 momentum, revisions >= %d. At most %d names "
                              "per industry." % (C.ST_FLAG["min_st_score"], C.ST_FLAG["min_value"],
                                                 C.ST_FLAG["min_revisions"], C.MAX_PER_INDUSTRY)),
    ("Value-trap risk flag", "Value >= %d and either quality < %d, or momentum < %d with revisions < %d: cheap, "
                             "and the business or the estimates are deteriorating."
     % (C.TRAP_FLAG["min_value"], C.TRAP_FLAG["max_quality"], C.TRAP_FLAG["max_momentum"],
        C.TRAP_FLAG["max_revisions"])),
    ("Compounders screen", "Separate, wider universe (market cap >= $%.1fB, $%.0fM daily volume). Gates: 3-year revenue "
                           "CAGR >= %.0f%%, TTM growth >= %.0f%%, ROIC >= %.0f%%, positive operating income and cash flow, "
                           "net debt/EBITDA <= %.0fx. Score: %.0f%% growth (CAGR, TTM growth, gross-margin trend), %.0f%% "
                           "returns (ROIC, ROIC trend, reinvestment rate), %.0f%% valuation (EV/EBIT per point of growth, "
                           "FCF yield), %.0f%% alignment (insider ownership, smaller size). Top %d flagged, max %d per industry."
     % (C.COMP_MIN_MARKET_CAP / 1e9, C.COMP_MIN_DOLLAR_VOLUME / 1e6, C.COMP_GATES["min_rev_cagr_3y"] * 100,
        C.COMP_GATES["min_rev_growth"] * 100, C.COMP_GATES["min_roic"] * 100, C.COMP_GATES["max_net_debt_ebitda"],
        C.COMP_WEIGHTS["growth"] * 100, C.COMP_WEIGHTS["returns"] * 100, C.COMP_WEIGHTS["valuation"] * 100,
        C.COMP_WEIGHTS["alignment"] * 100, C.COMP_FLAG_TOP, C.MAX_PER_INDUSTRY)),
    ("Qualitative review", "Claude researches each long-term and compounder name (filings, earnings calls, industry "
                           "sources) and scores 1-5: moat, disruption risk, industry structure, secular demand, "
                           "management/capital allocation, tail risks, catalyst. Conviction = weighted average "
                           "(moat 25%%, disruption 20%%, demand 15%%, management 15%%, tail risk 15%%, industry 10%%); "
                           "High >= 3.75, Medium >= 3.0. Reviews are refreshed after %d days." % C.REVIEW_MAX_AGE_DAYS),
    ("Implied FCF growth", "Perpetual owner-FCF growth the current price implies at a %.0f%% cost of equity "
                           "(reverse DCF). Low or negative = market expects little." % (C.COST_OF_EQUITY * 100)),
    ("Track record", "Forward returns of each day's flagged lists, entered at the next session's close, vs. the "
                     "equal-weighted candidate set and SPY. Built only from snapshots this tool published."),
    ("Caveats", "Not investment advice. Fundamentals are rebuilt from XBRL and can mis-tag; Yahoo data is "
                "unofficial and may be incomplete. Foreign filers reporting under IFRS are not covered. Verify any "
                "name against its filings before acting."),
]


def changes_vs_previous(hist_dir, today, cands, pool=None):
    files = sorted(f for f in glob.glob(os.path.join(hist_dir, "*.csv")) if os.path.basename(f)[:10] < today)
    cols = ["ticker", "company", "list", "change", "lt_score", "st_score", "price"]
    if not files:
        return pd.DataFrame(columns=cols)
    prev = pd.read_csv(files[-1])
    rows = []
    allc = cands if pool is None else pd.concat([cands, pool[~pool["ticker"].isin(cands["ticker"])]])
    cur = allc.set_index("ticker")
    for lst, col in [("Long-term value", "flag_lt"), ("Short-term setup", "flag_st"), ("Compounder", "flag_comp")]:
        if col not in prev:
            continue
        before = set(prev.loc[prev[col].astype(str).str.lower() == "true", "ticker"])
        now = set(allc.loc[allc[col].fillna(False).astype(bool), "ticker"])
        for t in sorted(now - before):
            r = cur.loc[t]
            rows.append([t, r["company"], lst, "Added", r["lt_score"], r["st_score"], r["price"]])
        for t in sorted(before - now):
            r = cur.loc[t] if t in cur.index else None
            rows.append([t, (r["company"] if r is not None else prev.set_index("ticker").loc[t, "company"]),
                         lst, "Dropped" if r is not None else "Dropped (left candidate list)",
                         r["lt_score"] if r is not None else None, r["st_score"] if r is not None else None,
                         r["price"] if r is not None else None])
    return pd.DataFrame(rows, columns=cols)


def _sheet(writer, name, df):
    df.to_excel(writer, sheet_name=name, index=False)
    ws = writer.sheets[name]
    head = PatternFill("solid", fgColor="1F3A5F")
    for j, col in enumerate(df.columns, 1):
        c = ws.cell(row=1, column=j)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), head
        c.alignment = Alignment(wrap_text=True, vertical="center")
        fmt = ("0.0%" if col in PCT else "0.0x" if col in MULT else '#,##0.0,,,"B"' if col in BIG
               else "0" if col in SCORES or col == "fscore" else None)
        if fmt:
            for i in range(2, len(df) + 2):
                ws.cell(row=i, column=j).number_format = fmt.replace("0.0x", '0.0"x"')
        width = max(10, min(40, len(str(col)) + 2, *(len(str(v)) + 2 for v in df[col].head(50))))
        ws.column_dimensions[get_column_letter(j)].width = width
    ws.freeze_panes = "C2" if "company" in df.columns else "A2"
    if len(df):
        ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 30


def write_excel(path, cands, funnel, track, changes, meta, comp=None, comp_funnel=None, reviews=None):
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        info = [("Run (UTC)", meta["run_utc"]), ("Prices as of", meta["price_date"]),
                ("Universe", meta["universe"]), ("Candidates", meta["candidates"]),
                ("Long-term value flags", meta["long_term_flags"]), ("Short-term flags", meta["short_term_flags"])]
        pd.DataFrame(info + [("", "")] + METHOD, columns=["Item", "Detail"]).to_excel(w, sheet_name="Read me", index=False)
        ws = w.sheets["Read me"]
        ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 28, 120
        for row in ws.iter_rows(min_row=2):
            row[1].alignment = Alignment(wrap_text=True, vertical="top")
            row[0].font = Font(bold=True)
        _sheet(w, "Long-term value", cands[cands["flag_lt"]].sort_values("lt_score", ascending=False))
        _sheet(w, "Short-term setups", cands[cands["flag_st"]].sort_values("st_score", ascending=False))
        if comp is not None:
            _sheet(w, "Compounders", comp[comp["flag_comp"]].sort_values("comp_score", ascending=False))
        if reviews is not None and len(reviews):
            _sheet(w, "Qualitative reviews", reviews)
        _sheet(w, "All candidates", cands)
        if comp is not None:
            _sheet(w, "Compounder pool", comp)
        _sheet(w, "Changes", changes)
        _sheet(w, "Filter funnel", funnel)
        if comp_funnel is not None:
            _sheet(w, "Compounder funnel", comp_funnel)
        _sheet(w, "Track record", track if len(track) else pd.DataFrame({"note": [
            "Builds automatically: 1-month results appear ~21 trading days after the first run."]}))


DASH_COLUMNS = [
    "ticker", "company", "sector", "industry", "signal", "lt_score", "st_score", "value_score", "quality_score",
    "momentum_score", "revisions_score", "sentiment_score", "price", "market_cap", "pe", "forward_pe",
    "ev_ebitda", "ev_ebit_norm", "p_fcf", "ebit_ev", "fcf_yield", "shareholder_yield", "implied_fcf_growth", "roic",
    "gross_margin", "oper_margin", "margin_volatility", "fscore", "net_debt_ebitda", "rev_growth", "ret_1m",
    "ret_6_1", "ret_12_1",
    "px_vs_200d", "pct_off_52w_high", "eps_rev_cy_90d", "eps_rev_ny_90d", "eps_surprise_last", "eps_surprise_avg", "target_upside",
    "short_pct_float", "insider_net_pct", "next_earnings", "dividend_yield", "period_end", "flag_lt", "flag_st",
    "flag_trap", "roic_trend", "insider_own", "rd_intensity", "flag_comp", "comp_score", "conviction",
    "conviction_label", "review_date",
]
DASH_COMP_COLUMNS = [
    "ticker", "company", "sector", "industry", "comp_score", "comp_growth_score", "comp_returns_score",
    "comp_valuation_score", "comp_alignment_score", "flag_comp", "in_core", "price", "market_cap", "rev_cagr_3y",
    "rev_growth", "gross_margin", "gm_trend", "roic", "roic_trend", "reinvestment_rate", "rd_intensity", "ev_ebit",
    "ev_ebit_per_growth", "fcf_yield", "insider_own", "ret_12_1", "conviction", "conviction_label", "review_date",
]


def _records(df, cols=None):
    import json
    import math
    df = df if cols is None else df[[c for c in cols if c in df.columns]]
    recs = json.loads(df.to_json(orient="records", double_precision=5))
    for r in recs:
        for k, v in r.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                r[k] = None
    return recs


def write_dashboard_json(out_dir, cands, funnel, track, changes, meta, comp=None, comp_funnel=None, reviews=None,
                         cands_full=None, pool_full=None):
    """Typed JSON files for the tracker page (one file per dataset)."""
    import json
    os.makedirs(out_dir, exist_ok=True)
    c = cands.copy()
    for col in ["flag_lt", "flag_st", "flag_trap"]:
        c[col] = c[col].astype(bool)
    c["signal"] = c["signal"].fillna("")
    files = {
        "candidates.json": _records(c, DASH_COLUMNS),
        "funnel.json": _records(funnel),
        "track_record.json": _records(track) if len(track) else [],
        "changes.json": _records(changes) if len(changes) else [],
        "compounders.json": _records(comp, DASH_COMP_COLUMNS) if comp is not None else [],
        "compounders_funnel.json": _records(comp_funnel) if comp_funnel is not None else [],
        "reviews.json": _review_rows(reviews, cands_full, pool_full),
        "summary.json": [{
            "run_utc": meta["run_utc"], "price_date": meta["price_date"], "universe": meta["universe"],
            "candidates": meta["candidates"], "long_term_flags": meta["long_term_flags"],
            "short_term_flags": meta["short_term_flags"], "both_flags": meta["both_flags"],
            "value_trap_flags": meta["value_trap_flags"],
            "yahoo_estimate_coverage": meta["yahoo_estimate_coverage"],
            "compounder_pool": meta.get("compounder_pool"), "compounder_flags": meta.get("compounder_flags"),
            "reviews_on_file": meta.get("reviews_on_file"), "review_queue": meta.get("review_queue"),
        }],
    }
    for name, recs in files.items():
        with open(os.path.join(out_dir, name), "w") as f:
            json.dump(recs, f, separators=(",", ":"))


def _review_rows(reviews, cands, pool):
    """Latest review per ticker, with the stock's current list membership."""
    if reviews is None or not len(reviews):
        return []
    r = reviews.copy()
    lists = {}
    if cands is not None:
        for _, c in cands.iterrows():
            tags = []
            if c.get("flag_lt"):
                tags.append("Long-term value")
            if c.get("flag_st"):
                tags.append("Short-term setup")
            lists[c["ticker"]] = tags
    if pool is not None:
        for _, c in pool[pool["flag_comp"]].iterrows():
            lists.setdefault(c["ticker"], []).append("Compounder")
    names = {}
    for df in (cands, pool):
        if df is not None:
            names.update(dict(zip(df["ticker"], df["company"])))
    r["company"] = r["ticker"].map(names)
    r["on_lists"] = r["ticker"].map(lambda t: ", ".join(lists.get(t, [])) or "Not currently listed")
    r = r.sort_values("conviction", ascending=False)
    return _records(r)
