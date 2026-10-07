# Auto-generated answer script. It reads the RAW csv files in ../data, cleans them,
# computes the answer and prints one RESULT_JSON line. Run: python <this file>
# Question: What is the average delivery time by city?

# ---------------------------------------------------------------------------
# Shared cleaning prelude.
# Every generated answer script starts with this exact text, so each script is
# fully standalone: it loads the RAW csv files, cleans them, then runs the
# question-specific analysis and prints one RESULT_JSON line.
# ---------------------------------------------------------------------------
import json
import os
import re
import sys

import pandas as pd

DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data"
)
LOG = {}
DATE_INFO = {}


def _read(name):
    df = pd.read_csv(os.path.join(DATA_DIR, name), dtype=str, keep_default_na=False)
    df = df.apply(lambda col: col.str.strip())
    return df.replace({"": pd.NA})


def _canon_id(s):
    return s.str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)


# ---- fx rates ---------------------------------------------------------------
_fx = _read("fx_rates.csv")
FX = {c.upper(): float(v) for c, v in zip(_fx["currency"], _fx["usd_per_unit"])}

# ---- customers: ids compared ignoring case and hyphens, duplicates merged ----
customers = _read("customers.csv")
customers["customer_id"] = _canon_id(customers["customer_id"])
customers["email"] = customers["email"].str.lower()
customers["name"] = customers["name"].str.replace(r"\s+", " ", regex=True)
LOG["customer_rows_raw"] = int(len(customers))
LOG["duplicate_customer_ids_merged"] = int(len(customers) - customers["customer_id"].nunique())
customers = customers.groupby("customer_id", as_index=False).first()
LOG["customers_missing_country"] = int(customers["country"].isna().sum())

# ---- products ----------------------------------------------------------------
products = _read("products.csv")
products["list_price"] = pd.to_numeric(products["list_price"])
LOG["products_without_category"] = int(products["category"].isna().sum())
products["category"] = products["category"].fillna("Unknown")

# ---- orders: dedupe, normalise status, parse mixed date formats --------------
orders_raw = _read("orders.csv")
LOG["order_rows_raw"] = int(len(orders_raw))
LOG["status_spellings_raw"] = int(orders_raw["status"].nunique())
orders = orders_raw.drop_duplicates()
LOG["exact_duplicate_order_rows_removed"] = int(len(orders_raw) - len(orders))
_before = len(orders)
orders = orders.drop_duplicates(subset="order_id", keep="first").copy()
LOG["conflicting_duplicate_order_ids_removed"] = int(_before - len(orders))
orders["customer_id"] = _canon_id(orders["customer_id"])
orders["status"] = orders["status"].str.lower()
orders["currency"] = orders["currency"].str.upper()
orders["total_amount"] = pd.to_numeric(orders["total_amount"])


def _parse_dates(s):
    parts = []
    counts = {}
    iso = s.str.match(r"^\d{4}-\d{2}-\d{2}$").fillna(False).astype(bool)
    counts["YYYY-MM-DD"] = int(iso.sum())
    if iso.any():
        parts.append(pd.to_datetime(s[iso], format="%Y-%m-%d"))
    mon = s.str.match(r"^\d{1,2} [A-Za-z]{3} \d{2}$").fillna(False).astype(bool)
    counts["DD Mon YY"] = int(mon.sum())
    if mon.any():
        parts.append(pd.to_datetime(s[mon], format="%d %b %y"))
    sl = s.str.match(r"^\d{1,2}/\d{1,2}/\d{4}$").fillna(False).astype(bool)
    counts["NN/NN/YYYY"] = int(sl.sum())
    DATE_INFO["slash_rows"] = int(sl.sum())
    if sl.any():
        nums = s[sl].str.split("/", expand=True).astype(int)
        first_big = bool((nums[0] > 12).any())
        second_big = bool((nums[1] > 12).any())
        if first_big and not second_big:
            dayfirst = True
            why = "some values have a first part above 12 (e.g. 27/03/2025) and none have a second part above 12"
        elif second_big and not first_big:
            dayfirst = False
            why = "some values have a second part above 12 and none have a first part above 12"
        else:
            dayfirst = True
            why = "the data gives no way to tell, so day-first was assumed"
        DATE_INFO["dayfirst"] = dayfirst
        DATE_INFO["note"] = (
            "Slash dates in the order file (e.g. 04/05/2025) are read as "
            + ("DD/MM/YYYY" if dayfirst else "MM/DD/YYYY")
            + " because " + why + "."
        )
        parts.append(pd.to_datetime(s[sl], format="%d/%m/%Y" if dayfirst else "%m/%d/%Y"))
    out = pd.concat(parts).reindex(s.index) if parts else pd.Series(pd.NaT, index=s.index)
    LOG["date_formats_found"] = counts
    LOG["unparseable_dates"] = int(out.isna().sum())
    return out


orders["date"] = _parse_dates(orders["order_date"])
orders = orders.drop(columns=["order_date"])
orders["orphan"] = ~orders["customer_id"].isin(customers["customer_id"])
LOG["orders_with_unknown_customer"] = int(orders["orphan"].sum())
DATA_MIN = orders["date"].min()
DATA_MAX = orders["date"].max()

# ---- order lines: rescale discounts, convert to USD, attach order fields -----
items = _read("order_items.csv")
items["quantity"] = pd.to_numeric(items["quantity"])
items["unit_price"] = pd.to_numeric(items["unit_price"])
items["discount_raw"] = pd.to_numeric(items["discount"])
items["discount"] = items["discount_raw"].where(items["discount_raw"] <= 1, items["discount_raw"] / 100)
LOG["discounts_rescaled_from_percent"] = int((items["discount_raw"] > 1).sum())
LOG["return_lines"] = int((items["quantity"] < 0).sum())
_n_items = len(items)
items = items.merge(
    orders[["order_id", "customer_id", "date", "status", "currency", "orphan"]],
    on="order_id", how="inner",
)
LOG["order_lines_without_order_removed"] = int(_n_items - len(items))
items["fx"] = items["currency"].map(FX)
items["usd"] = items["quantity"] * items["unit_price"] * (1 - items["discount"]) * items["fx"]
items = items.merge(products[["product_id", "category"]], on="product_id", how="left")
items["category"] = items["category"].fillna("Unknown")
rev_items = items[items["status"].isin(["delivered", "shipped"])]

_gross = (items[items["quantity"] > 0]
          .assign(g=lambda d: d["quantity"] * d["unit_price"] * (1 - d["discount"]))
          .groupby("order_id")["g"].sum())
_cmp = orders.set_index("order_id")[["total_amount"]].join(_gross)
LOG["orders_total_amount_mismatch"] = int(((_cmp["total_amount"] - _cmp["g"]).abs() > 0.5).sum())


# ---- notes, finance report check, output helpers ----------------------------
def _note(tag):
    n = LOG
    if tag == "dedup_orders" and n["exact_duplicate_order_rows_removed"]:
        return "Removed %d exact duplicate order rows before counting." % n["exact_duplicate_order_rows_removed"]
    if tag == "merge_customers" and n["duplicate_customer_ids_merged"]:
        return ("Merged %d duplicate customer IDs (IDs are compared ignoring case and hyphens, "
                "so c-0005 and C0005 are one customer)." % n["duplicate_customer_ids_merged"])
    if tag == "dates" and DATE_INFO.get("slash_rows"):
        return DATE_INFO["note"]
    if tag == "fx":
        used = ", ".join("1 %s = %s USD" % (k, v) for k, v in FX.items() if k != "USD")
        return "Converted non-USD amounts to USD using fx_rates.csv (%s)." % used
    if tag == "discount" and n["discounts_rescaled_from_percent"]:
        return ("%d order lines store the discount as a whole percentage (e.g. 10) instead of a "
                "fraction (0.10); values above 1 were divided by 100." % n["discounts_rescaled_from_percent"])
    if tag == "revenue_def":
        return ("Net revenue = quantity x unit_price x (1 - discount) from order_items, for delivered "
                "and shipped orders only; cancelled and pending orders are excluded.")
    if tag == "returns" and n["return_lines"]:
        return "%d lines with negative quantity are returns and reduce revenue." % n["return_lines"]
    if tag == "status_case" and n["status_spellings_raw"] > 4:
        return "Status values differing only by case or spacing were normalised (%d raw spellings)." % n["status_spellings_raw"]
    if tag == "orphans_in_revenue" and n["orders_with_unknown_customer"]:
        return ("%d orders reference customer IDs missing from customers.csv; they still count in "
                "revenue because the sale happened." % n["orders_with_unknown_customer"])
    if tag == "orphans_excluded" and n["orders_with_unknown_customer"]:
        return ("%d orders reference customer IDs missing from customers.csv and are excluded from "
                "customer-level figures." % n["orders_with_unknown_customer"])
    if tag == "total_amount" and n["orders_total_amount_mismatch"]:
        return ("orders.total_amount disagrees with the sum of the order lines on %d orders, so the "
                "order lines were used instead." % n["orders_total_amount_mismatch"])
    if tag == "no_period":
        return "No period was given, so the whole dataset (%s to %s) was used." % (
            DATA_MIN.strftime("%Y-%m-%d"), DATA_MAX.strftime("%Y-%m-%d"))
    if tag == "partial_period":
        return "The data ends on %s, so only days up to then are included." % DATA_MAX.strftime("%Y-%m-%d")
    if tag == "year_assumed":
        return "No year was given; the data only contains %d, so that year was used." % DATA_MIN.year
    if tag == "unknown_category" and n["products_without_category"]:
        return "%d products have no category and are reported as Unknown." % n["products_without_category"]
    if tag == "missing_country" and n["customers_missing_country"]:
        return "Customers with no country on file are excluded from the country breakdown."
    if tag == "causal":
        return ("Transaction data can show what changed but not why; the category changes below are "
                "supporting evidence, not proven causes.")
    return None


def report_check(label, value):
    path = os.path.join(DATA_DIR, "finance_report.txt")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(re.escape(label) + r"[^\n]*?USD\s*([\d,]*\d)", text)
    if not m:
        return None
    reported = float(m.group(1).replace(",", ""))
    diff = (reported - value) / value * 100 if value else 0.0
    consistent = abs(diff) <= 2.0
    if consistent:
        msg = "finance_report.txt says USD %s for %s, consistent with the tables (within 2%%)." % (m.group(1), label)
    else:
        msg = ("CONFLICT: finance_report.txt says USD %s for %s but the order tables give USD %s "
               "(report is %+.1f%% off). The tables were used because they can be recomputed line by "
               "line; the report figure cannot be reproduced." % (m.group(1), label, "{:,.2f}".format(value), diff))
    return {"report_value": reported, "table_value": value, "difference_pct": round(diff, 2),
            "consistent": consistent, "message": msg}


def _default(o):
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


def _print_result(result):
    print("RESULT_JSON:" + json.dumps(result, default=_default))
    sys.stdout.flush()


def emit(value, unit=None, summary=None, tags=(), evidence=None, extra=None):
    notes = [t for t in (_note(x) for x in tags) if t]
    extra = extra or {}
    confidence = max(0.7, round(0.97 - 0.01 * len(notes), 2))
    cross = extra.get("cross_document")
    if cross:
        notes.append(cross["message"])
        if not cross["consistent"]:
            confidence = round(confidence - 0.15, 2)
    _print_result({
        "decision": "ANSWER_WITH_ASSUMPTIONS" if notes else "ANSWER",
        "answer": value, "unit": unit, "summary": summary,
        "assumptions": notes, "confidence": confidence,
        "evidence": evidence or {}, "extra": extra, "data_quality": LOG,
    })


def decide(decision, reason, question=None):
    _print_result({
        "decision": decision, "answer": None, "reason": reason, "follow_up_question": question,
        "summary": reason, "assumptions": [], "confidence": 0.9,
        "evidence": {
            "data_range": [DATA_MIN.strftime("%Y-%m-%d"), DATA_MAX.strftime("%Y-%m-%d")],
            "tables_and_columns": {
                "customers": list(customers.columns), "products": list(products.columns),
                "orders": list(orders.columns), "order_items": list(items.columns),
            },
        },
        "extra": {}, "data_quality": LOG,
    })
    sys.exit(0)


def in_period(df):
    return df[(df["date"] >= START) & (df["date"] <= END)]


# ---- question-specific analysis ----
decide('REFUSE', 'This cannot be answered from the data: there is no delivery or shipping dates (orders only have an order date and a status).', None)
