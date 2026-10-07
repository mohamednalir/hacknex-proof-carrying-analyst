"""Independent verifier: re-runs every saved answer script and checks it gives the same answer.

For each answer in answers/answers.json it copies the script and the raw data
into a brand-new temporary folder, runs the script there with a fresh Python
process, and compares the number it prints with the number the agent reported.
If anything differs, the answer is not proven and this exits with an error.

  python verify.py            verify every saved answer
  python verify.py Q03 Q04    verify only these ids
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

from agent.datainfo import ROOT
from agent.executor import run_script, same_answer


def verify(ids=None):
    store = json.loads((ROOT / "answers" / "answers.json").read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shutil.copytree(ROOT / "data", tmp / "data")
        (tmp / "answers").mkdir()
        for qid, entry in sorted(store.items()):
            if ids and qid not in ids:
                continue
            src = ROOT / entry["script"]
            dst = tmp / "answers" / src.name
            shutil.copy(src, dst)
            run = run_script(dst)
            if not run["ok"]:
                results.append((qid, False, "script failed: " + run["error"][-120:]))
                continue
            new = run["result"]
            ok = new.get("decision") == entry.get("decision") and same_answer(new.get("answer"), entry.get("answer"))
            results.append((qid, ok, "re-run gives %s" % (json.dumps(new.get("answer"))[:60],)))
    return results


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ids = set(sys.argv[1:]) or None
    results = verify(ids)
    for qid, ok, msg in results:
        print("%-10s %-8s %s" % (qid, "VERIFIED" if ok else "MISMATCH", msg))
    good = sum(ok for _, ok, _ in results)
    print("-" * 60)
    print("%d / %d answers re-proven in a clean folder" % (good, len(results)))
    sys.exit(0 if good == len(results) else 1)


if __name__ == "__main__":
    main()
