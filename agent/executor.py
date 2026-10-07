"""Runs a generated answer script in a separate process and parses its result."""
import json
import os
import subprocess
import sys
import time


def run_script(path, timeout=90, data_dir=None):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if data_dir:
        env["DATA_DIR"] = str(data_dir)
    start = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(path)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout after %ss" % timeout, "runtime_s": timeout}
    runtime = round(time.time() - start, 2)
    line = None
    for out_line in proc.stdout.splitlines():
        if out_line.startswith("RESULT_JSON:"):
            line = out_line[len("RESULT_JSON:"):]
    if proc.returncode != 0 or line is None:
        err = (proc.stderr or proc.stdout or "no output").strip()
        return {"ok": False, "error": err[-1500:], "runtime_s": runtime}
    return {"ok": True, "result": json.loads(line), "runtime_s": runtime}


def same_answer(a, b, tol=1e-6):
    """Compare two answers (numbers, strings, bools, dicts) with a small tolerance."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_answer(a[k], b[k], tol) for k in a)
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
    return a == b
