"""Universe of every US-listed security (NYSE, Nasdaq, NYSE American) and the security-type filter."""
import io
import re
import time

import pandas as pd
import requests

NASDAQ_API = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true&exchange={ex}"
MIRROR = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/{ex}/{ex}_full_tickers.json"
NASDAQ_TRADED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}

# names that are not ordinary common equity
NON_COMMON = re.compile(
    r"\b(?:warrants?|rights?|units?|preferred|pref\.?|notes? due|debentures?|subordinated|"
    r"depositary shares,? each representing a 1/|perpetual|baby bond|contingent value)\b|%",
    re.I,
)
SPAC = re.compile(r"\b(?:acquisition corp|acquisition co\b|blank check|capital acquisition)", re.I)


def _num(x):
    if x is None:
        return None
    s = str(x).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _fetch_exchange(ex):
    for attempt in range(3):
        try:
            r = requests.get(NASDAQ_API.format(ex=ex), headers=BROWSER_HEADERS, timeout=60)
            r.raise_for_status()
            rows = r.json()["data"]["rows"]
            if rows:
                return rows, "nasdaq.com screener API"
        except Exception as e:  # noqa: BLE001
            print(f"  nasdaq api {ex} attempt {attempt+1} failed: {e}")
            time.sleep(3)
    r = requests.get(MIRROR.format(ex=ex), timeout=60)
    r.raise_for_status()
    return r.json(), "rreichel3/US-Stock-Symbols mirror"


def load_universe():
    frames, sources = [], set()
    for ex, label in [("nasdaq", "NASDAQ"), ("nyse", "NYSE"), ("amex", "NYSE American")]:
        rows, src = _fetch_exchange(ex)
        sources.add(src)
        df = pd.DataFrame(rows)
        df["exchange"] = label
        frames.append(df)
    u = pd.concat(frames, ignore_index=True)
    u["symbol"] = u["symbol"].astype(str).str.strip()
    u = u[u["symbol"] != ""].drop_duplicates("symbol")
    u["price_nasdaq"] = u["lastsale"].map(_num)
    u["mcap_nasdaq"] = u["marketCap"].map(_num)
    u["sector"] = u["sector"].fillna("").replace("", "Unclassified")
    u["industry"] = u["industry"].fillna("")
    u["country"] = u["country"].fillna("")

    # ETF / test-issue flags from Nasdaq Trader (best effort)
    etf = set()
    try:
        t = requests.get(NASDAQ_TRADED, headers=BROWSER_HEADERS, timeout=60).text
        nt = pd.read_csv(io.StringIO(t), sep="|", dtype=str)
        nt = nt[nt["Symbol"].notna()]
        bad = nt[(nt.get("ETF") == "Y") | (nt.get("Test Issue") == "Y")]
        etf = set(bad["Symbol"].str.replace(".", "/", regex=False)) | set(bad["Symbol"])
    except Exception as e:  # noqa: BLE001
        print(f"  nasdaqtraded.txt unavailable ({e}); relying on name rules only")
    u["is_etf"] = u["symbol"].isin(etf)
    # Yahoo / SEC style ticker: BRK/B -> BRK-B
    u["ticker"] = u["symbol"].str.replace("/", "-", regex=False)
    return u.reset_index(drop=True), sorted(sources)


def security_type_mask(u):
    """True for ordinary common stock / ADS of operating companies."""
    name = u["name"].fillna("")
    pref = u["symbol"].str.contains(r"\^", regex=True)
    non_common = name.str.contains(NON_COMMON)
    spac = name.str.contains(SPAC) | u["industry"].str.contains("Blank Check", case=False)
    return ~(pref | non_common | spac | u["is_etf"])
