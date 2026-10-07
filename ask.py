"""Ask the agent one question.

  python ask.py "What was net revenue in March 2025?"
  python ask.py --llm "Which category grew fastest from Q1 to Q2?"
"""
import argparse
import sys

from agent.core import answer_question


def show(r):
    print("=" * 72)
    print("Question  :", r["question"])
    print("Decision  :", r["decision"], "  (mode: %s, confidence: %s)" % (r.get("mode"), r.get("confidence")))
    if r["decision"] == "ERROR":
        print("Error     :", r.get("error"))
        return
    print("Response  :", r.get("summary") or r.get("answer"))
    if r.get("answer") is not None:
        print("Value     :", r["answer"], r.get("unit") or "")
    if r.get("assumptions"):
        print("Assumptions and checks:")
        for a in r["assumptions"]:
            print("  -", a)
    ev = r.get("evidence") or {}
    if r["decision"] in ("REFUSE", "CLARIFY"):
        ev = {"data_range": ev.get("data_range")}
    if ev:
        print("Evidence  :", ev)
    print("Script    :", r["script"], "(run it yourself; reproducible: %s)" % r.get("reproducible"))
    print("=" * 72)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="+")
    ap.add_argument("--llm", action="store_true", help="let the LLM write the code (needs ANTHROPIC_API_KEY)")
    args = ap.parse_args()
    show(answer_question(" ".join(args.question), use_llm=args.llm))


if __name__ == "__main__":
    main()
