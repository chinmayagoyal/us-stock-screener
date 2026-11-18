"""All tunable thresholds and weights live here. Change a number, push, and the next run uses it."""

# ---------------------------------------------------------------- initial filter
MIN_MARKET_CAP = 2_000_000_000      # $2B: mid-cap and above
MIN_PRICE = 5.0                     # avoid penny-stock microstructure
MIN_DOLLAR_VOLUME = 10_000_000      # 60-day median daily $ volume
MIN_PRICE_HISTORY_DAYS = 250        # ~1 year of trading, needed for momentum + TTM comparisons
EXCLUDED_SECTORS = {"Finance", "Real Estate"}   # banks/insurers/REITs need P/B, P/TBV, P/FFO models
MAX_FILING_AGE_DAYS = 200           # latest reported period must be this recent
MAX_NET_DEBT_TO_EBITDA = 4.0        # solvency gate (net cash always passes)
MIN_INTEREST_COVERAGE = 3.0         # EBIT / interest expense, applied when interest is reported

# ---------------------------------------------------------------- scoring
SECTOR_WEIGHT = 0.7                 # blend of sector-relative vs market-wide percentile ranks
MIN_SECTOR_SIZE = 8                 # smaller sectors are ranked market-wide only
COST_OF_EQUITY = 0.09               # used for market-implied FCF growth (reverse DCF)
TAX_RATE = 0.21

# metric -> direction (+1 higher is better, -1 lower is better)
VALUE_METRICS = {
    "ebit_ev": 1,          # EBIT / enterprise value (earnings yield, Greenblatt)
    "fcf_yield": 1,        # free cash flow / market cap
    "earnings_yield": 1,   # net income / market cap (inverse P/E)
    "fwd_earnings_yield": 1,  # forward EPS / price (inverse forward P/E)
    "shareholder_yield": 1,   # (dividends + buybacks) / market cap
    "sales_ev": 1,         # revenue / EV (inverse EV/Sales)
}
QUALITY_METRICS = {
    "roic": 1,             # after-tax EBIT / invested capital
    "gp_assets": 1,        # gross profit / assets (Novy-Marx)
    "fscore": 1,           # Piotroski F-score 0-9
    "accruals": -1,        # (net income - CFO) / assets: lower = cash-backed earnings
    "net_debt_ebitda": -1,
    "rev_growth": 1,       # TTM revenue YoY
}
MOMENTUM_METRICS = {
    "ret_12_1": 1,         # 12-month return skipping the latest month
    "ret_6_1": 1,          # 6-month return skipping the latest month
    "px_vs_200d": 1,       # price vs 200-day average
}
REVISION_METRICS = {
    "eps_rev_cy_90d": 1,   # % change in current-FY consensus EPS over 90 days
    "eps_rev_ny_90d": 1,   # % change in next-FY consensus EPS over 90 days
    "eps_surprise_avg": 1, # average EPS surprise, last 4 quarters
    "rev_breadth_30d": 1,  # (up - down) estimate revisions over 30 days / analysts
}
SENTIMENT_METRICS = {
    "short_pct_float": -1, # heavily shorted names tend to underperform
    "insider_net_pct": 1,  # net insider buying, last 6 months
}

LT_WEIGHTS = {"value": 0.60, "quality": 0.40}
ST_WEIGHTS = {"momentum": 0.35, "revisions": 0.30, "value": 0.20, "sentiment": 0.15}

# ---------------------------------------------------------------- flags
LT_FLAG = dict(min_lt_score=90, min_value=70, min_fscore=5)
ST_FLAG = dict(min_st_score=90, min_value=40, min_revisions=50)
TRAP_FLAG = dict(min_value=80, max_quality=30)

# ---------------------------------------------------------------- data sources
SEC_RATE_PER_SEC = 8                # SEC fair-access limit is 10/s
YAHOO_PAUSE_SEC = 0.35              # politeness pause between quote-summary calls
