"""Daily pipeline: universe -> data -> core value/short-term screen + compounders screen -> outputs.

    python -m screener.run            # full run
    python -m screener.run --limit 60 # quick smoke test on a sample
"""
import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config as C
from . import prices, qualitative, report, scoring, sec, track, universe, yahoo

OUT = "data/latest"
HIST = "data/history"
COMPANY_SUFFIX = (r"(?i)\s+(Common Stock|Common Shares|Class [A-C] (Common Stock|Common Shares|Ordinary Shares)|"
                  r"Ordinary Shares|American Depositary Shares)\b.*$")


class Funnel:
    def __init__(self, name):
        self.name, self.rows, self.dropped = name, [], []

    def start(self, label, rule, df):
        self.rows.append(dict(step=0, stage=label, rule=rule, remaining=len(df), removed=0))
        print(f"[{self.name} 0] {label}: {len(df)}")
        return df

    def step(self, label, rule, df, mask):
        mask = mask.fillna(False).astype(bool)
        after = df[mask]
        for _, r in df[~mask].iterrows():
            self.dropped.append(dict(screen=self.name, ticker=r.get("ticker"), company=r.get("name"),
                                     dropped_at=label,
                                     detail=r.get("sec_status") if label.startswith("Recent") else None))
        self.rows.append(dict(step=len(self.rows), stage=label, rule=rule, remaining=len(after),
                              removed=len(df) - len(after)))
        print(f"[{self.name} {len(self.rows)-1}] {label}: {len(after)} remaining ({len(df)-len(after)} removed)")
        return after


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="sample size for a smoke test")
    ap.add_argument("--skip-yahoo-estimates", action="store_true")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(HIST, exist_ok=True)
    run_at = datetime.now(timezone.utc)
    today = run_at.strftime("%Y-%m-%d")

    # ---------------------------------------------------------------- data for the whole investable base
    print("Loading universe...")
    u, uni_sources = universe.load_universe()
    common = u[universe.security_type_mask(u)].copy()
    base_cap = min(C.MIN_MARKET_CAP, C.COMP_MIN_MARKET_CAP)
    base = common[common["mcap_nasdaq"] >= base_cap].copy()
    if args.limit:
        base = base.sample(min(args.limit, len(base)), random_state=1)
        print(f"  smoke test: sampled {len(base)}")

    print(f"Downloading price history for {len(base)} stocks...")
    hist = prices.download_history(list(base["ticker"]) + ["SPY"])
    coverage = len(hist) / max(1, len(base) + 1)
    if coverage < C.MIN_PRICE_COVERAGE:
        raise SystemExit(f"Price download coverage {coverage:.0%} is too low; not publishing this run.")
    pm = pd.DataFrame.from_dict({t: prices.price_metrics(h) for t, h in hist.items() if t != "SPY"}, orient="index")
    base = base.join(pm, on="ticker")

    print("Mapping to SEC filers...")
    cikmap = sec.ticker_to_cik()
    base["cik"] = base["ticker"].str.upper().map(cikmap).astype("Int64")
    primary = base[base["cik"].notna()].sort_values("dollar_vol_60d", ascending=False).drop_duplicates("cik").index
    base["primary_class"] = base.index.isin(primary)

    liquid_base = base["primary_class"] & (base["price"] >= C.MIN_PRICE) \
        & (base["dollar_vol_60d"] >= min(C.MIN_DOLLAR_VOLUME, C.COMP_MIN_DOLLAR_VOLUME)) \
        & (base["history_days"] >= C.MIN_PRICE_HISTORY_DAYS)
    ciks = base.loc[liquid_base, "cik"].astype(int).tolist()
    print(f"Fetching SEC industry codes for {len(ciks)} companies...")
    sic = sec.fetch_sic(ciks)
    base["sic"] = base["cik"].map(lambda c: sic.get(c, (None, None))[0] if pd.notna(c) else None)
    base["sic_description"] = base["cik"].map(lambda c: sic.get(c, (None, None))[1] if pd.notna(c) else None)
    base["financial"] = base["sic"].map(sec.is_financial_sic)
    fetch = base.loc[liquid_base & ~base["financial"], "cik"].astype(int).tolist()
    print(f"Fetching SEC fundamentals for {len(fetch)} companies...")
    fund = sec.fetch_all(fetch)
    base = base.join(pd.DataFrame.from_dict(fund, orient="index"), on="cik")
    status_counts = base["sec_status"].value_counts().to_dict()
    base["filing_age"] = (pd.Timestamp(run_at.date()) - pd.to_datetime(base["period_end"], errors="coerce")).dt.days
    base = scoring.add_fundamental_metrics(base)
    base["company"] = base["name"].str.replace(COMPANY_SUFFIX, "", regex=True)
    recent = (base["sec_status"] == "ok") & (base["filing_age"] <= C.MAX_FILING_AGE_DAYS)

    # ---------------------------------------------------------------- core screen (value + short-term)
    F = Funnel("core")
    F.start("All US-listed securities", "NYSE, Nasdaq, NYSE American listings", u)
    s = F.step("Common stock only", "Drops ETFs, funds, preferreds, warrants, rights, units, notes, SPACs",
               u, universe.security_type_mask(u))
    s = F.step("Market cap >= $%.0fB" % (C.MIN_MARKET_CAP / 1e9), "Nasdaq-reported market capitalisation",
               s, s["mcap_nasdaq"] >= C.MIN_MARKET_CAP)
    s = base.loc[base.index.intersection(s.index)] if not args.limit else base[base["mcap_nasdaq"] >= C.MIN_MARKET_CAP]
    s = F.step("Price >= $%.0f, liquid, 1y+ history" % C.MIN_PRICE,
               "Price >= $%g; 60-day median $ volume >= $%.0fM; >= %d trading days"
               % (C.MIN_PRICE, C.MIN_DOLLAR_VOLUME / 1e6, C.MIN_PRICE_HISTORY_DAYS),
               s, (s["price"] >= C.MIN_PRICE) & (s["dollar_vol_60d"] >= C.MIN_DOLLAR_VOLUME)
               & (s["history_days"] >= C.MIN_PRICE_HISTORY_DAYS))
    s = F.step("SEC filer, one share class per company", "Ticker maps to an SEC CIK; keeps the most liquid class",
               s, s["primary_class"])
    s = F.step("Excludes banks, insurers, asset managers and REITs",
               "By SEC SIC code: these need book-value or FFO models. Exchanges, ratings/data firms stay in",
               s, ~s["financial"])
    s = F.step("Recent US-GAAP financials in USD",
               "SEC XBRL TTM rebuilt; latest period within %d days (IFRS/foreign-currency filers drop here)"
               % C.MAX_FILING_AGE_DAYS, s, recent.reindex(s.index))
    s = F.step("Profitable and cash-generative", "TTM operating income > 0 and TTM operating cash flow > 0",
               s, (s["ebit"] > 0) & (s["cfo"] > 0))
    solvent = ((s["net_debt"] <= 0) | (s["net_debt_ebitda"] <= C.MAX_NET_DEBT_TO_EBITDA)) & \
              (s["interest_cover"].isna() | (s["interest_cover"] >= C.MIN_INTEREST_COVERAGE) | (s["net_debt"] <= 0))
    cands = F.step("Solvent", "Net debt / EBITDA <= %.0fx (or net cash) and EBIT / interest >= %.0fx"
                   % (C.MAX_NET_DEBT_TO_EBITDA, C.MIN_INTEREST_COVERAGE), s, solvent).copy()
    if len(cands) < C.MIN_CANDIDATES and not args.limit:
        raise SystemExit(f"Only {len(cands)} candidates passed; likely a data problem, not publishing this run.")

    # ---------------------------------------------------------------- compounders screen
    G = Funnel("compounders")
    g = G.start("Common stock, market cap >= $%.1fB" % (C.COMP_MIN_MARKET_CAP / 1e9),
                "Wider net: multi-baggers usually start small or mid-sized", base)
    g = G.step("Price >= $%.0f, liquid, 1y+ history" % C.MIN_PRICE,
               "60-day median $ volume >= $%.0fM; one share class per company" % (C.COMP_MIN_DOLLAR_VOLUME / 1e6),
               g, (g["price"] >= C.MIN_PRICE) & (g["dollar_vol_60d"] >= C.COMP_MIN_DOLLAR_VOLUME)
               & (g["history_days"] >= C.MIN_PRICE_HISTORY_DAYS) & g["primary_class"])
    g = G.step("Excludes banks, insurers, asset managers and REITs", "By SEC SIC code", g, ~g["financial"])
    g = G.step("Recent US-GAAP financials in USD", "Latest period within %d days" % C.MAX_FILING_AGE_DAYS,
               g, recent.reindex(g.index))
    cg = C.COMP_GATES
    g = G.step("Sustained fast growth", "3-year revenue CAGR >= %.0f%% and TTM revenue growth >= %.0f%%"
               % (cg["min_rev_cagr_3y"] * 100, cg["min_rev_growth"] * 100),
               g, (g["rev_cagr_3y"] >= cg["min_rev_cagr_3y"]) & (g["rev_growth"] >= cg["min_rev_growth"]))
    g = G.step("Consistent, not a one-off", "Revenue up in every one of the last 3 fiscal years; operating profit in "
               "each of the last 2; operating-margin volatility <= %.0f pts (excludes commodity booms and licence "
               "windfalls)" % (cg["max_margin_volatility"] * 100),
               g, (g["rev_up_years"] == g["rev_years"]) & (g["rev_years"] >= 2) & g["ebit_pos_2y"].fillna(False).astype(bool)
               & (g["margin_volatility"] <= cg["max_margin_volatility"]))
    g = G.step("High returns on capital", "ROIC >= %.0f%%, operating income and operating cash flow > 0"
               % (cg["min_roic"] * 100), g, (g["roic"] >= cg["min_roic"]) & (g["ebit"] > 0) & (g["cfo"] > 0))
    pool = G.step("Not over-levered", "Net debt / EBITDA <= %.0fx (or net cash)" % cg["max_net_debt_ebitda"],
                  g, (g["net_debt"] <= 0) | (g["net_debt_ebitda"] <= cg["max_net_debt_ebitda"])).copy()

    # ---------------------------------------------------------------- estimates, scores, reviews
    if not args.skip_yahoo_estimates:
        need = list(dict.fromkeys(list(cands["ticker"]) + list(pool["ticker"])))
        print(f"Fetching analyst estimates for {len(need)} stocks...")
        ed = pd.DataFrame.from_dict(yahoo.enrich(need), orient="index")
        cands = cands.join(ed, on="ticker")
        pool = pool.join(ed, on="ticker")
    yahoo_cov = float(cands["eps_rev_cy_90d"].notna().mean()) if "eps_rev_cy_90d" in cands else 0.0
    cands = scoring.score(scoring.add_market_metrics(cands))
    pool = scoring.score_compounders(scoring.add_market_metrics(pool))
    for df in (cands, pool):
        df["nasdaq_sector"] = df["sector"]
        df["sector"] = df["y_sector"].fillna(df["sector"]) if "y_sector" in df else df["sector"]
        df["industry"] = df["y_industry"].fillna(df["industry"]) if "y_industry" in df else df["industry"]
    reviews = qualitative.load()
    cands = qualitative.merge(cands.sort_values("lt_score", ascending=False), reviews)
    pool = qualitative.merge(pool.sort_values("comp_score", ascending=False), reviews)
    in_core = set(cands["ticker"])
    pool["in_core"] = pool["ticker"].isin(in_core)
    cands["flag_comp"] = cands["ticker"].isin(set(pool.loc[pool["flag_comp"], "ticker"]))
    cands["comp_score"] = cands["ticker"].map(dict(zip(pool["ticker"], pool["comp_score"])))

    # ---------------------------------------------------------------- outputs
    for df, cols in ((cands, report.CANDIDATE_COLUMNS), (pool, report.COMPOUNDER_COLUMNS)):
        for c in cols:
            if c not in df:
                df[c] = np.nan
    out = cands[report.CANDIDATE_COLUMNS].copy()
    comp_out = pool[report.COMPOUNDER_COLUMNS].copy()
    out.to_csv(f"{OUT}/candidates.csv", index=False, float_format="%.6g")
    comp_out.to_csv(f"{OUT}/compounders.csv", index=False, float_format="%.6g")
    fun = pd.DataFrame(F.rows)
    comp_fun = pd.DataFrame(G.rows)
    fun.to_csv(f"{OUT}/funnel.csv", index=False)
    comp_fun.to_csv(f"{OUT}/compounders_funnel.csv", index=False)
    pd.DataFrame(F.dropped + G.dropped).to_csv(f"{OUT}/excluded.csv", index=False)
    q = qualitative.queue(cands, pool, reviews)
    q.to_csv(f"{OUT}/review_queue.csv", index=False)

    snap_cols = ["ticker", "company", "price", "lt_score", "st_score", "value_score", "comp_score",
                 "flag_lt", "flag_st", "flag_trap", "flag_comp", "conviction_label"]
    snap = pd.concat([cands.assign(in_core=True)[snap_cols + ["in_core"]],
                      pool[~pool["in_core"]].assign(flag_lt=False, flag_st=False, flag_trap=False,
                                                    lt_score=np.nan, st_score=np.nan, value_score=np.nan,
                                                    in_core=False)[snap_cols + ["in_core"]]])
    if not args.limit:  # smoke tests never enter the track record
        snap.to_csv(f"{HIST}/{today}.csv", index=False, float_format="%.6g")
    summ, det = track.build(HIST, hist)
    summ.to_csv(f"{OUT}/track_record.csv", index=False, float_format="%.6g")
    det.to_csv(f"{OUT}/track_record_detail.csv", index=False, float_format="%.6g")
    changes = report.changes_vs_previous(HIST, today, cands, pool)
    changes.to_csv(f"{OUT}/changes.csv", index=False)

    meta = dict(
        run_utc=run_at.isoformat(timespec="seconds"),
        price_date=str(cands["price_date"].max()),
        universe=len(u), candidates=len(cands),
        long_term_flags=int(cands["flag_lt"].sum()), short_term_flags=int(cands["flag_st"].sum()),
        both_flags=int((cands["flag_lt"] & cands["flag_st"]).sum()),
        value_trap_flags=int(cands["flag_trap"].sum()),
        compounder_pool=len(pool), compounder_flags=int(pool["flag_comp"].sum()),
        reviews_on_file=int(len(reviews)), review_queue=int(len(q)),
        yahoo_estimate_coverage=round(yahoo_cov, 3),
        sec_status_counts={k: int(v) for k, v in status_counts.items()},
        sources=dict(universe=uni_sources, fundamentals="SEC EDGAR XBRL companyfacts (data.sec.gov)",
                     prices_estimates="Yahoo Finance via yfinance (unofficial)",
                     qualitative="Claude research reviews (data/qualitative/reviews.json)"),
        smoke_test=bool(args.limit),
    )
    with open(f"{OUT}/meta.json", "w") as f:
        json.dump(meta, f, indent=2, default=str)
    report.write_excel(f"{OUT}/screener.xlsx", out, fun, summ, changes, meta, comp_out, comp_fun, reviews)
    report.write_dashboard_json("data/dashboard", out, fun, summ, changes, meta, comp_out, comp_fun, reviews, cands, pool)
    print(json.dumps(meta, indent=2, default=str))


if __name__ == "__main__":
    main()
