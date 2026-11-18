"""Live track record: how flagged stocks did after each daily snapshot, vs. all candidates and SPY.

Uses only snapshots this pipeline actually published (no look-ahead), and today's adjusted price
history for both ends of every return.
"""
import glob
import os

import numpy as np
import pandas as pd

HORIZONS = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}   # trading days
GROUPS = {"Long-term value": "flag_lt", "Short-term setup": "flag_st", "Value-trap risk": "flag_trap",
          "Compounder": "flag_comp", "High-conviction long-term": "hc_lt", "Both lists": "both"}


def _flag(df, col):
    if col == "hc_lt":
        return _flag(df, "flag_lt") & (df.get("conviction_label", pd.Series("", index=df.index)).astype(str) == "High")
    if col == "both":
        return _flag(df, "flag_lt") & _flag(df, "flag_st")
    if col not in df:
        return pd.Series(False, index=df.index)
    return df[col].astype(str).str.lower() == "true"


def _close_on_or_after(series, day):
    s = series[series.index >= day]
    return (s.index[0], s.iloc[0]) if len(s) else (None, None)


def build(history_dir, hist):
    """hist: {ticker: DataFrame[Close, ...]} from today's download."""
    files = sorted(glob.glob(os.path.join(history_dir, "*.csv")))
    if not files or "SPY" not in hist:
        return pd.DataFrame(), pd.DataFrame()
    closes = {t: h["Close"].astype(float) for t, h in hist.items()}
    for t, s in closes.items():
        if s.index.tz is not None:
            closes[t] = s.tz_localize(None)
    spy = closes["SPY"]
    cal = spy.index
    detail = []
    for f in files:
        snap_day = pd.Timestamp(os.path.basename(f)[:10])
        start_idx = cal.searchsorted(snap_day)
        if start_idx >= len(cal):
            continue
        snap = pd.read_csv(f)
        for hz, n in HORIZONS.items():
            # enter at the NEXT session's close: the list is published after the snapshot day's close
            if start_idx + 1 + n >= len(cal):
                continue
            d0, d1 = cal[start_idx + 1], cal[start_idx + 1 + n]
            rets = {}
            for t in snap["ticker"]:
                s = closes.get(t)
                if s is None or d0 not in s.index or d1 not in s.index:
                    continue
                rets[t] = s[d1] / s[d0] - 1
            if not rets:
                continue
            r = snap.set_index("ticker").assign(ret=pd.Series(rets)).dropna(subset=["ret"])
            core = r[_flag(r, "in_core")] if "in_core" in r else r
            bench = (core if len(core) else r)["ret"].mean()
            spy_ret = spy[d1] / spy[d0] - 1
            for gname, col in GROUPS.items():
                sub = r[_flag(r, col)]
                if sub.empty:
                    continue
                detail.append(dict(snapshot=snap_day.date().isoformat(), horizon=hz, group=gname,
                                   n=len(sub), group_return=sub["ret"].mean(),
                                   candidates_return=bench, spy_return=spy_ret,
                                   excess_vs_candidates=sub["ret"].mean() - bench,
                                   pct_names_beating_candidates=(sub["ret"] > bench).mean()))
    det = pd.DataFrame(detail)
    if det.empty:
        return det, det
    summ = det.groupby(["horizon", "group"]).agg(
        snapshots=("snapshot", "nunique"), avg_names=("n", "mean"),
        avg_group_return=("group_return", "mean"), avg_candidates_return=("candidates_return", "mean"),
        avg_spy_return=("spy_return", "mean"), avg_excess=("excess_vs_candidates", "mean"),
        snapshot_hit_rate=("excess_vs_candidates", lambda x: (x > 0).mean()),
        name_hit_rate=("pct_names_beating_candidates", "mean"),
    ).reset_index()
    order = {k: i for i, k in enumerate(HORIZONS)}
    summ = summ.sort_values(["horizon", "group"], key=lambda s: s.map(order) if s.name == "horizon" else s)
    return summ, det
