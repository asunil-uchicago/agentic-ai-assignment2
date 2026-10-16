"""Assignment 2: build reports/LAB_02.json from the repository and the runs.

Nothing in that file is filled by hand. This script writes every section it can
compute, and leaves the rest as it found it, so it is safe to run at any point:

    python -m eval.summarize_02

    fixture_validation  Part B: agent.validator.validate over fixtures/plans/
    ladder, diff_s49    Part E: agent.detectors and agent.diff over fixtures/traces/
    results             Part F: one entry per configuration, from runs/ and the tracker
    context             Part G: one entry per notes run on the evaluation issues

Every definition is checks/FORMATS.md, section 10.10. A section whose code is not
written yet is skipped with a note, not guessed at.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / "LAB_02.json"
PLANS = ROOT / "fixtures" / "plans"


def fixture_validation() -> list[dict] | None:
    """Part B: every plan in fixtures/plans/, as validate returns it.

    One entry per file, in name order, so the table in the report and this list are
    read the same way round.
    """
    try:
        from agent.validator import validate
    except Exception:
        return None
    out = []
    for path in sorted(PLANS.glob("*.json")):
        plan = json.loads(path.read_text(encoding="utf-8"))
        try:
            verdict = validate(plan)
        except NotImplementedError:
            return None
        out.append({
            "plan": path.name,
            "valid": verdict["valid"],
            "failures": verdict["failures"],
        })
    return out


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    wrote, skipped = [], []

    fixtures = fixture_validation()
    if fixtures is None:
        skipped.append("fixture_validation (agent/validator.py is not written yet)")
    else:
        report["fixture_validation"] = fixtures
        wrote.append(f"fixture_validation ({len(fixtures)} plans)")

    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    for line in wrote:
        print("wrote   ", line)
    for line in skipped:
        print("skipped ", line)

    for entry in report.get("fixture_validation") or []:
        if not isinstance(entry, dict) or entry.get("valid") is None:
            continue
        failures = ", ".join(f"({f['step']}, {f['check']})" for f in entry["failures"]) or "none"
        print(f"  {entry['plan']:<24} valid={str(entry['valid']):<5} failures: {failures}")


if __name__ == "__main__":
    main()
