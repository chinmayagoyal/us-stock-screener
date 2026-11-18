"""Daily pipeline: universe -> initial filter -> fundamentals -> scores -> outputs.

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
from . import prices, report, scoring, sec, track, universe, yahoo

OUT = "data/latest"
HIST = "data/history"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="sample size for a smoke test")
    ap.add_argument("--skip-yahoo-estimates", action="store_true")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(HIST, exist_ok=True)
    run_at = datetime.now(timezone.utc)
    funnel = []

    def step(label, rule, before, after):
        funnel.append(dict(step=len(funnel), stage=label, rule=rule, remaining=len(after),
                           removed=len(before) - len(after)))
        print(f"[{len(funnel)-1}] {label}: {len(after)} remaining ({len(before)-len(after)} removed)")
        return after

    print("Loading universe...")
    u, uni_sources = universe.load_universe()
    funnel.append(dict(step=0, stage="All US-listed securities", rule="NYSE, Nasdaq, NYSE American listings",
                       remaining=len(u), removed=0))
    print(f"[0] universe: {len(u)}")
    s = step("Common stock only", "Drops ETFs, funds, preferreds, warrants, rights, units, notes, SPACs",
             u, u[universe.security_type_mask(u)])
    s = step("Market cap >= $%.0fB" % (C.MIN_MARKET_CAP / 1e9), "Nasdaq-reported market capitalisation",
             s, s[s["mcap_nasdaq"] >= C.MIN_MARKET_CAP])
    s = step("Excludes financials and real estate", "Banks, insurers, asset managers and REITs need book-value / FFO models",
             s, s[~s["sector"].isin(C.EXCLUDED_SECTORS)])
    if args.limit:
        s = s.sample(min(args.limit, len(s)), random_state=1)
        print(f"  smoke test: sampled {len(s)}")

    print("Downloading price history...")
    hist = prices.download_history(list(s["ticker"]) + ["SPY"])
    pm = pd.DataFrame.from_dict({t: prices.price_metrics(h) for t, h in hist.items() if t != "SPY"}, orient="index")
    s = s.join(pm, on="ticker")
    s = step("Price >= $%.0f, liquid, 1y+ history" % C.MIN_PRICE,
             "Price >= $%g; 60-day median $ volume >= $%.0fM; >= %d trading days"
             % (C.MIN_PRICE, C.MIN_DOLLAR_VOLUME / 1e6, C.MIN_PRICE_HISTORY_DAYS),
             s, s[(s["price"] >= C.MIN_PRICE) & (s["dollar_vol_60d"] >= C.MIN_DOLLAR_VOLUME)
                  & (s["history_days"] >= C.MIN_PRICE_HISTORY_DAYS)])

    print("Mapping to SEC filers...")
    cikmap = sec.ticker_to_cik()
    s = s.assign(cik=s["ticker"].str.upper().map(cikmap))
    s2 = s[s["cik"].notna()].copy()
    s2["cik"] = s2["cik"].astype(int)
    s2 = s2.sort_values("dollar_vol_60d", ascending=False).drop_duplicates("cik")
    s = step("SEC filer, one share class per company", "Ticker maps to an SEC CIK; keeps the most liquid class",
             s, s2)

    print(f"Fetching SEC fundamentals for {len(s)} companies...")
    fund = sec.fetch_all(s["cik"].tolist())
    fd = pd.DataFrame.from_dict(fund, orient="index")
    s = s.join(fd, on="cik")
    status_counts = s["sec_status"].value_counts().to_dict()
    age = (pd.Timestamp(run_at.date()) - pd.to_datetime(s["period_end"], errors="coerce")).dt.days
    s = step("Recent US-GAAP financials in USD",
             "SEC XBRL TTM rebuilt; latest period within %d days (IFRS/foreign-currency filers drop here)"
             % C.MAX_FILING_AGE_DAYS,
             s, s[(s["sec_status"] == "ok") & (age <= C.MAX_FILING_AGE_DAYS)])

    s = scoring.add_fundamental_metrics(s)
    s = step("Profitable and cash-generative", "TTM operating income > 0 and TTM operating cash flow > 0",
             s, s[(s["ebit"] > 0) & (s["cfo"] > 0)])
    solvent = ((s["net_debt"] <= 0) | (s["net_debt_ebitda"] <= C.MAX_NET_DEBT_TO_EBITDA)) & \
              (s["interest_cover"].isna() | (s["interest_cover"] >= C.MIN_INTEREST_COVERAGE) | (s["net_debt"] <= 0))
    s = step("Solvent", "Net debt / EBITDA <= %.0fx (or net cash) and EBIT / interest >= %.0fx"
             % (C.MAX_NET_DEBT_TO_EBITDA, C.MIN_INTEREST_COVERAGE), s, s[solvent])
    cands = s.copy()

    if not args.skip_yahoo_estimates:
        print(f"Fetching analyst estimates for {len(cands)} candidates...")
        est = yahoo.enrich(cands["ticker"].tolist())
        ed = pd.DataFrame.from_dict(est, orient="index")
        cands = cands.join(ed, on="ticker")
    yahoo_cov = float(cands["eps_rev_cy_90d"].notna().mean()) if "eps_rev_cy_90d" in cands else 0.0
    cands = scoring.add_market_metrics(cands)
    cands = scoring.score(cands)
    cands["company"] = cands["name"].str.replace(r"\s+(Common Stock|Common Shares|Class [A-C] (Common Stock|Common Shares|Ordinary Shares)|Ordinary Shares|American Depositary Shares)\b.*$", "", regex=True)
    cands["nasdaq_sector"] = cands["sector"]
    cands["sector"] = cands["rank_group"]
    cands["industry"] = cands["y_industry"].fillna(cands["industry"]) if "y_industry" in cands else cands["industry"]
    cands = cands.sort_values("lt_score", ascending=False)

    # ---------------------------------------------------------------- outputs
    today = run_at.strftime("%Y-%m-%d")
    cols = report.CANDIDATE_COLUMNS
    for c in cols:
        if c not in cands:
            cands[c] = np.nan
    out = cands[cols].copy()
    out.to_csv(f"{OUT}/candidates.csv", index=False, float_format="%.6g")
    fun = pd.DataFrame(funnel)
    fun.to_csv(f"{OUT}/funnel.csv", index=False)

    snap = cands[["ticker", "company", "price", "lt_score", "st_score", "value_score",
                  "flag_lt", "flag_st", "flag_trap"]]
    if not args.limit:  # smoke tests never enter the track record
        snap.to_csv(f"{HIST}/{today}.csv", index=False, float_format="%.6g")
    summ, det = track.build(HIST, hist)
    summ.to_csv(f"{OUT}/track_record.csv", index=False, float_format="%.6g")
    det.to_csv(f"{OUT}/track_record_detail.csv", index=False, float_format="%.6g")

    changes = report.changes_vs_previous(HIST, today, cands)
    changes.to_csv(f"{OUT}/changes.csv", index=False)

    meta = dict(
        run_utc=run_at.isoformat(timespec="seconds"),
        price_date=str(cands["price_date"].max()),
        universe=len(u), candidates=len(cands),
        long_term_flags=int(cands["flag_lt"].sum()), short_term_flags=int(cands["flag_st"].sum()),
        both_flags=int((cands["flag_lt"] & cands["flag_st"]).sum()),
        value_trap_flags=int(cands["flag_trap"].sum()),
        yahoo_estimate_coverage=round(yahoo_cov, 3),
        sec_status_counts={k: int(v) for k, v in status_counts.items()},
        sources=dict(universe=uni_sources, fundamentals="SEC EDGAR XBRL companyfacts (data.sec.gov)",
                     prices_estimates="Yahoo Finance via yfinance (unofficial)"),
        smoke_test=bool(args.limit),
    )
    with open(f"{OUT}/meta.json", "w") as f:
        json.dump(meta, f, indent=2, default=str)
    report.write_excel(f"{OUT}/screener.xlsx", out, fun, summ, changes, meta)
    report.write_dashboard_json("data/dashboard", out, fun, summ, changes, meta)
    print(json.dumps(meta, indent=2, default=str))


if __name__ == "__main__":
    main()
