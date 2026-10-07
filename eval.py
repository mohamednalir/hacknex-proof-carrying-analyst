"""Run the agent on every question in eval/answer_key.json and score it.

  python eval.py            full run, writes reports/eval_report.md and .json
  python eval.py --llm      let the LLM write code instead of templates
"""
import argparse
import json
import sys

from agent.core import answer_question
from agent.datainfo import ROOT
from agent.executor import same_answer

CLASS = {"ANSWER": "answer", "ANSWER_WITH_ASSUMPTIONS": "answer", "REFUSE": "refuse", "CLARIFY": "clarify"}


def close(a, b):
    """Numbers within 0.5% (or 0.01), dicts key by key, everything else equal."""
    if isinstance(b, dict):
        if not isinstance(a, dict):
            return False
        return all(k in a and close(a[k], v) for k, v in b.items())
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= max(0.01, 0.005 * abs(b))
    return a == b


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    args = ap.parse_args()

    key = json.loads((ROOT / "eval" / "answer_key.json").read_text(encoding="utf-8"))
    rows, passed = [], 0
    for q in key:
        r = answer_question(q["question"], qid=q["id"], use_llm=args.llm)
        want = CLASS[q["expected_behavior"]]
        got = CLASS.get(r["decision"], "error")
        ok_decision = want == got
        ok_value = True
        if want == "answer" and "expected_answer" in q:
            ok_value = close(r.get("answer"), q["expected_answer"])
        ok_repro = bool(r.get("reproducible"))
        ok = ok_decision and ok_value and ok_repro
        passed += ok
        rows.append({
            "id": q["id"], "question": q["question"], "expected": q["expected_behavior"], "got": r["decision"],
            "decision_ok": ok_decision, "value_ok": ok_value, "reproducible": ok_repro, "pass": ok,
            "agent_answer": r.get("answer"), "expected_answer": q.get("expected_answer"),
        })
        print("%-4s %-4s %-24s -> %-24s value:%-5s repro:%s" % (
            q["id"], "PASS" if ok else "FAIL", q["expected_behavior"], r["decision"], ok_value, ok_repro))

    n = len(rows)
    answerable = [r for r in rows if r["expected"] in ("ANSWER", "ANSWER_WITH_ASSUMPTIONS")]
    refusals = [r for r in rows if r["expected"] in ("REFUSE", "CLARIFY")]
    print("-" * 72)
    print("Overall            : %d / %d" % (passed, n))
    print("Answerable correct : %d / %d" % (sum(r["pass"] for r in answerable), len(answerable)))
    print("Refuse/clarify OK  : %d / %d" % (sum(r["pass"] for r in refusals), len(refusals)))

    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "eval_report.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    md = ["# Evaluation report", "", "Overall: **%d / %d**" % (passed, n), "",
          "| ID | Question | Expected | Got | Value | Reproducible | Result |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["question"], r["expected"], r["got"], "ok" if r["value_ok"] else "WRONG",
            "yes" if r["reproducible"] else "NO", "PASS" if r["pass"] else "FAIL"))
    (out / "eval_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    sys.exit(0 if passed == n else 1)


if __name__ == "__main__":
    main()
