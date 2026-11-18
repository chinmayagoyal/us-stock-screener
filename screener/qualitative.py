"""Qualitative reviews: load, score conviction, and build the review queue.

Reviews live in data/qualitative/reviews.json (a list, newest appended last). Each review:
{
  "ticker": "MPC", "company": "Marathon Petroleum", "review_date": "2026-11-18", "reviewer": "Claude",
  "scores": {"moat": 1-5, "disruption": 1-5, "industry": 1-5, "demand": 1-5, "management": 1-5,
             "tail_risk": 1-5, "catalyst": 1-5},          # 5 = best (e.g. disruption 5 = very low risk)
  "reasons": {"moat": "...", ...},                        # one line each
  "bull_case": "...", "bear_case": "...", "key_risk": "...", "catalyst_note": "...",
  "sources": ["https://...", ...]
}
"""
import json
import os
from datetime import date

import pandas as pd

from . import config as C

PATH = "data/qualitative/reviews.json"
RUBRIC = ["moat", "disruption", "industry", "demand", "management", "tail_risk", "catalyst"]


def load(path=PATH):
    if not os.path.exists(path):
        return pd.DataFrame(columns=["ticker"])
    with open(path) as f:
        reviews = json.load(f)
    rows = []
    for r in reviews:
        sc = r.get("scores", {}) or {}
        row = {"ticker": r.get("ticker"), "review_date": r.get("review_date"),
               "bull_case": r.get("bull_case"), "bear_case": r.get("bear_case"),
               "key_risk": r.get("key_risk"), "catalyst_note": r.get("catalyst_note"),
               "review_sources": " ".join(r.get("sources", []) or [])}
        for k in RUBRIC:
            row[f"q_{k}"] = sc.get(k)
        w = {k: v for k, v in C.QUAL_WEIGHTS.items() if isinstance(sc.get(k), (int, float))}
        row["conviction"] = (sum(sc[k] * v for k, v in w.items()) / sum(w.values())) if len(w) >= 4 else None
        rows.append(row)
    df = pd.DataFrame(rows).dropna(subset=["ticker"])
    df = df.sort_values("review_date").drop_duplicates("ticker", keep="last")
    df["conviction_label"] = pd.cut(df["conviction"], [0, 3.0, 3.75, 5.01], right=False,
                                    labels=["Low", "Medium", "High"]).astype(str).replace("nan", "")
    age = (pd.Timestamp(date.today()) - pd.to_datetime(df["review_date"], errors="coerce")).dt.days
    df["review_stale"] = age > C.REVIEW_MAX_AGE_DAYS
    return df


def merge(frame, reviews):
    if reviews.empty:
        for c in ["conviction", "conviction_label", "review_date"]:
            frame[c] = None
        return frame
    return frame.merge(reviews, on="ticker", how="left")


def queue(cands, pool, reviews):
    """Names on the long-term / compounder lists without a fresh review, highest priority first."""
    reviewed = {} if reviews.empty else dict(zip(reviews["ticker"], reviews["review_stale"]))
    rows = []
    lt = cands[cands["flag_lt"]].copy()
    lt["list"] = lt.apply(lambda r: "Both" if r["flag_st"] else "Long-term value", axis=1)
    lt["priority_score"] = lt["lt_score"] + lt["flag_st"].astype(int) * 100
    comp = pool[pool["flag_comp"]].copy()
    comp["list"] = "Compounder"
    comp["priority_score"] = comp["comp_score"]
    for df in (lt, comp):
        for _, r in df.iterrows():
            t = r["ticker"]
            if t in reviewed and not reviewed[t]:
                continue
            rows.append(dict(ticker=t, company=r.get("company"), list=r["list"],
                             reason="stale review" if t in reviewed else "never reviewed",
                             priority_score=r["priority_score"]))
    q = pd.DataFrame(rows, columns=["ticker", "company", "list", "reason", "priority_score"])
    q = q.sort_values("priority_score", ascending=False).drop_duplicates("ticker")
    return q
