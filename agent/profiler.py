"""Data-health profiler: scans the RAW files and lists every quality problem found.

It deliberately works on the raw csv files (not on the cleaned frames), so it
is an independent look at the data. The agent's cleaning steps are the fixes
for the problems listed here.
"""
import re

import pandas as pd

from .datainfo import ROOT, load_namespace

DATA = ROOT / "data"


def _raw(name):
    df = pd.read_csv(DATA / name, dtype=str, keep_default_na=False)
    df = df.apply(lambda c: c.str.strip())
    return df.replace({"": pd.NA})


def _canon(s):
    return s.str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)


def profile():
    findings = []

    def add(table, issue, count, detail, fix):
        if count:
            findings.append({"table": table, "issue": issue, "count": int(count), "detail": detail, "fix": fix})

    cust, prod, orders = _raw("customers.csv"), _raw("products.csv"), _raw("orders.csv")
    items, fx = _raw("order_items.csv"), _raw("fx_rates.csv")

    dup_cust = len(cust) - _canon(cust["customer_id"]).nunique()
    add("customers", "duplicate customers under different ID formats", dup_cust,
        "e.g. c-0005 and C0005; emails differ only by case", "merge on ID ignoring case and hyphens")
    add("customers", "missing country", cust["country"].isna().sum(), "country is blank",
        "exclude from country breakdowns")
    add("products", "missing category", prod["category"].isna().sum(), "category is blank",
        "report as Unknown")

    dup_rows = orders.duplicated().sum()
    add("orders", "exact duplicate rows", dup_rows, "same order logged twice", "drop duplicates before counting")
    add("orders", "status spelled several ways", orders["status"].nunique() - orders["status"].str.lower().nunique(),
        "spellings: " + ", ".join(sorted(orders["status"].dropna().unique())[:6]) + " ...",
        "lower-case and trim")

    d = orders["order_date"].dropna()
    iso = d.str.match(r"^\d{4}-\d{2}-\d{2}$").sum()
    mon = d.str.match(r"^\d{1,2} [A-Za-z]{3} \d{2}$").sum()
    sl = d[d.str.match(r"^\d{1,2}/\d{1,2}/\d{4}$")]
    add("orders", "three different date formats", 1 if (iso and mon and len(sl)) else 0,
        "%d ISO, %d 'DD Mon YY', %d NN/NN/YYYY" % (iso, mon, len(sl)), "parse each format separately")
    if len(sl):
        parts = sl.str.split("/", expand=True).astype(int)
        ambiguous = ((parts[0] <= 12) & (parts[1] <= 12) & (parts[0] != parts[1])).sum()
        evidence_dayfirst = int((parts[0] > 12).sum())
        add("orders", "ambiguous slash dates (both parts <= 12)", ambiguous,
            "%d slash dates have a first part above 12, which proves DD/MM/YYYY" % evidence_dayfirst,
            "read as day-first; flag any user question that uses an ambiguous date")

    known = set(_canon(cust["customer_id"]))
    orphan = (~_canon(orders.drop_duplicates()["customer_id"]).isin(known)).sum()
    add("orders", "orders for customers that do not exist", orphan, "customer_id not in customers.csv",
        "keep in revenue, exclude from customer-level figures")
    add("orders", "currencies mixed", orders["currency"].nunique() - 1, "currencies: " + ", ".join(sorted(orders["currency"].dropna().unique())),
        "convert to USD with fx_rates.csv")

    disc = pd.to_numeric(items["discount"])
    add("order_items", "discount stored on two scales", (disc > 1).sum(),
        "fractions (0.10) mixed with whole percentages (10)", "divide values above 1 by 100")
    add("order_items", "negative quantities (returns)", (pd.to_numeric(items["quantity"]) < 0).sum(),
        "return lines inside the sales table", "let them reduce revenue; use for return rate")

    rate = {c.upper(): float(v) for c, v in zip(fx["currency"], fx["usd_per_unit"])}
    ocur = orders.drop_duplicates("order_id").set_index("order_id")["currency"].str.upper()
    p = prod.set_index("product_id")
    list_usd = pd.to_numeric(p["list_price"]) * p["price_currency"].str.upper().map(rate)
    it = items.assign(
        cur=items["order_id"].map(ocur),
        price=pd.to_numeric(items["unit_price"]),
    )
    it["usd_price"] = it["price"] * it["cur"].map(rate)
    it["list_usd"] = it["product_id"].map(list_usd)
    off = ((it["usd_price"] - it["list_usd"]).abs() / it["list_usd"] > 0.03).sum()
    add("order_items", "unit price disagrees with products list price", off,
        "more than 3% apart after currency conversion", "use the price actually charged (order line)")

    ns = load_namespace()
    add("orders", "total_amount disagrees with sum of order lines", ns["LOG"]["orders_total_amount_mismatch"],
        "header total differs from line items by more than 0.5", "ignore total_amount, use order lines")

    report = (DATA / "finance_report.txt")
    if report.exists():
        text = report.read_text(encoding="utf-8")
        rev = ns["rev_items"]
        for q in (2, 3):
            m = re.search(r"Q%d 2025[^\n]*?USD\s*([\d,]*\d)" % q, text)
            if not m:
                continue
            lo, hi = pd.Timestamp(2025, (q - 1) * 3 + 1, 1), pd.Timestamp(2025, q * 3, 1) + pd.offsets.MonthEnd(0)
            calc = float(rev[(rev["date"] >= lo) & (rev["date"] <= hi)]["usd"].sum())
            stated = float(m.group(1).replace(",", ""))
            if abs(stated - calc) / calc > 0.02:
                add("finance_report.txt", "report contradicts the tables (Q%d)" % q, 1,
                    "report says USD %s, tables give USD %s" % (m.group(1), "{:,.0f}".format(calc)),
                    "trust the tables, flag the conflict in answers")
    return findings


def render(findings):
    lines = ["DATA HEALTH REPORT", "-" * 78]
    for f in findings:
        lines.append("[%s] %s: %d" % (f["table"], f["issue"], f["count"]))
        lines.append("      %s" % f["detail"])
        lines.append("      fix: %s" % f["fix"])
    lines.append("-" * 78)
    lines.append("%d problem types found." % len(findings))
    return "\n".join(lines)
