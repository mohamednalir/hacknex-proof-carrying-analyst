"""The agent: triage -> generate script -> execute -> re-execute -> record."""
import hashlib
import json
from pathlib import Path

from . import executor, planner, templates
from .datainfo import ROOT, dataset_info, prelude_text

ANSWERS_DIR = ROOT / "answers"
ANSWERS_JSON = ANSWERS_DIR / "answers.json"


def make_id(question):
    return "A" + hashlib.sha1(question.strip().encode("utf-8")).hexdigest()[:8]


def _compose(question, body):
    q_line = " ".join(question.split())
    head = (
        "# Auto-generated answer script. It reads the RAW csv files in ../data, cleans them,\n"
        "# computes the answer and prints one RESULT_JSON line. Run: python <this file>\n"
        "# Question: " + q_line + "\n\n"
    )
    return head + prelude_text() + "\n\n# ---- question-specific analysis ----\n" + body.strip() + "\n"


def _decision_body(decision, reason, follow_up=None):
    return "decide(%r, %r, %r)\n" % (decision, reason, follow_up)


def _load_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_result(entry):
    ANSWERS_DIR.mkdir(exist_ok=True)
    store = _load_json(ANSWERS_JSON)
    store[entry["id"]] = entry
    ANSWERS_JSON.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def answer_question(question, qid=None, use_llm=False, recheck=True, save=True):
    qid = qid or make_id(question)
    info = dataset_info()
    pl = planner.plan(question, info)
    mode = "rules"
    body = None
    llm_note = None

    if pl.kind == "QUERY" and not use_llm:
        body = templates.build_body(pl.intent, pl.params)
    elif pl.kind in ("REFUSE", "CLARIFY"):
        decision = pl.kind
        body = _decision_body(decision, pl.reason + ((" " + pl.follow_up) if pl.follow_up else ""), pl.follow_up or None)
    else:
        from . import llm
        if llm.available():
            mode = "llm"
            gen = llm.generate(question, info, qid, _compose, ANSWERS_DIR)
            if gen["kind"] == "code":
                body = gen["body"]
            else:
                body = _decision_body(gen["kind"].upper(), gen["text"], gen["text"] if gen["kind"] == "clarify" else None)
            llm_note = gen.get("note")
        elif pl.kind == "QUERY":
            body = templates.build_body(pl.intent, pl.params)
        else:
            body = _decision_body(
                "CLARIFY",
                "I could not map this question onto a supported analysis. Rephrase it, or set "
                "ANTHROPIC_API_KEY to enable free-form questions.",
                "Could you rephrase the question, e.g. as revenue, order counts, top customers or a comparison of months?",
            )

    ANSWERS_DIR.mkdir(exist_ok=True)
    script_path = ANSWERS_DIR / (qid + ".py")
    script_path.write_text(_compose(question, body), encoding="utf-8")

    run = executor.run_script(script_path)
    entry = {
        "id": qid, "question": question, "mode": mode,
        "script": "answers/%s.py" % qid, "runtime_s": run.get("runtime_s"),
    }
    if not run["ok"]:
        entry.update({"decision": "ERROR", "answer": None, "summary": "The generated script failed.",
                      "error": run["error"], "reproducible": False, "assumptions": [], "confidence": 0.0})
    else:
        entry.update(run["result"])
        reproducible = None
        if recheck:
            second = executor.run_script(script_path)
            reproducible = bool(second["ok"] and executor.same_answer(
                second["result"].get("answer"), run["result"].get("answer"))
                and second["result"].get("decision") == run["result"].get("decision"))
        entry["reproducible"] = reproducible
    if llm_note:
        entry["llm_note"] = llm_note
    if save:
        save_result(entry)
    return entry
