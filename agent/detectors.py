"""Assignment 2, Part E: three detectors, and Lecture 2's ladder. This file is yours.

Three of the four plan failures have a detector of a few lines over a trace
(Lecture 2, slides 45 to 49); the validator is the fourth. The checker calls these
on fixtures/traces/, so keep these exact signatures (checks/FORMATS.md, section
10.2):

    repeat_check(trace) -> list[list]
        Circular reasoning. Exact repeats: two tool_call lines with the same tool
        and the same arguments. Returns each group of repeats as the step numbers
        of its tool_call lines, e.g. [[1, 3], [2, 4]].

    orphan_check(plan) -> list
        Hallucinated steps. The ids of steps, other than the last, whose result no
        later step uses: no later step lists them in depends_on.

    expected_result_check(plan, trace) -> list
        Premature stopping, in part. The ids of plan steps that did not run and
        return their result. It catches skipped steps, not a plan too short.

    ladder(plan, trace) -> {"q1": {"fired": bool, "ids": [...]}, "q2": ..., "q3": ...}
        Lecture 2's questions 1 to 3 (slide 50), in order: did any two steps do
        the same thing; is any step's result never used; did every planned step
        execute. "ids" says what fired: groups of step numbers for q1, step ids
        (or, from a trace, step numbers) for q2 and q3. Question 4 needs
        judgment, so it goes in your report, not here.

    plan    a plan (section 10.1)
    trace   a list of trace lines, as harness.trace.read_trace returns them

A plan with no depends_on cannot answer question 2 from the plan. Answer it from
the trace, and say how in your report.
"""

from __future__ import annotations

import json

from agent.diff import match, plan_steps


def _calls(trace: list[dict]) -> list[dict]:
    return [r for r in trace if r.get("type") == "tool_call"]


def repeat_check(trace: list[dict]) -> list[list]:
    """Circular reasoning: the same action again, each time with a fresh reason.

    An exact repeat is two tool calls with the same tool and the same arguments.
    Hashing the call is the whole detector (Lecture 2, slide 48); the hard part was
    having recorded the arguments at all.
    """
    groups: dict[str, list] = {}
    for call in _calls(trace):
        key = json.dumps([call.get("name"), call.get("input")], sort_keys=True, default=str)
        groups.setdefault(key, []).append(call.get("step"))
    return [steps for steps in groups.values() if len(steps) > 1]


def orphan_check(plan: dict) -> list:
    """Hallucinated steps: a step that looks right but nothing needs.

    Walk the dependency graph. Every step but the last should be used by a later
    one; a step whose result is never read was not part of the task.
    """
    steps = plan_steps(plan)
    needed = set()
    for step in steps:
        for dep in step.get("depends_on") or []:
            needed.add(str(dep))
    return [s.get("id") for s in steps[:-1] if str(s.get("id")) not in needed]


def _orphans_from_trace(trace: list[dict]) -> list:
    """Question 2 for a plan with no depends_on, answered from the trace instead.

    A call's result counts as used when a later call's arguments name a path that
    call returned. The looping run was transcribed without its paths, so there is
    nothing recorded for a later call to name and no use can be shown for any of
    them. That is the honest answer, and the report says so: the one pairing a
    person would call productive is visible only because the query resembles the
    path, which is a resemblance, not a record.
    """
    calls = _calls(trace)
    used = set()
    for i, call in enumerate(calls):
        returned = call.get("paths") or []
        for later in calls[i + 1:]:
            text = json.dumps(later.get("input") or {}, default=str)
            if any(path and path in text for path in returned):
                used.add(i)
                break
    return [c.get("step") for i, c in enumerate(calls[:-1]) if i not in used]


def expected_result_check(plan: dict, trace: list[dict]) -> list:
    """Premature stopping, in part: a step that never ran and returned its result.

    This catches a plan whose steps were skipped, not a plan that was too short to
    begin with. Nothing inside a run can tell you the plan itself stopped early;
    only a test of success from outside can (Lecture 2, slide 49).
    """
    taken, _ = match(plan, trace)
    out = []
    for step in plan_steps(plan):
        call = taken.get(str(step.get("id")))
        if call is None or call.get("is_error"):
            out.append(step.get("id"))
    return out


def ladder(plan: dict, trace: list[dict]) -> dict:
    """Lecture 2's first three diagnostic questions, in order (slide 50).

    Question 4, whether the plan matched the task, is the one that needs judgment,
    so it is answered in the report rather than here.
    """
    repeats = repeat_check(trace)
    # Question 2 reads the dependency graph. A plan that records no dependencies at
    # all cannot answer it, so the trace answers it instead.
    has_depends = any("depends_on" in s for s in plan_steps(plan))
    orphans = orphan_check(plan) if has_depends else _orphans_from_trace(trace)
    unrun = expected_result_check(plan, trace)
    return {
        "q1": {"fired": bool(repeats), "ids": repeats},
        "q2": {"fired": bool(orphans), "ids": orphans},
        "q3": {"fired": bool(unrun), "ids": unrun},
    }


if __name__ == "__main__":
    raise SystemExit("Assignment 2 Part E: print both runs' ladders here, if you like")
