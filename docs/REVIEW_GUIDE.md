# Qualitative review guide

The reviewer (a scheduled Claude task) follows this guide so that scores stay consistent across stocks and over time.

## What to review

`data/latest/review_queue.csv` lists the stocks on the Long-term value, Both and Compounder lists that have no review yet, or whose review is older than 120 days. It is sorted by priority, highest first. Review from the top.

## How to research (per stock, about 3–5 lookups)

1. The latest 10-K, Item 1 (Business) and Item 1A (Risk factors). Read them on sec.gov or in a reliable summary.
2. The latest earnings release and call highlights: growth drivers, guidance, management's own view of competition.
3. One or two independent views on competition and industry structure: trade press or analyst commentary.
4. Anything material in the last 90 days: M&A, management change, litigation, regulation.

Use only what you found. Every review lists 2–5 source URLs.

## Rubric: score 1–5, where 5 is always the better outcome for an investor

| Factor | 5 | 3 | 1 |
|---|---|---|---|
| **moat** | Durable advantage: switching costs, network effects, scale cost lead, brand or licence, visible in a decade of high ROIC | Some advantage, but contestable | Commodity; no pricing power |
| **disruption** (risk; 5 = low) | Product hard to substitute; tech shifts help it | Real but slow-moving threat | Core product being made obsolete now |
| **industry** | Consolidated, rational pricing, high barriers | Moderate competition | Fragmented, price wars, new capacity flooding in |
| **demand** | Strong multi-year secular tailwind | GDP-like growth | Structural decline |
| **management** | Owner-like, disciplined capital allocation, candid, good record | Adequate | Value-destructive M&A, dilution, poor disclosure |
| **tail_risk** (5 = few) | Net cash; diversified customers; no major legal or regulatory overhang | Some exposure | Refinancing, litigation, concentration or regulatory risk that could impair the equity |
| **catalyst** | Clear, dated event likely within 6–12 months | Possible catalyst, timing unclear | None visible |

Score against the whole market, not just the stock's own industry. A cyclical earnings peak should show up in `demand` and `tail_risk`.

## Conviction

Computed by the pipeline, not by the reviewer: moat 25%, disruption 20%, demand 15%, management 15%, tail risk 15%, industry 10%. High ≥ 3.75, Medium ≥ 3.0, Low < 3.0. The catalyst score is shown separately; it matters for timing, not conviction.

## Format

Append to `data/qualitative/reviews.json` (a JSON list). Never edit or delete earlier reviews; the newest review per ticker wins.

```json
{
  "ticker": "XYZ", "company": "XYZ Corp", "review_date": "YYYY-MM-DD", "reviewer": "Claude",
  "scores": {"moat": 4, "disruption": 3, "industry": 3, "demand": 4, "management": 4, "tail_risk": 4, "catalyst": 3},
  "reasons": {"moat": "one line", "disruption": "...", "industry": "...", "demand": "...",
              "management": "...", "tail_risk": "...", "catalyst": "..."},
  "bull_case": "one or two sentences", "bear_case": "one or two sentences",
  "key_risk": "one line", "catalyst_note": "one line",
  "sources": ["https://...", "https://..."]
}
```

Write reasons in your own words. Never paste text from sources. These reviews describe a business and are not investment advice.
