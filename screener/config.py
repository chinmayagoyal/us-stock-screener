"""All tunable thresholds and weights live here. Change a number, push, and the next run uses it."""

# ---------------------------------------------------------------- initial filter
MIN_MARKET_CAP = 2_000_000_000      # $2B: mid-cap and above
MIN_PRICE = 5.0                     # avoid penny-stock microstructure
MIN_DOLLAR_VOLUME = 10_000_000      # 60-day median daily $ volume
MIN_PRICE_HISTORY_DAYS = 250        # ~1 year of trading, needed for momentum + TTM comparisons
# Banks, lenders, brokers, asset managers, insurers and REITs are excluded by SEC SIC code (sec.is_financial_sic):
# they need P/B, P/TBV or P/FFO models. Exchanges, ratings/data firms and real-estate services stay in.
MAX_FILING_AGE_DAYS = 200           # latest reported period must be this recent
MAX_NET_DEBT_TO_EBITDA = 4.0        # solvency gate (net cash always passes)
MIN_INTEREST_COVERAGE = 3.0         # EBIT / interest expense, applied when interest is reported

# ---------------------------------------------------------------- scoring
# Share of each metric's percentile that is sector-relative (the rest is market-wide).
# Value works best within industries; momentum and revisions keep their industry component.
SECTOR_WEIGHTS = {"value": 0.7, "quality": 0.5, "momentum": 0.2, "revisions": 0.3, "sentiment": 0.3}
MIN_SECTOR_SIZE = 8                 # smaller sectors are ranked market-wide only
COST_OF_EQUITY = 0.09               # used for market-implied FCF growth (reverse DCF)
TAX_RATE = 0.21

# metric -> direction (+1 higher is better, -1 lower is better)
VALUE_METRICS = {
    "ebit_ev_norm": 1,     # cycle-adjusted EBIT (avg of TTM + last 3 fiscal years) / EV
    "fcf_yield": 1,        # (operating cash flow - capex - stock comp) / market cap
    "fwd_earnings_yield": 1,  # forward EPS / price (inverse forward P/E)
    "shareholder_yield": 1,   # dividend yield + net share-count reduction
}
QUALITY_METRICS = {
    "roic": 1,             # after-tax EBIT / invested capital
    "gp_assets": 1,        # gross profit / assets (Novy-Marx)
    "fscore": 1,           # Piotroski F-score 0-9
    "accruals": -1,        # (net income - CFO) / assets: lower = cash-backed earnings
    "net_debt_ebitda": -1,
    "margin_volatility": -1,  # std. dev. of annual operating margin (lower = steadier business)
    "roic_trend": 1,       # change in ROIC over the last 2 fiscal years (improving moat/efficiency)
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
    "eps_surprise_last": 1,  # latest quarter's EPS surprise (post-earnings drift)
    "eps_surprise_avg": 1, # average EPS surprise, last 4 quarters
    "rev_breadth_30d": 1,  # (up - down) estimate revisions over 30 days / analysts
}
SENTIMENT_METRICS = {
    "short_pct_float": -1, # heavily shorted names tend to underperform
    "insider_net_pct": 1,  # net insider buying, last 6 months
    "insider_own": 1,      # insider ownership (alignment)
}

LT_WEIGHTS = {"value": 0.60, "quality": 0.40}
ST_WEIGHTS = {"momentum": 0.35, "revisions": 0.30, "value": 0.20, "sentiment": 0.15}

# ---------------------------------------------------------------- flags
LT_FLAG = dict(min_lt_score=90, min_value=70, min_fscore=5,
               max_implied_growth=0.05)   # absolute check: price implies <= 5% perpetual owner-FCF growth
ST_FLAG = dict(min_st_score=90, min_value=40, min_revisions=50)
TRAP_FLAG = dict(min_value=80, max_quality=30, max_momentum=20, max_revisions=30)
MAX_PER_INDUSTRY = 4                # diversification cap on each flagged list
MIN_CANDIDATES = 300                # data-quality guard: fail the run rather than publish a broken list
MIN_PRICE_COVERAGE = 0.8

# ---------------------------------------------------------------- data sources
SEC_RATE_PER_SEC = 8                # SEC fair-access limit is 10/s
YAHOO_PAUSE_SEC = 0.35              # politeness pause between quote-summary calls

# ---------------------------------------------------------------- compounders / high-potential screen
COMP_MIN_MARKET_CAP = 500_000_000   # wider net: multi-baggers usually start small or mid-sized
COMP_MIN_DOLLAR_VOLUME = 3_000_000
COMP_GATES = dict(min_rev_cagr_3y=0.15, min_rev_growth=0.10, min_roic=0.12, max_net_debt_ebitda=3.0,
                  max_margin_volatility=0.12)   # excludes commodity booms and one-off licence windfalls
COMP_METRICS = {
    "growth": {"rev_cagr_3y": 1, "rev_growth": 1, "gm_trend": 1},
    "returns": {"roic": 1, "roic_trend": 1, "reinvestment_rate": 1, "margin_volatility": -1},
    "valuation": {"ev_ebit_per_growth": -1, "fcf_yield": 1},
    "alignment": {"insider_own": 1, "market_cap": -1},      # owner-operators; smaller-cap tilt
}
COMP_WEIGHTS = {"growth": 0.35, "returns": 0.30, "valuation": 0.20, "alignment": 0.15}
COMP_FLAG_TOP = 25                  # flag the top N by compounder score (max MAX_PER_INDUSTRY per industry)

# ---------------------------------------------------------------- qualitative reviews (data/qualitative/reviews.json)
QUAL_WEIGHTS = {"moat": 0.25, "disruption": 0.20, "demand": 0.15, "management": 0.15, "tail_risk": 0.15,
                "industry": 0.10}   # catalyst is shown separately; it matters for timing, not conviction
REVIEW_MAX_AGE_DAYS = 120
