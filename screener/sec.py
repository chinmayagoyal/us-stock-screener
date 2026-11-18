"""Fundamentals from SEC EDGAR XBRL 'companyfacts' (official, free, US-GAAP filers).

For each company we rebuild trailing-twelve-month (TTM) flows and latest balance-sheet values,
plus the same figures one year earlier (for growth and the Piotroski F-score).
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import requests

from . import config

TICKER_MAP = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def _ua():
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in ua:
        raise SystemExit("SEC requires a contact email in the User-Agent: add a repository secret "
                         "SEC_CONTACT_EMAIL (Settings > Secrets and variables > Actions).")
    return ua


# ------------------------------------------------------------------ tags (first = preferred)
T = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet",
                "RevenuesNetOfInterestExpense", "OperatingRevenue"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices"],
    "gross_profit": ["GrossProfit"],
    "ebit": ["OperatingIncomeLoss"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "interest": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
                 "InterestPaidNet", "InterestExpenseNet"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
           "Depreciation"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsForCapitalImprovements", "PaymentsToAcquireOtherPropertyPlantAndEquipment"],
    "dividends": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "wdil": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    # instants
    "assets": ["Assets"],
    "cur_assets": ["AssetsCurrent"],
    "cur_liab": ["LiabilitiesCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"],
    "sti": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "OtherShortTermInvestments", "DebtSecuritiesCurrent",
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "debt_combined": ["DebtLongtermAndShorttermCombinedAmount"],
    "ltd_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
                       "LongTermDebtAndFinanceLeaseObligationsNoncurrent", "SeniorNotesNoncurrent"],
    "ltd_total": ["LongTermDebt", "DebtInstrumentCarryingAmount", "DebtAndCapitalLeaseObligations"],
    "debt_current": ["DebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "ltd_current": ["LongTermDebtCurrent"],
    "st_borrow": ["ShortTermBorrowings", "CommercialPaper"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "nci": ["MinorityInterest"],
}


def _d(s):
    return date.fromisoformat(s)


class Facts:
    def __init__(self, j):
        f = j.get("facts", {})
        self.g = f.get("us-gaap", {})
        self.dei = f.get("dei", {})
        self.entity = j.get("entityName", "")

    def usd_ok(self):
        for tag in T["net_income"] + T["revenue"]:
            if self.g.get(tag, {}).get("units", {}).get("USD"):
                return True
        return False

    def _merge(self, tags, unit, duration):
        per_tag = []
        for pr, tag in enumerate(tags):
            d = {}
            for f in self.g.get(tag, {}).get("units", {}).get(unit, []):
                has_start = "start" in f
                if has_start != duration or f.get("val") is None:
                    continue
                k = (f["start"], f["end"]) if duration else f["end"]
                if k not in d or f.get("filed", "") > d[k][1]:
                    d[k] = (float(f["val"]), f.get("filed", ""))
            if d:
                latest = max((k[1] if duration else k) for k in d)
                per_tag.append((latest, -pr, {k: v[0] for k, v in d.items()}))
        if not per_tag:
            return {}
        per_tag.sort(reverse=True)
        merged = dict(per_tag[0][2])
        for _, _, d in per_tag[1:]:
            for k, v in d.items():
                merged.setdefault(k, v)
        return merged

    def dur(self, key, unit="USD"):
        m = self._merge(T[key], unit, True)
        return [(_d(s), _d(e), v) for (s, e), v in m.items()]

    def inst(self, key, unit="USD"):
        m = self._merge(T[key], unit, False)
        return {_d(e): v for e, v in m.items()}

    def shares_outstanding(self):
        facts = self.dei.get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
        if not facts:
            return None, None
        last_filed = max(f.get("filed", "") for f in facts)
        latest = [f for f in facts if f.get("filed", "") == last_filed]
        end = max(f["end"] for f in latest)
        return sum(float(f["val"]) for f in latest if f["end"] == end), end


# ------------------------------------------------------------------ TTM arithmetic
def _len(s, e):
    return (e - s).days


def ttm_at(series, E):
    """Trailing-12-month value of a duration series for the period ending E (date)."""
    if not series:
        return None
    ending = [(s, e, v) for s, e, v in series if abs((e - E).days) <= 3]
    for s, e, v in ending:                       # 1) a fiscal year ends at E
        if 350 <= _len(s, e) <= 380:
            return v
    for s, e, v in sorted(ending, key=lambda x: x[0]):   # 2) FY + YTD - prior YTD (longest YTD first)
        L = _len(s, e)
        if not 80 <= L <= 290:
            continue
        ann = [vv for ss, ee, vv in series
               if 350 <= _len(ss, ee) <= 380 and abs((ee - (s - timedelta(days=1))).days) <= 10]
        prior = [vv for ss, ee, vv in series
                 if abs((ee - (E - timedelta(days=365))).days) <= 10 and abs(_len(ss, ee) - L) <= 10]
        if ann and prior:
            return ann[0] + v - prior[0]
    total, cur, ok = 0.0, E, True                # 3) four discrete quarters
    for _ in range(4):
        q = [(s, v) for s, e, v in series if 80 <= _len(s, e) <= 100 and abs((e - cur).days) <= 5]
        if not q:
            ok = False
            break
        total += q[0][1]
        cur = q[0][0] - timedelta(days=1)
    if ok:
        return total
    for s, e, v in ending:                       # 4) last resort: annualise a 9-month YTD
        if 260 <= _len(s, e) <= 290:
            return v * 365.0 / _len(s, e)
    return None


def latest_annual(series):
    ann = [(e, v) for s, e, v in series if 350 <= _len(s, e) <= 380]
    return max(ann)[1] if ann else None


def inst_at(series, E, tol=100, fallback=None):
    """Balance-sheet value at E; if absent within tol days, the latest within `fallback` days."""
    if not series:
        return None
    ok = [d for d in series if E - timedelta(days=tol) <= d <= E + timedelta(days=5)]
    if not ok and fallback:
        ok = [d for d in series if E - timedelta(days=fallback) <= d <= E + timedelta(days=5)]
    return series[max(ok)] if ok else None


def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def _sum(*vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def fundamentals(j):
    F = Facts(j)
    if not F.usd_ok():
        return {"sec_status": "no USD US-GAAP financials"}
    ni = F.dur("net_income")
    cfo = F.dur("cfo")
    if not ni or not cfo:
        return {"sec_status": "missing income or cash-flow data"}

    # most recent period end where both net income and CFO TTM can be rebuilt
    E = None
    for e in sorted({e for _, e, _ in ni}, reverse=True)[:6]:
        if ttm_at(ni, e) is not None and ttm_at(cfo, e) is not None:
            E = e
            break
    if E is None:
        return {"sec_status": "could not rebuild TTM"}
    E1 = None
    for e in sorted({e for _, e, _ in ni}, reverse=True):
        if abs((e - (E - timedelta(days=365))).days) <= 20 and ttm_at(ni, e) is not None:
            E1 = e
            break

    S = {k: F.dur(k) for k in ["revenue", "cogs", "gross_profit", "ebit", "pretax", "interest", "da",
                               "capex", "dividends", "buybacks", "sbc"]}
    I = {k: F.inst(k) for k in ["assets", "cur_assets", "cur_liab", "cash", "sti", "ltd_noncurrent",
                                "ltd_total", "debt_current", "ltd_current", "st_borrow", "equity", "nci",
                                "debt_combined"]}

    def flow(k, at):
        if at is None:
            return None
        return ttm_at(S[k] if k in S else {"ni": ni, "cfo": cfo}[k], at)

    def gp(at):
        g = flow("gross_profit", at)
        if g is None:
            r, c = flow("revenue", at), flow("cogs", at)
            g = r - c if r is not None and c is not None else None
        return g

    def ebit(at):
        x = flow("ebit", at)
        if x is None:
            p, i = flow("pretax", at), flow("interest", at)
            x = p + (i or 0) if p is not None else None
        return x

    def debt(at):
        # some filers tag long-term debt only in the 10-K, so allow a year-old value as fallback
        fb = 400
        nonc = inst_at(I["ltd_noncurrent"], at, fallback=fb)
        combined = inst_at(I["debt_combined"], at)
        if combined is not None:
            return combined, (nonc if nonc is not None else combined)
        if nonc is not None:
            cur = _first(inst_at(I["debt_current"], at),
                         _sum(inst_at(I["ltd_current"], at), inst_at(I["st_borrow"], at)),
                         inst_at(I["debt_current"], at, fallback=fb))
            return nonc + (cur or 0), nonc
        tot = inst_at(I["ltd_total"], at, fallback=fb)
        if tot is not None:
            return tot + (inst_at(I["st_borrow"], at) or 0), tot
        st = inst_at(I["st_borrow"], at)
        return (st or 0.0), 0.0

    out = {"sec_status": "ok", "sec_entity": F.entity, "period_end": E.isoformat(),
           "prior_period_end": E1.isoformat() if E1 else None}
    out["revenue"] = flow("revenue", E)
    out["gross_profit"] = gp(E)
    out["ebit"] = ebit(E)
    out["net_income"] = ttm_at(ni, E)
    out["cfo"] = ttm_at(cfo, E)
    capex = flow("capex", E)
    out["capex"] = capex if capex is not None else latest_annual(S["capex"])
    da = flow("da", E)
    out["da"] = da if da is not None else latest_annual(S["da"])
    out["interest"] = flow("interest", E)
    out["dividends"] = flow("dividends", E) or 0.0
    out["buybacks"] = flow("buybacks", E) or 0.0
    out["sbc"] = flow("sbc", E)
    out["assets"] = inst_at(I["assets"], E)
    out["cur_assets"] = inst_at(I["cur_assets"], E)
    out["cur_liab"] = inst_at(I["cur_liab"], E)
    out["cash"] = (inst_at(I["cash"], E) or 0.0) + (inst_at(I["sti"], E) or 0.0)
    out["debt"], out["lt_debt"] = debt(E)
    out["equity"] = inst_at(I["equity"], E)
    out["nci"] = inst_at(I["nci"], E) or 0.0
    out["shares_out"], out["shares_date"] = F.shares_outstanding()

    wd = F.dur("wdil", "shares")
    def wdil(at):
        if at is None:
            return None
        c = sorted([(_len(s, e), v) for s, e, v in wd if abs((e - at).days) <= 5])
        return c[0][1] if c else None
    out["wdil_shares"], out["wdil_shares_prior"] = wdil(E), wdil(E1)

    # prior year (for growth and F-score)
    out["revenue_prior"] = flow("revenue", E1)
    out["gross_profit_prior"] = gp(E1)
    out["net_income_prior"] = ttm_at(ni, E1) if E1 else None
    out["cfo_prior"] = ttm_at(cfo, E1) if E1 else None
    out["assets_prior"] = inst_at(I["assets"], E1) if E1 else None
    out["cur_assets_prior"] = inst_at(I["cur_assets"], E1) if E1 else None
    out["cur_liab_prior"] = inst_at(I["cur_liab"], E1) if E1 else None
    out["lt_debt_prior"] = debt(E1)[1] if E1 else None
    return out


# ------------------------------------------------------------------ fetching
class _Rate:
    def __init__(self, per_sec):
        self.lock, self.gap, self.next = threading.Lock(), 1.0 / per_sec, time.monotonic()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.gap
        time.sleep(max(0.0, t - now))


_local = threading.local()


def _session():
    if not hasattr(_local, "s"):
        s = requests.Session()
        s.headers.update({"User-Agent": _ua(), "Accept-Encoding": "gzip, deflate"})
        _local.s = s
    return _local.s


def ticker_to_cik():
    r = requests.get(TICKER_MAP, headers={"User-Agent": _ua()}, timeout=60)
    r.raise_for_status()
    return {v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()}


def fetch_all(ciks):
    """{cik: fundamentals dict}"""
    rate = _Rate(config.SEC_RATE_PER_SEC)
    res = {}

    def work(cik):
        err = ""
        for attempt in range(4):
            rate.wait()
            try:
                r = _session().get(FACTS_URL.format(cik=cik), timeout=60)
                if r.status_code == 404:
                    return cik, {"sec_status": "no XBRL facts"}
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2 * (attempt + 1))
                    continue
                r.raise_for_status()
                return cik, fundamentals(r.json())
            except Exception as e:  # noqa: BLE001
                err = str(e)
                time.sleep(2 * (attempt + 1))
        return cik, {"sec_status": f"fetch failed: {err[:80]}"}

    ciks = list(dict.fromkeys(ciks))
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(work, c) for c in ciks]
        for i, f in enumerate(as_completed(futs), 1):
            cik, d = f.result()
            res[cik] = d
            if i % 200 == 0:
                print(f"  SEC: {i}/{len(ciks)}")
    return res
