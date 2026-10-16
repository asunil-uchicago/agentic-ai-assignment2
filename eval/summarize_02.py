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
TRACES = ROOT / "fixtures" / "traces"


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


def fixture_run(name: str):
    """A recorded run from fixtures/traces/: its plan and its trace."""
    from harness.trace import read_trace
    folder = TRACES / name
    return json.loads((folder / "plan.json").read_text(encoding="utf-8")), read_trace(folder / "trace.jsonl")


def ladders() -> dict | None:
    """Part E: questions 1 to 3 over both recorded runs."""
    try:
        from agent.detectors import ladder
    except Exception:
        return None
    out = {}
    for name in ("looping", "s49"):
        plan, trace = fixture_run(name)
        try:
            out[name] = ladder(plan, trace)
        except NotImplementedError:
            return None
    return out


def diff_s49() -> dict | None:
    """Part E: the diff of slide 51's plan against its trace, step ids as strings."""
    try:
        from agent.diff import diff
    except Exception:
        return None
    plan, trace = fixture_run("s49")
    try:
        got = diff(plan, trace)
    except NotImplementedError:
        return None
    return {"steps": {str(k): v for k, v in (got.get("steps") or {}).items()},
            "extra": got.get("extra") or []}


CONFIGS = ("agent", "planned_off", "planned_self", "planned_external")
EVAL_ISSUES = (4201, 4202, 4203, 4204, 4205, 4206)
UNFINISHED = ("quota", "rate_limited")


def _free(backend: str) -> bool:
    return backend == "never-stops" or str(backend).startswith("harness.scripted:")


def _configuration(start: dict) -> str | None:
    """Which of Part F's four configurations a run belongs to, or None."""
    way = start.get("way")
    if way == "agent":
        return "agent"
    if way == "planned":
        return f"planned_{start.get('critique') or 'off'}"
    return None


def load_runs() -> dict[str, list[dict]]:
    """Every finished run of this assignment on the evaluation issues, by configuration."""
    from harness.trace import read_trace

    out: dict[str, list[dict]] = {c: [] for c in CONFIGS}
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if path.name.startswith("_"):
            continue
        records = read_trace(path)
        if not records or records[0].get("type") != "run_start":
            continue
        start = records[0]
        config = _configuration(start)
        if config is None or start.get("lab") != "02" or _free(start.get("backend") or ""):
            continue
        if int(start.get("issue") or 0) not in EVAL_ISSUES:
            continue
        ends = [r for r in records if r.get("type") == "end"]
        if not any(r.get("type") == "run_end" for r in records):
            continue
        if ends and ends[-1].get("terminal_reason") in UNFINISHED:
            continue
        out[config].append({"run_id": start["run_id"], "issue": int(start["issue"]),
                            "sweep": int(start.get("sweep") or 0), "records": records})
    return out


def _mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def _nearest_rank(values, percentile):
    import math
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return None
    return ordered[max(1, math.ceil(percentile / 100 * len(ordered))) - 1]


def _prompt_tokens(records, purposes=None) -> int:
    total = 0
    for r in records:
        if r.get("type") != "model_call":
            continue
        if purposes is not None and r.get("purpose") not in purposes:
            continue
        total += (r.get("usage") or {}).get("prompt_tokens", 0)
    return total


def results() -> dict | None:
    """Part F: one entry per configuration (checks/FORMATS.md, section 10.10)."""
    try:
        import yaml
        from agent.detectors import repeat_check
        from eval.check_triage import check
        from harness.formats import parse_triage_comment, normalize_path
        from harness.tracker import Tracker
    except Exception:
        return None

    answers = {int(k): v for k, v in
               yaml.safe_load((ROOT / "fixtures" / "answers.yaml").read_text())["eval"].items()}
    tracker = Tracker(ROOT)
    runs = load_runs()

    def right(body, answer) -> bool:
        """Section 6's rule applied to one comment's text, for drafts_fixed/broken."""
        label, file = parse_triage_comment(body or "")
        return (label == (answer.get("label") or "").strip().lower()
                and file == normalize_path(answer.get("file")))

    out = {}
    for config in CONFIGS:
        mine = runs[config]
        if not mine:
            out[config] = None
            continue
        planned = config != "agent"
        second = config in ("planned_self", "planned_external")
        passed = {r["run_id"]: check(tracker, r["run_id"], r["issue"], answers[r["issue"]]) for r in mine}
        sweeps = sorted({r["sweep"] for r in mine})
        per_sweep = [sum(1 for r in mine if r["sweep"] == s and passed[r["run_id"]]) for s in sweeps]

        rounds, revisions, held, changed, fixed, broken = [], [], 0, 0, 0, 0
        repeats, off_plan, elapsed, tokens, plan_share, crit_share = 0, 0, [], [], [], []
        for r in mine:
            recs = r["records"]
            crit = [x for x in recs if x.get("type") == "critique"]
            rounds.append(len(crit))
            revisions.append(sum(1 for x in recs if x.get("type") == "revision"))
            off_plan += sum(1 for x in recs if x.get("type") == "off_plan")
            repeats += 1 if repeat_check(recs) else 0
            run_end = next((x for x in recs if x.get("type") == "run_end"), {})
            elapsed.append(run_end.get("elapsed_s"))
            tokens.append(sum((x.get("usage") or {}).get("prompt_tokens", 0)
                              + (x.get("usage") or {}).get("output_tokens", 0)
                              for x in recs if x.get("type") == "model_call"))
            whole = _prompt_tokens(recs) or 0
            plan_share.append(_prompt_tokens(recs, {"plan", "revise"}) / whole if whole else 0.0)
            crit_share.append(_prompt_tokens(recs, {"critique"}) / whole if whole else 0.0)
            posted = tracker.comments(run_id=r["run_id"])
            if crit and crit[-1].get("result") == "fail" and not posted:
                held += 1
            if any(x.get("changed") for x in crit):
                changed += 1
                first = right(crit[0].get("draft"), answers[r["issue"]])
                if not first and passed[r["run_id"]]:
                    fixed += 1
                if first and not passed[r["run_id"]]:
                    broken += 1

        out[config] = {
            "runs": len(mine),
            "passes": sum(1 for r in mine if passed[r["run_id"]]),
            "per_issue": {str(i): sum(1 for r in mine if r["issue"] == i and passed[r["run_id"]])
                          for i in EVAL_ISSUES},
            "sweep_min": min(per_sweep) if per_sweep else None,
            "sweep_max": max(per_sweep) if per_sweep else None,
            "mean_tokens": _mean(tokens),
            "p50_latency_s": _nearest_rank(elapsed, 50),
            "max_latency_s": max([e for e in elapsed if e is not None], default=None),
            "plan_overhead_share": _mean(plan_share) if planned else None,
            "critique_overhead_share": _mean(crit_share) if second else None,
            "runs_with_repeat": repeats,
            "off_plan": off_plan if planned else None,
            "revisions_mean": _mean(revisions) if planned else None,
            "revisions_max": max(revisions) if planned else None,
            "rounds_mean": _mean(rounds) if second else None,
            "rounds_max": max(rounds) if second else None,
            "drafts_changed": changed if second else None,
            "drafts_fixed": fixed if second else None,
            "drafts_broken": broken if second else None,
            "drafts_held": held if second else None,
        }
    return out


NOTES_ISSUES = (4203, 4204, 4206)


def context() -> list[dict] | None:
    """Part G: one entry per notes run on the evaluation issues, and no other.

    Every field is read back off the trace. A path counts as seen when a tool_call
    line above the question has it in its paths, which is what the run actually did,
    never what the model answered.
    """
    from harness.trace import read_trace

    out = []
    for path in sorted((ROOT / "runs").glob("notes-*.jsonl")):
        records = read_trace(path)
        if not records or records[0].get("type") != "run_start":
            continue
        start = records[0]
        if int(start.get("issue") or 0) not in NOTES_ISSUES:
            continue                      # a notes run on a development issue is development
        if not any(r.get("type") == "run_end" for r in records):
            continue
        ends = [r for r in records if r.get("type") == "end"]
        if ends and ends[-1].get("terminal_reason") in UNFINISHED:
            continue

        seen: list[str] = []
        compacted, asked, questions = False, False, []
        for line in records:
            kind = line.get("type")
            if kind == "tool_call":
                seen += [p for p in line.get("paths") or [] if p not in seen]
            elif kind == "compaction" and not asked:
                compacted = True
            elif kind == "question":
                asked = True
                questions.append({
                    "path": line.get("path"),
                    "truth": "yes" if line.get("path") in seen else "no",
                    "answer": line.get("answer"),
                })
        out.append({
            "run_id": start["run_id"],
            "issue": int(start["issue"]),
            "notes_shown": start.get("notes") == "on",
            "compacted": compacted,
            "questions": questions,
            "right": sum(1 for q in questions if q["answer"] == q["truth"]),
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

    rungs = ladders()
    if rungs is None:
        skipped.append("ladder (agent/detectors.py is not written yet)")
    else:
        report["ladder"] = rungs
        wrote.append("ladder (looping, s49)")

    s49 = diff_s49()
    if s49 is None:
        skipped.append("diff_s49 (agent/diff.py is not written yet)")
    else:
        report["diff_s49"] = s49
        wrote.append("diff_s49")

    table = results()
    if table is None:
        skipped.append("results (eval/check_triage.py or agent/detectors.py is not ready)")
    else:
        for config, entry in table.items():
            if entry is not None:
                report["results"][config] = entry
        done = [c for c, e in table.items() if e]
        wrote.append(f"results ({', '.join(done) if done else 'no finished runs yet'})")

    entries = context()
    if entries is None:
        skipped.append("context")
    else:
        report["context"] = entries
        wrote.append(f"context ({len(entries)} notes runs)")

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
