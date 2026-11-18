"""Analyst estimates, revisions, surprises, short interest and insider activity from Yahoo Finance.

One quoteSummary request per candidate. Every field is optional: if Yahoo throttles or a field is
missing, the scores simply re-weight over the metrics that are available.
"""
import time
from datetime import datetime, timezone

import yfinance as yf

from . import config

MODULES = ["financialData", "defaultKeyStatistics", "summaryDetail", "assetProfile", "earningsTrend",
           "earningsHistory", "netSharePurchaseActivity", "calendarEvents"]


def _raw(v):
    if isinstance(v, dict):
        return v.get("raw")
    return v


def _pct_change(now, then):
    now, then = _raw(now), _raw(then)
    if now is None or then is None or then == 0:
        return None
    return (now - then) / abs(then)


def _fetch(sym):
    t = yf.Ticker(sym)
    data = t._analysis._fetch(MODULES)  # noqa: SLF001 - single request for all modules
    return data["quoteSummary"]["result"][0]


def parse(res):
    o = {}
    fd = res.get("financialData", {}) or {}
    ks = res.get("defaultKeyStatistics", {}) or {}
    sd = res.get("summaryDetail", {}) or {}
    ap = res.get("assetProfile", {}) or {}
    o["y_sector"] = ap.get("sector")
    o["y_industry"] = ap.get("industry")
    o["target_mean"] = _raw(fd.get("targetMeanPrice"))
    o["recommendation_mean"] = _raw(fd.get("recommendationMean"))
    o["n_analysts"] = _raw(fd.get("numberOfAnalystOpinions"))
    o["forward_eps"] = _raw(ks.get("forwardEps"))
    o["forward_pe"] = _raw(sd.get("forwardPE"))
    o["short_pct_float"] = _raw(ks.get("shortPercentOfFloat"))
    o["insider_own"] = _raw(ks.get("heldPercentInsiders"))
    o["dividend_yield"] = _raw(sd.get("dividendYield"))

    for item in (res.get("earningsTrend", {}) or {}).get("trend", []):
        per = item.get("period")
        key = {"0y": "cy", "+1y": "ny"}.get(per)
        if not key:
            continue
        tr = item.get("epsTrend", {}) or {}
        o[f"eps_est_{key}"] = _raw(tr.get("current"))
        o[f"eps_rev_{key}_30d"] = _pct_change(tr.get("current"), tr.get("30daysAgo"))
        o[f"eps_rev_{key}_90d"] = _pct_change(tr.get("current"), tr.get("90daysAgo"))
        if key == "cy":
            rv = item.get("epsRevisions", {}) or {}
            up, dn = _raw(rv.get("upLast30days")), _raw(rv.get("downLast30days"))
            n = _raw((item.get("earningsEstimate", {}) or {}).get("numberOfAnalysts"))
            if up is not None and dn is not None and n:
                o["rev_breadth_30d"] = (up - dn) / n

    hist = (res.get("earningsHistory", {}) or {}).get("history", [])
    hist = sorted(hist, key=lambda h: _raw(h.get("quarter")) or 0)  # oldest -> newest
    surprises = []
    for h in hist:
        a, e = _raw(h.get("epsActual")), _raw(h.get("epsEstimate"))
        if a is not None and e not in (None, 0):
            surprises.append((a - e) / abs(e))
    if surprises:
        o["eps_surprise_last"] = surprises[-1]
        o["eps_surprise_avg"] = sum(surprises) / len(surprises)

    ns = res.get("netSharePurchaseActivity", {}) or {}
    o["insider_net_pct"] = _raw(ns.get("netPercentInsiderShares"))

    ed = ((res.get("calendarEvents", {}) or {}).get("earnings", {}) or {}).get("earningsDate", [])
    ed = [_raw(x) for x in ed if _raw(x)]
    if ed:
        o["next_earnings"] = datetime.fromtimestamp(min(ed), tz=timezone.utc).strftime("%Y-%m-%d")
    return o


def enrich(tickers):
    out, fails = {}, 0
    for i, t in enumerate(tickers, 1):
        for attempt in range(3):
            try:
                out[t] = parse(_fetch(t))
                break
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "Too Many Requests" in msg or "Rate" in msg:
                    time.sleep(30 * (attempt + 1))
                else:
                    time.sleep(1)
        else:
            fails += 1
        time.sleep(config.YAHOO_PAUSE_SEC)
        if i % 100 == 0:
            print(f"  Yahoo estimates: {i}/{len(tickers)} ({fails} failed)")
    return out
