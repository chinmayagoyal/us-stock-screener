# US stock screener: weekly undervaluation tracker

Every Friday after the US close, a GitHub Action:

1. Loads every US-listed security (NYSE, Nasdaq, NYSE American: about 7,300).
2. Applies the **initial filter** (investable, profitable, solvent).
3. Rebuilds trailing-12-month fundamentals for survivors from **SEC EDGAR XBRL**.
4. Pulls prices, analyst estimates, revisions, surprises and short interest from **Yahoo Finance**.
5. Scores every candidate for **long-term undervaluation** (1–3 years) and **short-term setups** (1–6 months).
   A separate **compounders** screen runs on a wider universe ($500M+). It looks for fast, consistent growth with high returns on capital.
   Each stock's latest **qualitative review** (`data/qualitative/reviews.json`) is merged in as a conviction score.
6. Commits the results to `data/latest/` and a weekly snapshot to `data/history/`. The snapshots feed a live track record.

## Tracker page

A Claude dashboard (https://claude.ai/artifact/HFxjifrsRpJuFUC4TzJ6zh) shows the lists, the filter funnel, a value-vs-quality map and the track record. A scheduled Claude task reloads it every Saturday at 06:55 IST from `data/dashboard/*.json`. The page source is in `dashboard/index.html` for reference.

## Outputs (`data/latest/`)

| File | What it holds |
|---|---|
| `candidates.csv` | Every stock that passed the filter, with ~60 metrics, composite scores and flags |
| `screener.xlsx` | The same as a workbook: Read me, Long-term value, Short-term setups, All candidates, Changes, Filter funnel, Track record |
| `funnel.csv` | How many stocks each filter step removed |
| `changes.csv` | Names added to or dropped from each list since the previous run |
| `track_record.csv` | Forward returns of past flagged lists vs. all candidates and SPY (fills in over time) |
| `compounders.csv` / `compounders_funnel.csv` | The compounder pool, its scores and its filter funnel |
| `review_queue.csv` | Listed stocks that still need a qualitative review, highest priority first |
| `excluded.csv` | Every stock that failed the filter and the step it failed at |
| `meta.json` | Run time, price date, counts, data coverage |

## Qualitative reviews

A scheduled Claude task runs every Friday at 13:17 IST, before that night's screen. It researches up to 20 names from `review_queue.csv` and appends reviews to `data/qualitative/reviews.json`, following `docs/REVIEW_GUIDE.md`. You can also add or override reviews yourself: append a newer review for the ticker, and the newest one per ticker wins.

## Method

See the **Read me** sheet in `screener.xlsx`. Every threshold and weight is in `screener/config.py`.

## Running by hand

Actions → *Weekly stock screen* → *Run workflow*. Set `limit` to e.g. `60` for a quick smoke test. A smoke test writes `data/latest/` but never enters the track record.

## Caveats

Not investment advice. XBRL tagging varies between companies, so a few fundamentals will be wrong. Yahoo Finance data is unofficial and can be incomplete. Check any name against its filings before acting.
