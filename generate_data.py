"""
Messy retail dataset generator for the Proof-Carrying Data Analyst project.

Outputs
  data/        what the agent is allowed to see
    customers.csv, products.csv, orders.csv, order_items.csv,
    fx_rates.csv, finance_report.txt
  eval/        held out, never shown to the agent
    answer_key.json      ground truth for every test question
    traps_manifest.json  how many of each trap were planted

Usage
  pip install pandas numpy
  python generate_data.py            (seed 42 by default)
  python generate_data.py --seed 7

Business rules the ground truth is computed with
  - Order currency is USD, EUR or INR (fx_rates.csv, rate = USD per 1 unit)
  - Revenue = sum(quantity * unit_price * (1 - discount)) over order_items,
    converted to USD, for orders with status delivered or shipped.
    Negative quantities are returns and reduce revenue.
  - orders.total_amount is NOT used (it is deliberately unreliable)
  - Slash dates are DD/MM/YYYY (provable from rows like 27/03/2025)
  - Duplicate customer IDs (c-0005 vs C0005) are the same person
  - Data covers 2025-01-01 to 2025-09-30 only
"""

import argparse
import json
import os
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

FX = {"USD": 1.0, "EUR": 1.08, "INR": 0.012}
COUNTRY_CCY = {"US": "USD", "DE": "EUR", "FR": "EUR", "IN": "INR"}
START = date(2025, 1, 1)
END = date(2025, 9, 30)
N_CUSTOMERS = 200
N_PRODUCTS = 40
N_ORDERS = 1500
CATEGORIES = ["Electronics", "Home", "Fashion", "Beauty", "Sports"]
FIRST = ["Aarav", "Maya", "Liam", "Sofia", "Noah", "Priya", "Lucas", "Emma",
         "Arjun", "Mia", "Ethan", "Anika", "Oliver", "Zara", "Kabir", "Lena"]
LAST = ["Sharma", "Smith", "Müller", "Dubois", "Patel", "Brown", "Rossi",
        "Kumar", "Garcia", "Nair", "Khan", "Wagner", "Martin", "Iyer"]


def money(x, ccy):
    return int(round(x)) if ccy == "INR" else round(x, 2)


def build(seed):
    rng = random.Random(seed)
    np.random.seed(seed)
    manifest = {}

    # ---------- customers ----------
    customers = []
    for i in range(1, N_CUSTOMERS + 1):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        customers.append({
            "customer_id": f"C{i:04d}",
            "name": f"{first} {last}",
            "email": f"{first}.{last}{i}@example.com".lower(),
            "country": rng.choice(list(COUNTRY_CCY)),
            "signup_date": (date(2023, 1, 1) + timedelta(days=rng.randint(0, 700))).isoformat(),
        })
    true_country = {c["customer_id"]: c["country"] for c in customers}

    dup_map = {}
    for c in rng.sample(customers, 10):
        num = c["customer_id"][1:]
        dup_id = f"c-{num}"
        dup_map[dup_id] = c["customer_id"]
    dup_rows = []
    for dup_id, canon in dup_map.items():
        base = next(c for c in customers if c["customer_id"] == canon)
        dup_rows.append({**base, "customer_id": dup_id,
                         "email": base["email"].upper(),
                         "name": base["name"].replace(" ", "  ")})
    customers_out = customers + dup_rows
    missing_country = rng.sample(range(len(customers_out)), 10)
    for idx in missing_country:
        customers_out[idx]["country"] = None
    manifest["duplicate_customers"] = len(dup_map)
    manifest["customers_missing_country"] = len(missing_country)
    rng.shuffle(customers_out)

    # ---------- products ----------
    products = []
    base_usd = {}
    for i in range(1, N_PRODUCTS + 1):
        pid = f"P{i:03d}"
        usd = round(rng.uniform(5, 200), 2)
        ccy = rng.choice(["USD", "EUR", "INR"])
        base_usd[pid] = usd
        products.append({
            "product_id": pid,
            "name": f"Item {i}",
            "category": rng.choice(CATEGORIES),
            "list_price": money(usd / FX[ccy], ccy),
            "price_currency": ccy,
        })
    null_cat = rng.sample(range(N_PRODUCTS), 2)
    for idx in null_cat:
        products[idx]["category"] = None
    cat_of = {p["product_id"]: (p["category"] or "Unknown") for p in products}
    manifest["products_null_category"] = len(null_cat)

    # ---------- clean orders and items ----------
    span = (END - START).days
    orphan_orders = set(rng.sample(range(N_ORDERS), 15))
    clean_orders, clean_items = [], []
    for n in range(N_ORDERS):
        oid = f"ORD-{n + 1:05d}"
        canon = rng.choice(customers)["customer_id"]
        ccy = COUNTRY_CCY[true_country[canon]]
        if n in orphan_orders:
            ref_id, canon = f"C9{rng.randint(100, 999)}", None
            ccy = "USD"
        else:
            ref_id = canon
            for d_id, c_id in dup_map.items():
                if c_id == canon and rng.random() < 0.5:
                    ref_id = d_id
        status = rng.choices(["delivered", "shipped", "cancelled", "pending"],
                             [0.6, 0.2, 0.1, 0.1])[0]
        od = START + timedelta(days=rng.randint(0, span))
        lines = []
        for _ in range(rng.randint(1, 4)):
            pid = rng.choice(list(base_usd))
            lines.append({
                "order_id": oid,
                "product_id": pid,
                "quantity": rng.randint(1, 5),
                "unit_price": money(base_usd[pid] / FX[ccy], ccy),
                "discount": rng.choice([0, 0, 0, 0.05, 0.1, 0.15, 0.2]),
            })
        if status in ("delivered", "shipped") and rng.random() < 0.06:
            r = rng.choice(lines)
            lines.append({**r, "quantity": -1})
        clean_items.extend(lines)
        gross = sum(l["quantity"] * l["unit_price"] * (1 - l["discount"])
                    for l in lines if l["quantity"] > 0)
        clean_orders.append({
            "order_id": oid, "customer_ref": ref_id, "canon_customer": canon,
            "date": od, "status": status, "currency": ccy,
            "total_amount": money(gross, ccy),
            "payment_method": rng.choice(["card", "upi", "paypal", "cod"]),
        })

    ci = pd.DataFrame(clean_items)
    co = pd.DataFrame(clean_orders)
    ci["fx"] = ci["order_id"].map(co.set_index("order_id")["currency"]).map(FX)
    ci["usd"] = ci["quantity"] * ci["unit_price"] * (1 - ci["discount"]) * ci["fx"]
    ci = ci.merge(co[["order_id", "date", "status", "canon_customer"]], on="order_id")
    ci["category"] = ci["product_id"].map(cat_of)
    ci["date"] = pd.to_datetime(ci["date"])
    rev = ci[ci["status"].isin(["delivered", "shipped"])]

    # ---------- corrupt orders ----------
    fmt_counts = {"iso": 0, "d_mon_yy": 0, "slash_dmy": 0}
    out_orders = []
    for o in clean_orders:
        r = rng.random()
        if r < 0.5:
            ds, k = o["date"].isoformat(), "iso"
        elif r < 0.75:
            ds, k = o["date"].strftime("%d %b %y"), "d_mon_yy"
        else:
            ds, k = o["date"].strftime("%d/%m/%Y"), "slash_dmy"
        fmt_counts[k] += 1
        st = o["status"]
        v = rng.random()
        if v < 0.15:
            st = st.upper()
        elif v < 0.25:
            st = st.title() + " "
        out_orders.append({
            "order_id": o["order_id"], "customer_id": o["customer_ref"],
            "order_date": ds, "status": st,
            "total_amount": o["total_amount"], "currency": o["currency"],
            "payment_method": o["payment_method"],
        })
    manifest["order_date_formats"] = fmt_counts
    manifest["orphan_orders"] = len(orphan_orders)

    bad_total = rng.sample(range(len(out_orders)), 20)
    for i in bad_total:
        out_orders[i]["total_amount"] = money(out_orders[i]["total_amount"] * 1.1,
                                              out_orders[i]["currency"])
    manifest["orders_total_mismatch"] = len(bad_total)

    dup_idx = rng.sample(range(len(out_orders)), 40)
    out_orders.extend(dict(out_orders[i]) for i in dup_idx)
    manifest["exact_duplicate_order_rows"] = len(dup_idx)
    rng.shuffle(out_orders)

    # ---------- corrupt items ----------
    out_items = []
    pct_count = 0
    for l in clean_items:
        row = dict(l)
        if row["discount"] > 0 and rng.random() < 0.3:
            row["discount"] = round(row["discount"] * 100)
            pct_count += 1
        out_items.append(row)
    manifest["discounts_stored_as_percent"] = pct_count
    manifest["return_lines_negative_qty"] = int((ci["quantity"] < 0).sum())
    bad_price = rng.sample(range(len(out_items)), 15)
    for i in bad_price:
        out_items[i]["unit_price"] = money(out_items[i]["unit_price"] * 1.2,
                                           "USD")
    manifest["items_price_disagrees_with_products"] = len(bad_price)
    # unit_price tampering above changes truth, so recompute truth from out_items
    oi = pd.DataFrame(out_items)
    oi["disc_frac"] = oi["discount"].apply(lambda d: d / 100 if d > 1 else d)
    oi["fx"] = oi["order_id"].map(co.set_index("order_id")["currency"]).map(FX)
    oi["usd"] = oi["quantity"] * oi["unit_price"] * (1 - oi["disc_frac"]) * oi["fx"]
    oi = oi.merge(co[["order_id", "date", "status", "canon_customer", "customer_ref"]],
                  on="order_id")
    oi["category"] = oi["product_id"].map(cat_of)
    oi["date"] = pd.to_datetime(oi["date"])
    rev = oi[oi["status"].isin(["delivered", "shipped"])]

    # ---------- truth values ----------
    def rev_between(a, b):
        m = (rev["date"] >= a) & (rev["date"] <= b)
        return round(float(rev.loc[m, "usd"].sum()), 2)

    mar = rev_between("2025-03-01", "2025-03-31")
    q2 = rev_between("2025-04-01", "2025-06-30")
    q3 = rev_between("2025-07-01", "2025-09-30")
    may = rev_between("2025-05-01", "2025-05-31")
    jun = rev_between("2025-06-01", "2025-06-30")
    total_rev = round(float(rev["usd"].sum()), 2)

    known = rev[rev["canon_customer"].notna()]
    top5 = (known.groupby("canon_customer")["usd"].sum()
            .sort_values(ascending=False).head(5).round(2))
    q2_mask = (rev["date"] >= "2025-04-01") & (rev["date"] <= "2025-06-30")
    by_cat = rev[q2_mask].groupby("category")["usd"].sum().round(2).to_dict()

    orders_df = co.copy()
    orders_df["date"] = pd.to_datetime(orders_df["date"])
    uniq_customers = orders_df["canon_customer"].dropna().nunique()
    sold = oi[(oi["quantity"] > 0) & oi["status"].isin(["delivered", "shipped"])]["quantity"].sum()
    returned = -oi[oi["quantity"] < 0]["quantity"].sum()
    rev_orders = orders_df[orders_df["status"].isin(["delivered", "shipped"])]
    per_order = rev.groupby("order_id")["usd"].sum()
    top_country = (orders_df.dropna(subset=["canon_customer"])
                   .assign(country=lambda d: d["canon_customer"].map(true_country))
                   ["country"].value_counts())
    # visible country column has 10 blanks, so compute from visible data
    vis = pd.DataFrame(customers_out)
    vis_country = vis.set_index("customer_id")["country"]
    vis_ct = (orders_df.assign(country=orders_df["customer_ref"].map(vis_country))
              .dropna(subset=["country"])["country"].value_counts())

    key = [
        {"id": "Q01", "question": "How many unique orders were placed in 2025?",
         "expected_behavior": "ANSWER", "expected_answer": N_ORDERS,
         "traps": ["exact duplicate order rows"]},
        {"id": "Q02", "question": "How many unique orders were placed in March 2025?",
         "expected_behavior": "ANSWER",
         "expected_answer": int(((orders_df["date"] >= "2025-03-01") &
                                 (orders_df["date"] <= "2025-03-31")).sum()),
         "traps": ["duplicate rows", "mixed date formats"]},
        {"id": "Q03", "question": "What was net revenue in March 2025?",
         "expected_behavior": "ANSWER_WITH_ASSUMPTIONS", "expected_answer": mar,
         "unit": "USD",
         "traps": ["mixed currencies", "duplicates", "status casing",
                   "discount scale", "returns"]},
        {"id": "Q04", "question": "What was total revenue for Q3 2025?",
         "expected_behavior": "ANSWER_WITH_ASSUMPTIONS", "expected_answer": q3,
         "unit": "USD",
         "notes": "finance_report.txt states a different Q3 figure; agent must flag the contradiction",
         "traps": ["table vs document contradiction"]},
        {"id": "Q05", "question": "What was total revenue for Q2 2025?",
         "expected_behavior": "ANSWER_WITH_ASSUMPTIONS", "expected_answer": q2,
         "unit": "USD",
         "notes": "finance_report.txt agrees with this one (rounded)"},
        {"id": "Q06", "question": "Who are the top 5 customers by net spend?",
         "expected_behavior": "ANSWER_WITH_ASSUMPTIONS",
         "expected_answer": {k: float(v) for k, v in top5.items()}, "unit": "USD",
         "notes": "must merge c-XXXX with CXXXX; orphan orders excluded",
         "traps": ["duplicate customers", "orphan orders"]},
        {"id": "Q07", "question": "What was Q2 2025 revenue by product category?",
         "expected_behavior": "ANSWER_WITH_ASSUMPTIONS", "expected_answer": by_cat,
         "unit": "USD", "notes": "null category reported as Unknown",
         "traps": ["null category"]},
        {"id": "Q08", "question": "How many distinct customers placed an order?",
         "expected_behavior": "ANSWER", "expected_answer": int(uniq_customers),
         "notes": "after merging duplicate IDs, orphan orders excluded"},
        {"id": "Q09", "question": "What is the average order value?",
         "expected_behavior": "ANSWER_WITH_ASSUMPTIONS",
         "expected_answer": round(float(per_order.mean()), 2), "unit": "USD",
         "notes": "delivered and shipped orders, net of returns"},
        {"id": "Q10", "question": "What percentage of units sold were returned?",
         "expected_behavior": "ANSWER",
         "expected_answer": round(float(returned) / float(sold) * 100, 2),
         "unit": "percent"},
        {"id": "Q11", "question": "Which country placed the most orders?",
         "expected_behavior": "ANSWER_WITH_ASSUMPTIONS",
         "expected_answer": vis_ct.index[0],
         "notes": "orders with unknown or missing country are excluded"},
        {"id": "Q12", "question": "How many orders reference a customer that does not exist?",
         "expected_behavior": "ANSWER", "expected_answer": len(orphan_orders)},
        {"id": "Q13", "question": "What was the revenue on 04/05/2025?",
         "expected_behavior": "CLARIFY",
         "notes": "04/05 could be 4 May or 5 April; agent should ask or state its assumption explicitly"},
        {"id": "Q14", "question": "What was total revenue?",
         "expected_behavior": "ANSWER_WITH_ASSUMPTIONS", "expected_answer": total_rev,
         "unit": "USD", "notes": "must state currency and period assumptions"},
        {"id": "Q15", "question": "Why did sales drop in June compared to May?",
         "expected_behavior": "ANSWER_WITH_ASSUMPTIONS",
         "expected_answer": {"may": may, "june": jun,
                             "premise_true": jun < may},
         "notes": "must check the premise first; data cannot explain causes either way",
         "traps": ["false premise" if jun >= may else "causal question"]},
        {"id": "Q16", "question": "What was revenue in Q4 2025?",
         "expected_behavior": "REFUSE",
         "notes": "data ends 2025-09-30"},
        {"id": "Q17", "question": "What is the average delivery time by city?",
         "expected_behavior": "REFUSE",
         "notes": "no delivery date or city columns exist"},
        {"id": "Q18", "question": "What is our profit margin?",
         "expected_behavior": "REFUSE", "notes": "no cost data exists"},
    ]

    # ---------- finance report ----------
    q2_rounded = int(round(q2, -3))
    q3_wrong = int(round(q3 * 1.12, -3))
    report = (
        "NORTHWIND RETAIL - MANAGEMENT SUMMARY (FY2025, UNAUDITED)\n"
        "---------------------------------------------------------\n"
        f"Q2 2025 net revenue was approximately USD {q2_rounded:,}.\n"
        f"Q3 2025 net revenue came in at USD {q3_wrong:,}, a strong quarter.\n"
        "Returns remained low across all categories.\n"
        "Figures are preliminary and subject to change.\n"
    )
    manifest["finance_report_q3_stated"] = q3_wrong
    manifest["finance_report_q3_true"] = q3

    return {
        "customers": pd.DataFrame(customers_out),
        "products": pd.DataFrame(products),
        "orders": pd.DataFrame(out_orders),
        "order_items": pd.DataFrame(out_items),
        "fx": pd.DataFrame({"currency": list(FX), "usd_per_unit": list(FX.values())}),
        "report": report,
        "key": key,
        "manifest": manifest,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    result = build(args.seed)
    os.makedirs("data", exist_ok=True)
    os.makedirs("eval", exist_ok=True)

    result["customers"].to_csv("data/customers.csv", index=False)
    result["products"].to_csv("data/products.csv", index=False)
    result["orders"].to_csv("data/orders.csv", index=False)
    result["order_items"][["order_id", "product_id", "quantity",
                           "unit_price", "discount"]].to_csv("data/order_items.csv", index=False)
    result["fx"].to_csv("data/fx_rates.csv", index=False)
    with open("data/finance_report.txt", "w", encoding="utf-8") as f:
        f.write(result["report"])
    with open("eval/answer_key.json", "w", encoding="utf-8") as f:
        json.dump(result["key"], f, indent=2, ensure_ascii=False)
    with open("eval/traps_manifest.json", "w", encoding="utf-8") as f:
        json.dump(result["manifest"], f, indent=2)

    print("Wrote data/ and eval/ (seed", args.seed, ")")
    print(json.dumps(result["manifest"], indent=2))


if __name__ == "__main__":
    main()
