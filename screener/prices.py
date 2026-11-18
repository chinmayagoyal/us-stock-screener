"""Daily price history from Yahoo Finance (via yfinance) and the price-based metrics."""
import time

import numpy as np
import pandas as pd
import yfinance as yf


def download_history(tickers, period="15mo", chunk=150):
    """Return {ticker: DataFrame[Close, Volume]} of split/dividend-adjusted daily bars."""
    out = {}
    tickers = list(dict.fromkeys(tickers))
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        for attempt in range(3):
            try:
                df = yf.download(batch, period=period, interval="1d", auto_adjust=True,
                                 group_by="ticker", threads=True, progress=False, timeout=30)
                break
            except Exception as e:  # noqa: BLE001
                print(f"  price batch {i} attempt {attempt+1} failed: {e}")
                time.sleep(10 * (attempt + 1))
        else:
            continue
        for t in batch:
            try:
                sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                sub = sub[["Close", "Volume"]].dropna(subset=["Close"])
                if len(sub):
                    out[t] = sub
            except KeyError:
                pass
        print(f"  prices: {min(i+chunk, len(tickers))}/{len(tickers)} requested, {len(out)} with data")
        time.sleep(1.5)
    missing = [t for t in tickers if t not in out]
    if missing:  # second pass, single-threaded (avoids yfinance cache-lock errors)
        print(f"  retrying {len(missing)} tickers without threads")
        for t in missing:
            try:
                sub = yf.download(t, period=period, interval="1d", auto_adjust=True, threads=False,
                                  progress=False, timeout=30, multi_level_index=False)
                sub = sub[["Close", "Volume"]].dropna(subset=["Close"])
                if len(sub):
                    out[t] = sub
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.3)
    return out


def price_metrics(hist):
    """hist: DataFrame[Close, Volume] -> dict of metrics."""
    c = hist["Close"].astype(float)
    v = hist["Volume"].astype(float)
    n = len(c)
    m = {"price": c.iloc[-1], "price_date": c.index[-1].strftime("%Y-%m-%d"), "history_days": n}
    dv = (c * v).tail(60)
    m["dollar_vol_60d"] = float(dv.median()) if len(dv) else np.nan

    def ret(a, b):  # return from b trading days ago to a trading days ago
        if n > b:
            return c.iloc[-1 - a] / c.iloc[-1 - b] - 1
        return np.nan

    m["ret_1m"] = ret(0, 21)
    m["ret_3m"] = ret(0, 63)
    m["ret_6_1"] = ret(21, 126)
    m["ret_12_1"] = ret(21, 252)
    m["ret_12m"] = ret(0, 252)
    m["px_vs_200d"] = c.iloc[-1] / c.tail(200).mean() - 1 if n >= 200 else np.nan
    m["px_vs_50d"] = c.iloc[-1] / c.tail(50).mean() - 1 if n >= 50 else np.nan
    hi = c.tail(252).max()
    m["pct_off_52w_high"] = c.iloc[-1] / hi - 1 if hi else np.nan
    r = c.pct_change().tail(63)
    m["vol_3m"] = float(r.std() * np.sqrt(252)) if len(r) > 20 else np.nan
    return m
