"""Loads the cleaning prelude once, in-process, to learn the dataset's shape."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRELUDE_PATH = Path(__file__).resolve().parent / "clean_prelude.py"
_CACHE = {}


def prelude_text():
    return PRELUDE_PATH.read_text(encoding="utf-8")


def load_namespace(force=False):
    """Run the prelude and return its namespace (cleaned frames, LOG, FX, ...)."""
    if "ns" in _CACHE and not force:
        return _CACHE["ns"]
    ns = {"__file__": str(ROOT / "answers" / "_info.py"), "__name__": "prelude_info"}
    code = compile(prelude_text(), str(PRELUDE_PATH), "exec")
    exec(code, ns)
    _CACHE["ns"] = ns
    return ns


def dataset_info():
    ns = load_namespace()
    return {
        "data_min": ns["DATA_MIN"].date(),
        "data_max": ns["DATA_MAX"].date(),
        "log": ns["LOG"],
        "columns": {
            "customers": list(ns["customers"].columns),
            "products": list(ns["products"].columns),
            "orders": list(ns["orders"].columns),
            "items": list(ns["items"].columns),
        },
    }
