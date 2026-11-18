"""Debug helper: python -m screener.diag TICKER [TICKER...] prints SEC tags and rebuilt fundamentals."""
import json
import re
import sys

import requests

from . import sec

PAT = re.compile(r"(Debt|Borrowing|NotesPayable|Notes|Lease|Cash|Investments|Securities|Marketable|Equity$|OperatingIncome|CommercialPaper)", re.I)


def main():
    cik = sec.ticker_to_cik()
    s = requests.Session()
    s.headers["User-Agent"] = sec._ua()
    for t in sys.argv[1:]:
        c = cik.get(t.upper())
        print("=" * 30, t, c)
        if not c:
            continue
        j = s.get(sec.FACTS_URL.format(cik=c), timeout=60).json()
        g = j["facts"].get("us-gaap", {})
        rows = []
        for tag, node in g.items():
            if not PAT.search(tag):
                continue
            for unit, facts in node.get("units", {}).items():
                inst = [f for f in facts if "start" not in f]
                if not inst:
                    continue
                last = max(inst, key=lambda f: (f["end"], f.get("filed", "")))
                if last["end"] >= "2025-06-01":
                    rows.append((last["end"], tag, unit, last["val"]))
        for r in sorted(rows, key=lambda r: (r[0], r[1]))[-60:]:
            print(f"  {r[0]} {r[1]:<75} {r[2]:<5} {r[3]:>18,.0f}")
        for tag in ["NetIncomeLoss", "ProfitLoss", "NetCashProvidedByUsedInOperatingActivities",
                    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]:
            fs = [x for x in g.get(tag, {}).get("units", {}).get("USD", []) if "start" in x and x["end"] >= "2024-09-01"]
            for x in sorted(fs, key=lambda x: (x["end"], x["start"])):
                print(f"  D {tag[:40]:<40} {x['start']} {x['end']} {x.get('form')} {x.get('filed')} {x['val']:,.0f}")
        f = sec.fundamentals(j)
        print(json.dumps({k: f.get(k) for k in ["sec_status", "period_end", "revenue", "ebit", "net_income", "cfo",
                                                 "capex", "da", "cash", "debt", "lt_debt", "equity", "interest"]},
                         default=str))


if __name__ == "__main__":
    main()
