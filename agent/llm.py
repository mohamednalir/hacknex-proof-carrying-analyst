"""Optional LLM code generator for questions the templates cannot handle.

Enabled when the `anthropic` package is installed and ANTHROPIC_API_KEY is set.
The model never sees the answer; it only writes pandas code against the cleaned
frames, and that code is executed and verified like any other answer script.
"""
import importlib.util
import os
import re

from . import executor

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

SYSTEM = """You are a careful data analyst writing pandas code for a retail dataset.

Your code is appended to a prelude that has ALREADY loaded and cleaned the raw files. Do not read files.
These pandas DataFrames and helpers already exist:

customers  : customer_id, name, email, country, signup_date   (duplicates merged, ids like C0005)
products   : product_id, name, category, list_price, price_currency   (category 'Unknown' if missing)
orders     : order_id, customer_id, status, currency, total_amount, payment_method, date (Timestamp), orphan (bool)
             one row per order; status is lower case; total_amount is unreliable, do not use it
items      : one row per order line with columns order_id, product_id, quantity (negative = return),
             unit_price (in the order's currency), discount (fraction), currency, status, date, customer_id,
             orphan, fx, usd (net line value in USD), category
rev_items  : items restricted to delivered and shipped orders  (this is what 'revenue' means)
FX, LOG, DATA_MIN, DATA_MAX : exchange rates, cleaning log, first and last order date
START, END : you must define these yourself (pd.Timestamp) before calling in_period(df)

Helpers:
  emit(value, unit=None, summary=None, tags=(), evidence=None, extra=None)  # report a numeric/str/dict answer
  decide("REFUSE", reason)  or  decide("CLARIFY", reason, follow_up_question)  # ends the script
  report_check(label, value)  # compares a quarter label like 'Q3 2025' with finance_report.txt
tags may include: revenue_def returns fx dedup_orders merge_customers dates discount status_case
orphans_in_revenue orphans_excluded total_amount no_period partial_period unknown_category missing_country causal

Rules:
- Data covers DATA_MIN to DATA_MAX only. If the question needs other dates, columns that do not exist
  (costs, delivery dates, cities, ...), or is truly ambiguous, answer REFUSE or CLARIFY instead of guessing.
- If the question has a false premise, check it with the data first and say so in the summary.
- Every number must come from code. Never hard-code results. Round money to 2 decimals.
- Write short, plain pandas. No file reading, no plotting, no network.

Reply in exactly this format:
DECISION: CODE   (or REFUSE or CLARIFY)
then either a ```python block with the analysis ending in emit(...), or one sentence for REFUSE/CLARIFY."""


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and importlib.util.find_spec("anthropic") is not None


def _parse(text):
    m = re.search(r"DECISION:\s*(CODE|REFUSE|CLARIFY)", text, re.I)
    kind = m.group(1).lower() if m else "code"
    if kind == "code":
        block = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
        return "code", (block.group(1) if block else "")
    rest = text[m.end():].strip() if m else text.strip()
    return kind, rest


def generate(question, info, qid, compose, answers_dir, max_attempts=3):
    import anthropic
    client = anthropic.Anthropic()
    context = "Data range: %s to %s. Question: %s" % (info["data_min"], info["data_max"], question)
    messages = [{"role": "user", "content": context}]
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        resp = client.messages.create(model=MODEL, max_tokens=2500, system=SYSTEM, messages=messages)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        kind, payload = _parse(text)
        if kind != "code":
            return {"kind": kind, "text": payload, "note": "LLM triage"}
        if not payload.strip():
            last_error = "No code block was returned."
        else:
            path = answers_dir / (qid + "_draft.py")
            path.write_text(compose(question, payload), encoding="utf-8")
            run = executor.run_script(path)
            path.unlink(missing_ok=True)
            if run["ok"]:
                return {"kind": "code", "body": payload, "note": "LLM-written code, %d attempt(s)" % attempt}
            last_error = run["error"]
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": "That code failed with:\n%s\nFix it and reply in the same format." % last_error})
    return {"kind": "clarify", "text": "The generated code kept failing (%s)" % last_error[-200:], "note": "LLM failed"}
