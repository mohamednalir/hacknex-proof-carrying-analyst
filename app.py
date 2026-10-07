"""Streamlit demo UI.   Run:  streamlit run app.py   (or: py -m streamlit run app.py)"""
import json
import os

import streamlit as st

from agent import profiler
from agent.core import answer_question
from agent.datainfo import ROOT
from agent.executor import run_script, same_answer

st.set_page_config(page_title="Proof-Carrying Data Analyst", layout="wide")

SAMPLES = [
    "What was net revenue in March 2025?",
    "What was total revenue for Q3 2025?",
    "Who are the top 5 customers by net spend?",
    "What was Q2 2025 revenue by product category?",
    "Monthly revenue trend",
    "What percentage of units sold were returned?",
    "Why did sales drop in June compared to May?",
    "What was the revenue on 04/05/2025?",
    "What was revenue in Q4 2025?",
    "What is our profit margin?",
]

BADGE = {
    "ANSWER": ("success", "ANSWER"),
    "ANSWER_WITH_ASSUMPTIONS": ("success", "ANSWER (with stated assumptions)"),
    "CLARIFY": ("warning", "NEEDS CLARIFICATION"),
    "REFUSE": ("error", "CANNOT BE DETERMINED FROM THE DATA"),
    "ERROR": ("error", "SCRIPT ERROR"),
}

st.title("Proof-Carrying Data Analyst")
st.caption("Every number comes with a script you can re-run. If the data cannot support an answer, the agent says so.")

with st.sidebar:
    st.header("Try a question")
    for i, s in enumerate(SAMPLES):
        if st.button(s, key="sample%d" % i, use_container_width=True):
            st.session_state["question"] = s
    use_llm = st.checkbox("Let the LLM write the code", value=False,
                          disabled=not os.environ.get("ANTHROPIC_API_KEY"),
                          help="Needs ANTHROPIC_API_KEY and the anthropic package. Off = built-in analyses.")
    st.divider()
    if st.button("Show data health report", use_container_width=True):
        st.session_state["show_health"] = not st.session_state.get("show_health", False)

if st.session_state.get("show_health"):
    st.subheader("Data health report (raw files)")
    findings = profiler.profile()
    st.dataframe([{"table": f["table"], "issue": f["issue"], "count": f["count"], "fix": f["fix"]} for f in findings],
                 use_container_width=True, hide_index=True)

question = st.text_input("Ask a question about the sales data", key="question",
                         placeholder="e.g. What was net revenue in March 2025?")

if st.button("Ask", type="primary") and question.strip():
    with st.spinner("Writing and running the analysis script..."):
        st.session_state["result"] = answer_question(question.strip(), use_llm=use_llm)

r = st.session_state.get("result")
if r:
    kind, label = BADGE.get(r["decision"], ("info", r["decision"]))
    getattr(st, kind)("**%s**   |   confidence %.2f   |   mode: %s" % (label, r.get("confidence", 0), r.get("mode")))
    if r["decision"] == "ERROR":
        st.code(r.get("error", ""))
    else:
        st.subheader("Response")
        st.write(r.get("summary") or "")
        if r.get("answer") is not None:
            ans = r["answer"]
            if isinstance(ans, dict):
                st.table({"item": list(ans.keys()), "value": [str(v) for v in ans.values()]})
            else:
                st.metric(r.get("unit") or "answer", ans if isinstance(ans, str) else "{:,}".format(ans))

        if r.get("assumptions"):
            st.subheader("Assumptions and checks applied")
            for a in r["assumptions"]:
                (st.warning if a.startswith("CONFLICT") else st.markdown)(("- " if not a.startswith("CONFLICT") else "") + a)

        cols = st.columns(2)
        with cols[0]:
            st.subheader("Evidence")
            ev = r.get("evidence", {})
            st.json(ev if r["decision"] not in ("REFUSE", "CLARIFY") else {"data_range": ev.get("data_range")})
        with cols[1]:
            st.subheader("Data problems found while cleaning")
            st.json({k: v for k, v in (r.get("data_quality") or {}).items() if v})

        st.subheader("Proof: the script behind this answer")
        script = (ROOT / r["script"]).read_text(encoding="utf-8")
        st.caption("%s - %s" % (r["script"], "re-run twice with identical results" if r.get("reproducible") else "not yet confirmed reproducible"))
        with st.expander("Show script"):
            st.code(script, language="python")
        if st.button("Re-run this script now and compare"):
            run = run_script(ROOT / r["script"])
            if run["ok"] and same_answer(run["result"].get("answer"), r.get("answer")):
                st.success("Verified: the script printed the same answer again (%s s)." % run["runtime_s"])
            else:
                st.error("Mismatch or failure: %s" % (run.get("error") or "answers differ"))
