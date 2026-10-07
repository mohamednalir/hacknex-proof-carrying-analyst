"""Rule-based triage and planning.

Decides, before any number is computed, whether a question should be
answered, needs clarification, or must be refused, and maps answerable
questions onto an analysis template. Anything it cannot map is UNKNOWN and
can be handed to the optional LLM code generator.
"""
import calendar
import re
from dataclasses import dataclass, field
from datetime import date

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_RE = re.compile(r"\b(" + "|".join(sorted(MONTH_NAMES, key=len, reverse=True)) + r")\b")

MISSING_DATA = [
    (r"\bdeliver(y|ies)\b.*\b(time|date|speed|days)\b|\btime to deliver|\bshipping (time|duration|speed)",
     "delivery or shipping dates (orders only have an order date and a status)"),
    (r"\bcity\b|\bcities\b|\bstates?\b|\bregions?\b|\bpost ?codes?\b|\bzip\b",
     "city or region (customers only have a country column)"),
    (r"\bprofit|\bmargins?\b|\bcogs\b|cost of goods|\bcosts?\b|\bexpenses?\b",
     "cost data (there are no cost, COGS or expense columns)"),
    (r"\binventory\b|stock level|\bwarehouse|\bsupplier",
     "inventory or supplier data"),
    (r"\bmarketing\b|\badvert|\bad spend\b|\bcampaign|\bconversion|\btraffic\b|\bclicks?\b",
     "marketing or web-analytics data"),
    (r"\bemployees?\b|\bsalar(y|ies)\b|\bpayroll\b|\bstaff\b",
     "HR or payroll data"),
    (r"\breviews?\b|\bratings?\b|\bsatisfaction\b|\bnps\b",
     "customer feedback data"),
    (r"\bgender\b|\bage\b|\bincome\b",
     "customer demographic data"),
]

DIRECTION_RE = r"drop|fall|fell|decline|decrease|dip|slump|plunge|increase|rise|rose|grow|jump|spike|surge"


@dataclass
class Plan:
    kind: str                      # QUERY, REFUSE, CLARIFY, UNKNOWN
    intent: str = ""
    params: dict = field(default_factory=dict)
    reason: str = ""
    follow_up: str = ""


def _find_months(ql):
    return [MONTH_NAMES[m] for m in MONTH_RE.findall(ql)]


def _month_range(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def parse_period(ql, info):
    dmin, dmax = info["data_min"], info["data_max"]
    year_m = re.search(r"\b(20\d\d)\b", ql)
    year = int(year_m.group(1)) if year_m else dmax.year
    year_assumed = year_m is None

    single = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", ql)
    slash = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", ql)
    start = end = label = None
    if single:
        start = end = date(int(single.group(1)), int(single.group(2)), int(single.group(3)))
        label = start.isoformat()
        year_assumed = False
    elif slash and int(slash.group(1)) > 12:
        start = end = date(int(slash.group(3)), int(slash.group(2)), int(slash.group(1)))
        label = start.isoformat()
        year_assumed = False
    else:
        q = re.search(r"\bq([1-4])\b", ql)
        ordinal = re.search(r"\b(first|1st|second|2nd|third|3rd|fourth|4th)\s+quarter\b", ql)
        months = _find_months(ql)
        if q or ordinal:
            if q:
                qn = int(q.group(1))
            else:
                qn = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}[ordinal.group(1)]
            start = date(year, (qn - 1) * 3 + 1, 1)
            end = _month_range(year, qn * 3)[1]
            label = "Q%d %d" % (qn, year)
        elif months:
            start, end = _month_range(year, months[0])
            label = "%s %d" % (calendar.month_name[months[0]], year)
        elif year_m:
            start, end = date(year, 1, 1), date(year, 12, 31)
            label = str(year)
            year_assumed = False
    if start is None:
        return {"all": True, "label": "", "year_assumed": False, "partial": False, "out_of_range": False}
    return {
        "start": start.isoformat(), "end": end.isoformat(), "label": label, "all": False,
        "year_assumed": year_assumed and not single,
        "partial": end > dmax and start <= dmax,
        "out_of_range": end < dmin or start > dmax,
    }


def detect_intent(ql):
    if re.search(r"\bwhy\b", ql) and re.search(DIRECTION_RE, ql):
        return "premise"
    if "return" in ql and re.search(r"percent|%|rate|share|proportion|ratio|how many|how much", ql):
        return "return_rate"
    if re.search(r"average order value|\baov\b|average (order|basket)|avg order", ql):
        return "aov"
    if re.search(r"not exist|no matching customer|unknown customer|orphan|missing customer|not in the customer", ql):
        return "orphans"
    if re.search(r"\b(top|best|biggest|largest|highest)\b", ql) and "customer" in ql:
        return "top_customers"
    if "country" in ql and re.search(r"\bwhich\b|\bmost\b|\btop\b", ql):
        return "top_country"
    if re.search(r"(distinct|unique|different|how many) customers|number of customers|customers (placed|ordered|bought)", ql):
        return "distinct_customers"
    if "order" in ql and re.search(r"how many|number of|count|\btotal\b", ql):
        return "count_orders"
    money = r"revenue|sales|turnover|sold|income"
    if re.search(r"by month|monthly|per month|each month|month by month|month over month|trend", ql) and re.search(money, ql):
        return "revenue_by_month"
    if re.search(r"categor", ql) and re.search(money, ql):
        return "revenue_by_category"
    if re.search(r"revenue|sales|turnover|income|earn", ql):
        return "revenue"
    return None


def plan(question, info):
    ql = " ".join(question.lower().split())

    d = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", ql)
    if d:
        a, b = int(d.group(1)), int(d.group(2))
        if a <= 12 and b <= 12 and a != b:
            return Plan(
                "CLARIFY",
                reason="The date %s can be read two ways." % d.group(0),
                follow_up="Do you mean %d %s (day/month) or %d %s (month/day)? I will not guess, because the "
                          "answer differs between the two." % (
                              a, calendar.month_name[b], b, calendar.month_name[a]),
            )

    for pattern, what in MISSING_DATA:
        if re.search(pattern, ql):
            return Plan("REFUSE", reason="This cannot be answered from the data: there is no %s." % what)

    intent = detect_intent(ql)
    if intent is None:
        return Plan("UNKNOWN", reason="The question did not match any supported analysis.")

    dmin, dmax = info["data_min"], info["data_max"]
    coverage = "The data only covers %s to %s" % (dmin.isoformat(), dmax.isoformat())

    if intent == "premise":
        months = _find_months(ql)
        year_m = re.search(r"\b(20\d\d)\b", ql)
        year = int(year_m.group(1)) if year_m else dmax.year
        if not months:
            return Plan("CLARIFY", reason="No month was given.",
                        follow_up="Which month (or period) do you want me to check, and compared with which?")
        if len(months) >= 2:
            if re.search(r"\bfrom\b|\bbetween\b", ql):
                base, target = months[0], months[1]
            else:
                target, base = months[0], months[1]
        else:
            target = months[0]
            base = target - 1
            if base < 1:
                return Plan("CLARIFY", reason="No earlier month to compare with.",
                            follow_up="Which month should %s be compared with?" % calendar.month_name[target])
        last = dmax.month if year == dmax.year else (12 if year < dmax.year else 0)
        if year != dmax.year or max(base, target) > last:
            return Plan("REFUSE", reason="No data for the requested month. %s." % coverage)
        direction = "drop" if re.search(r"drop|fall|fell|decline|decrease|dip|slump|plunge", ql) else "rise"
        return Plan("QUERY", "premise", {
            "year": year, "base": base, "target": target, "direction": direction,
            "base_name": calendar.month_name[base].lower(), "target_name": calendar.month_name[target].lower(),
        })

    if intent in ("revenue", "count_orders", "aov", "return_rate", "distinct_customers") and re.search(
            r"\b(by|per|each|every)\s+(week|day|country|customer|product|payment|status|region|segment|channel)\b|\bweekly\b|\bdaily\b", ql):
        return Plan("UNKNOWN", reason="This grouping is not covered by the built-in analyses.")

    period = parse_period(ql, info)
    vague = re.search(r"\b(quarter|half|week|ytd|last|this|previous|prior|next|yesterday|today|recent|recently|lately|current)\b", ql)
    if vague and (period.get("all") or (not period.get("all") and re.fullmatch(r"\d{4}", period.get("label", "")))):
        return Plan("CLARIFY", reason="I could not tell which period you mean by '%s'." % vague.group(1),
                    follow_up="Which exact period do you mean (for example Q2 2025, March 2025, or 2025-03-27)?")
    if period.get("out_of_range"):
        return Plan("REFUSE", reason="No data for %s. %s." % (period["label"], coverage))

    params = dict(period)
    if intent == "top_customers":
        n = re.search(r"\btop\s+(\d+)\b", ql)
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}
        w = re.search(r"\btop\s+(one|two|three|four|five|ten)\b", ql)
        params["n"] = int(n.group(1)) if n else (words[w.group(1)] if w else (1 if re.search(r"\b(top|best|biggest) customer\b", ql) else 5))
    if intent == "count_orders":
        st = re.search(r"\b(delivered|shipped|cancel+ed|pending)\b", ql)
        if st:
            params["status"] = "cancelled" if st.group(1).startswith("cancel") else st.group(1)
    return Plan("QUERY", intent, params)
