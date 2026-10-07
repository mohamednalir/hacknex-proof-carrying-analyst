"""Analysis bodies appended after the cleaning prelude.

Each body is plain pandas code that uses the cleaned frames from the prelude
(customers, products, orders, items, rev_items) and finishes by calling emit().
Placeholders like __START__ are filled in by build_body().
"""

PERIOD = '''
START = pd.Timestamp("__START__")
END = pd.Timestamp("__END__")
LABEL = "__LABEL__"
PERIOD_ALL = __ALL__
if PERIOD_ALL:
    LABEL = "the whole dataset (%s to %s)" % (DATA_MIN.strftime("%Y-%m-%d"), DATA_MAX.strftime("%Y-%m-%d"))
PTAGS = (["no_period"] if PERIOD_ALL else []) + (["partial_period"] if __PARTIAL__ else []) + (["year_assumed"] if __YEAR_ASSUMED__ else [])
'''

REVENUE = '''
sel = in_period(rev_items)
value = round(float(sel["usd"].sum()), 2)
check = report_check(LABEL, value) if LABEL.startswith("Q") else None
emit(value, unit="USD",
     summary="Net revenue for %s is USD %s." % (LABEL, "{:,.2f}".format(value)),
     tags=PTAGS + ["revenue_def", "returns", "fx", "dedup_orders", "status_case", "discount", "dates", "orphans_in_revenue"],
     evidence={"order_lines_used": int(len(sel)), "orders_used": int(sel["order_id"].nunique())},
     extra={"period": LABEL, "cross_document": check})
'''

REVENUE_BY_CATEGORY = '''
sel = in_period(rev_items)
by = sel.groupby("category")["usd"].sum().round(2).sort_values(ascending=False)
value = {k: float(v) for k, v in by.items()}
total = round(float(sel["usd"].sum()), 2)
assert abs(sum(value.values()) - total) < 0.05
emit(value, unit="USD",
     summary="Net revenue by product category for %s (total USD %s): " % (LABEL, "{:,.2f}".format(total))
             + "; ".join("%s USD %s" % (k, "{:,.2f}".format(v)) for k, v in value.items()) + ".",
     tags=PTAGS + ["revenue_def", "returns", "fx", "dedup_orders", "status_case", "discount", "dates", "unknown_category"],
     evidence={"order_lines_used": int(len(sel)), "orders_used": int(sel["order_id"].nunique())},
     extra={"period": LABEL, "total_usd": total})
'''

REVENUE_BY_MONTH = '''
sel = in_period(rev_items)
by = sel.groupby(sel["date"].dt.strftime("%Y-%m"))["usd"].sum().round(2)
value = {k: float(v) for k, v in by.items()}
total = round(float(sel["usd"].sum()), 2)
assert abs(sum(value.values()) - total) < 0.05
emit(value, unit="USD",
     summary="Net revenue by month for %s (total USD %s): " % (LABEL, "{:,.2f}".format(total))
             + "; ".join("%s USD %s" % (k, "{:,.2f}".format(v)) for k, v in value.items()) + ".",
     tags=PTAGS + ["revenue_def", "returns", "fx", "dedup_orders", "status_case", "discount", "dates"],
     evidence={"order_lines_used": int(len(sel)), "orders_used": int(sel["order_id"].nunique())},
     extra={"period": LABEL, "total_usd": total})
'''

COUNT_ORDERS = '''
STATUS = "__STATUS__"
o = in_period(orders)
if STATUS:
    o = o[o["status"] == STATUS]
value = int(o["order_id"].nunique())
what = ("%s orders" % STATUS) if STATUS else "orders (all statuses)"
emit(value, unit="orders",
     summary="%s unique %s in %s." % ("{:,}".format(value), what, LABEL),
     tags=PTAGS + ["dedup_orders", "dates", "status_case"],
     evidence={"orders_used": value}, extra={"period": LABEL})
'''

TOP_CUSTOMERS = '''
N = __N__
sel = in_period(rev_items)
sel = sel[~sel["orphan"]]
g = sel.groupby("customer_id")["usd"].sum().sort_values(ascending=False).head(N).round(2)
names = customers.set_index("customer_id")["name"].to_dict()
value = {k: float(v) for k, v in g.items()}
emit(value, unit="USD",
     summary="Top %d customers by net spend in %s: " % (N, LABEL)
             + "; ".join("%s (%s) USD %s" % (k, names.get(k, "?"), "{:,.2f}".format(v)) for k, v in value.items()) + ".",
     tags=PTAGS + ["revenue_def", "returns", "fx", "merge_customers", "orphans_excluded", "discount", "dates"],
     evidence={"order_lines_used": int(len(sel)), "customers_ranked": int(sel["customer_id"].nunique())},
     extra={"names": {k: names.get(k) for k in value}, "period": LABEL})
'''

DISTINCT_CUSTOMERS = '''
o = in_period(orders)
o = o[~o["orphan"]]
value = int(o["customer_id"].nunique())
emit(value, unit="customers",
     summary="%d distinct customers placed at least one order in %s." % (value, LABEL),
     tags=PTAGS + ["merge_customers", "orphans_excluded", "dedup_orders", "dates"],
     evidence={"orders_used": int(o["order_id"].nunique())}, extra={"period": LABEL})
'''

AOV = '''
sel = in_period(rev_items)
per_order = sel.groupby("order_id")["usd"].sum()
value = round(float(per_order.mean()), 2)
emit(value, unit="USD",
     summary="Average order value for %s is USD %s over %d delivered or shipped orders." % (LABEL, "{:,.2f}".format(value), len(per_order)),
     tags=PTAGS + ["revenue_def", "returns", "fx", "dedup_orders", "status_case", "discount", "dates", "orphans_in_revenue"],
     evidence={"orders_used": int(len(per_order)), "order_lines_used": int(len(sel))}, extra={"period": LABEL})
'''

RETURN_RATE = '''
sel = in_period(rev_items)
sold = float(sel.loc[sel["quantity"] > 0, "quantity"].sum())
returned = float(-sel.loc[sel["quantity"] < 0, "quantity"].sum())
value = round(returned / sold * 100, 2)
emit(value, unit="percent",
     summary="%s units were returned out of %s sold in %s, a return rate of %.2f%%." % (int(returned), "{:,}".format(int(sold)), LABEL, value),
     tags=PTAGS + ["returns", "dedup_orders", "status_case", "dates"],
     evidence={"units_sold": int(sold), "units_returned": int(returned)}, extra={"period": LABEL})
'''

TOP_COUNTRY = '''
o = in_period(orders).merge(customers[["customer_id", "country"]], on="customer_id", how="left")
known = o[o["country"].notna()]
counts = known.groupby("country")["order_id"].nunique().sort_values(ascending=False)
value = str(counts.index[0])
emit(value, unit="country",
     summary="%s placed the most orders in %s (%s of %s orders with a known country)." % (
         value, LABEL, int(counts.iloc[0]), int(counts.sum())),
     tags=PTAGS + ["dedup_orders", "merge_customers", "orphans_excluded", "missing_country", "dates"],
     evidence={"orders_by_country": {k: int(v) for k, v in counts.items()}, "orders_without_country": int(len(o) - len(known))},
     extra={"period": LABEL})
'''

ORPHANS = '''
o = orders[orders["orphan"]]
value = int(o["order_id"].nunique())
emit(value, unit="orders",
     summary="%d orders reference a customer ID that does not exist in customers.csv." % value,
     tags=["dedup_orders", "merge_customers"],
     evidence={"example_order_ids": o["order_id"].head(5).tolist(), "example_customer_ids": o["customer_id"].head(5).tolist()})
'''

PREMISE = '''
YEAR = __YEAR__
BASE_M, TARGET_M = __BASE__, __TARGET__
DIRECTION = "__DIRECTION__"
BASE_NAME, TARGET_NAME = "__BASE_NAME__", "__TARGET_NAME__"
sel = rev_items.assign(month=rev_items["date"].dt.month, year=rev_items["date"].dt.year)
sel = sel[(sel["year"] == YEAR) & (sel["month"].isin([BASE_M, TARGET_M]))]
base = round(float(sel.loc[sel["month"] == BASE_M, "usd"].sum()), 2)
target = round(float(sel.loc[sel["month"] == TARGET_M, "usd"].sum()), 2)
change = round((target - base) / base * 100, 2)
holds = (target < base) if DIRECTION == "drop" else (target > base)
pivot = sel.pivot_table(index="category", columns="month", values="usd", aggfunc="sum").fillna(0)
for m in (BASE_M, TARGET_M):
    if m not in pivot.columns:
        pivot[m] = 0.0
delta = (pivot[TARGET_M] - pivot[BASE_M]).round(2).sort_values()
moves = {k: float(v) for k, v in delta.items()}
word = "higher" if change > 0 else "lower"
if holds:
    summary = ("The premise holds: %s revenue (USD %s) was %.1f%% %s than %s (USD %s). "
               % (TARGET_NAME.title(), "{:,.2f}".format(target), abs(change), word, BASE_NAME.title(), "{:,.2f}".format(base)))
    summary += "Largest category moves (USD): " + ", ".join("%s %+.0f" % (k, v) for k, v in list(moves.items())[:3] if v < 0) + ". The data cannot establish causes."
else:
    summary = ("The premise is not supported: %s revenue (USD %s) was %.1f%% %s than %s (USD %s), so there was no %s. "
               % (TARGET_NAME.title(), "{:,.2f}".format(target), abs(change), word, BASE_NAME.title(), "{:,.2f}".format(base), DIRECTION))
value = {BASE_NAME: base, TARGET_NAME: target, "premise_true": bool(holds)}
emit(value, unit="USD", summary=summary,
     tags=["revenue_def", "returns", "fx", "dedup_orders", "status_case", "discount", "dates", "causal"],
     evidence={"order_lines_used": int(len(sel))},
     extra={"change_pct": change, "category_change_usd": moves})
'''

BODIES = {
    "revenue": REVENUE,
    "revenue_by_category": REVENUE_BY_CATEGORY,
    "revenue_by_month": REVENUE_BY_MONTH,
    "count_orders": COUNT_ORDERS,
    "top_customers": TOP_CUSTOMERS,
    "distinct_customers": DISTINCT_CUSTOMERS,
    "aov": AOV,
    "return_rate": RETURN_RATE,
    "top_country": TOP_COUNTRY,
    "orphans": ORPHANS,
    "premise": PREMISE,
}
NEEDS_PERIOD = {"revenue", "revenue_by_category", "revenue_by_month", "count_orders", "top_customers",
                "distinct_customers", "aov", "return_rate", "top_country"}


def build_body(intent, params):
    body = BODIES[intent]
    if intent in NEEDS_PERIOD:
        body = PERIOD + body
    repl = {
        "__START__": params.get("start", "1900-01-01"),
        "__END__": params.get("end", "2100-01-01"),
        "__LABEL__": params.get("label", ""),
        "__ALL__": str(bool(params.get("all", False))),
        "__PARTIAL__": str(bool(params.get("partial", False))),
        "__YEAR_ASSUMED__": str(bool(params.get("year_assumed", False))),
        "__STATUS__": params.get("status", ""),
        "__N__": str(params.get("n", 5)),
        "__YEAR__": str(params.get("year", 2025)),
        "__BASE__": str(params.get("base", 1)),
        "__TARGET__": str(params.get("target", 2)),
        "__DIRECTION__": params.get("direction", "drop"),
        "__BASE_NAME__": params.get("base_name", ""),
        "__TARGET_NAME__": params.get("target_name", ""),
    }
    for k, v in repl.items():
        body = body.replace(k, v)
    return body
