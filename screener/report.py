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
    "pe", "forward_pe", "ev_ebitda", "ev_ebit", "p_fcf",
    "ebit_ev", "fcf_yield", "earnings_yield", "fwd_earnings_yield", "shareholder_yield", "sales_ev",
    "implied_fcf_growth",
    "roic", "gp_assets", "gross_margin", "oper_margin", "fscore", "accruals", "net_debt_ebitda",
    "interest_cover", "rev_growth",
    "ret_1m", "ret_3m", "ret_6_1", "ret_12_1", "px_vs_200d", "pct_off_52w_high", "vol_3m",
    "eps_rev_cy_90d", "eps_rev_ny_90d", "rev_breadth_30d", "eps_surprise_last", "eps_surprise_avg",
    "target_upside", "recommendation_mean", "n_analysts", "short_pct_float", "insider_net_pct",
    "next_earnings", "dividend_yield",
    "revenue", "ebit", "net_income", "fcf", "net_debt", "dollar_vol_60d",
    "period_end", "price_date", "flag_lt", "flag_st", "flag_trap", "cik",
]

PCT = {"ebit_ev", "fcf_yield", "earnings_yield", "fwd_earnings_yield", "shareholder_yield", "implied_fcf_growth",
       "roic", "gp_assets", "gross_margin", "oper_margin", "accruals", "rev_growth", "ret_1m", "ret_3m", "ret_6_1",
       "ret_12_1", "px_vs_200d", "pct_off_52w_high", "vol_3m", "eps_rev_cy_90d", "eps_rev_ny_90d",
       "rev_breadth_30d", "eps_surprise_last", "eps_surprise_avg", "target_upside", "short_pct_float",
       "insider_net_pct", "dividend_yield", "group_return", "candidates_return", "spy_return",
       "excess_vs_candidates", "pct_names_beating_candidates", "avg_group_return", "avg_candidates_return",
       "avg_spy_return", "avg_excess", "snapshot_hit_rate", "name_hit_rate"}
MULT = {"pe", "forward_pe", "ev_ebitda", "ev_ebit", "p_fcf", "sales_ev", "net_debt_ebitda", "interest_cover",
        "recommendation_mean"}
BIG = {"market_cap", "ev", "revenue", "ebit", "net_income", "fcf", "net_debt", "dollar_vol_60d"}
SCORES = {"lt_score", "st_score", "value_score", "quality_score", "momentum_score", "revisions_score",
          "sentiment_score"}

METHOD = [
    ("What this is", "Daily screen of every US-listed stock. An initial filter keeps investable, profitable, "
                     "solvent companies; survivors are scored for long-term undervaluation and short-term setups."),
    ("Initial filter", "Common stock only (no ETFs/funds/preferreds/warrants/SPACs); market cap >= $%.0fB; excludes "
                       "Finance and Real Estate sectors; price >= $%g; 60-day median dollar volume >= $%.0fM; "
                       ">= 1 year of trading; SEC US-GAAP financials in USD no older than %d days; TTM operating "
                       "income > 0 and operating cash flow > 0; net debt/EBITDA <= %.0fx (or net cash) and "
                       "interest cover >= %.0fx."
     % (C.MIN_MARKET_CAP / 1e9, C.MIN_PRICE, C.MIN_DOLLAR_VOLUME / 1e6, C.MAX_FILING_AGE_DAYS,
        C.MAX_NET_DEBT_TO_EBITDA, C.MIN_INTEREST_COVERAGE)),
    ("Ranking", "Every metric is converted to a 0-100 percentile: %.0f%% vs. sector peers, %.0f%% vs. all "
                "candidates. Composites average the available metric ranks and are re-ranked 0-100."
     % (C.SECTOR_WEIGHT * 100, (1 - C.SECTOR_WEIGHT) * 100)),
    ("Value composite", "EBIT/EV, FCF yield, earnings yield (1/PE), forward earnings yield, shareholder yield "
                        "(dividends + buybacks), sales/EV."),
    ("Quality composite", "ROIC, gross profit/assets, Piotroski F-score, accruals (lower better), net debt/EBITDA "
                          "(lower better), revenue growth."),
    ("Momentum composite", "12-1 month return, 6-1 month return, price vs 200-day average."),
    ("Revisions composite", "90-day change in current- and next-year consensus EPS, average EPS surprise "
                            "(last 4 quarters), 30-day revision breadth."),
    ("Sentiment composite", "Short interest % of float (lower better), net insider buying (6 months)."),
    ("Long-term score (1-3 yrs)", "%.0f%% value + %.0f%% quality." % (C.LT_WEIGHTS["value"] * 100,
                                                                     C.LT_WEIGHTS["quality"] * 100)),
    ("Short-term score (1-6 mo)", "%.0f%% momentum + %.0f%% revisions + %.0f%% value + %.0f%% sentiment."
     % tuple(C.ST_WEIGHTS[k] * 100 for k in ["momentum", "revisions", "value", "sentiment"])),
    ("Long-term value flag", "LT score >= %d, value >= %d, F-score >= %d."
     % (C.LT_FLAG["min_lt_score"], C.LT_FLAG["min_value"], C.LT_FLAG["min_fscore"])),
    ("Short-term setup flag", "ST score >= %d, value >= %d, positive 12-1 momentum, revisions >= %d."
     % (C.ST_FLAG["min_st_score"], C.ST_FLAG["min_value"], C.ST_FLAG["min_revisions"])),
    ("Value-trap risk flag", "Value >= %d but quality < %d: cheap, but the business may deserve it."
     % (C.TRAP_FLAG["min_value"], C.TRAP_FLAG["max_quality"])),
    ("Implied FCF growth", "Perpetual FCF growth the current price implies at a %.0f%% cost of equity "
                           "(reverse DCF). Low or negative = market expects little." % (C.COST_OF_EQUITY * 100)),
    ("Track record", "Forward returns of each day's flagged lists vs. the equal-weighted candidate set and SPY, "
                     "built only from snapshots this tool published. Fills in as the tool runs (1M after ~21 "
                     "trading days)."),
    ("Caveats", "Not investment advice. Fundamentals are rebuilt from XBRL and can mis-tag; Yahoo data is "
                "unofficial and may be incomplete. Verify any name against filings before acting."),
]


def changes_vs_previous(hist_dir, today, cands):
    files = sorted(f for f in glob.glob(os.path.join(hist_dir, "*.csv")) if os.path.basename(f)[:10] < today)
    cols = ["ticker", "company", "list", "change", "lt_score", "st_score", "price"]
    if not files:
        return pd.DataFrame(columns=cols)
    prev = pd.read_csv(files[-1])
    rows = []
    cur = cands.set_index("ticker")
    for lst, col in [("Long-term value", "flag_lt"), ("Short-term setup", "flag_st")]:
        before = set(prev.loc[prev[col].astype(str).str.lower() == "true", "ticker"])
        now = set(cands.loc[cands[col], "ticker"])
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


def write_excel(path, cands, funnel, track, changes, meta):
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
        _sheet(w, "All candidates", cands)
        _sheet(w, "Changes", changes)
        _sheet(w, "Filter funnel", funnel)
        _sheet(w, "Track record", track if len(track) else pd.DataFrame({"note": [
            "Builds automatically: 1-month results appear ~21 trading days after the first run."]}))
