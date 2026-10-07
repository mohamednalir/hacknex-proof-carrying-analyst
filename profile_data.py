"""Scan the raw data and print a data-health report (also saved to reports/data_health.json)."""
import json
import sys

from agent.profiler import profile, render
from agent.datainfo import ROOT


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    findings = profile()
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "data_health.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(render(findings))


if __name__ == "__main__":
    main()
