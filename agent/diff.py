"""Assignment 2, Part E: the diff of the plan against what ran. This file is yours.

"The one people skip" (Lecture 2, slide 54). The checker calls it on slide 51's run
in fixtures/traces/s49/, so keep this exact signature (checks/FORMATS.md, section
10.2):

    diff(plan, trace) -> {"steps": {step_id: label}, "extra": [step numbers]}

    steps   every plan step, labelled
              executed   it ran, in plan order
              skipped    it never ran
              reordered  it ran, out of plan order
    extra   the step numbers of tool_call lines that match no plan step

How a call matches a step is yours to decide: by its tool, and by any arguments
the plan fixes (an argument written "$fill" is fixed by nothing). Say how in your
report. Mind slide 51's run: it calls run_tests twice, and only one of those calls
can belong to each run_tests step.
"""

from __future__ import annotations

import json

from harness.formats import FILL


def plan_steps(plan: dict) -> list[dict]:
    steps = plan.get("steps") if isinstance(plan, dict) else None
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def step_args(step: dict) -> dict:
    """A step's arguments, however the plan writes them: args, or args_json."""
    if isinstance(step.get("args"), dict):
        return step["args"]
    try:
        parsed = json.loads(step.get("args_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def fixed_args(step: dict) -> dict:
    """Only the arguments the plan actually decided. A "$fill" is fixed by nothing."""
    return {k: v for k, v in step_args(step).items() if v != FILL}


def match(plan: dict, trace: list[dict]) -> tuple[dict, list]:
    """Pair each traced tool call with the plan step it ran for.

    A call matches a step by `plan_step` where the line carries one, which the
    executor always writes; the recorded runs in fixtures/traces/ do not, so there
    the match is by tool and by the arguments the plan fixes. One call consumes one
    step: that is what keeps slide 51's two run_tests calls from both claiming the
    first run_tests step, and it is what makes its second identical search `extra`
    rather than a second execution of the step that already ran.

    Returns the plan step id each call was matched to, keyed by id, and the step
    numbers of the calls that matched nothing.
    """
    steps = plan_steps(plan)
    ids = {str(s.get("id")) for s in steps}
    taken: dict[str, dict] = {}
    extra: list = []

    for call in [r for r in trace if r.get("type") == "tool_call"]:
        named = call.get("plan_step")
        if named is not None and str(named) in ids and str(named) not in taken:
            taken[str(named)] = call
            continue
        chosen = None
        for step in steps:
            key = str(step.get("id"))
            if key in taken or step.get("tool") != call.get("name"):
                continue
            given = call.get("input") or {}
            if all(given.get(k) == v for k, v in fixed_args(step).items()):
                chosen = key
                break
        if chosen is None:
            extra.append(call.get("step"))
        else:
            taken[chosen] = call
    return taken, extra


def diff(plan: dict, trace: list[dict]) -> dict:
    """The plan against what ran: the comparison people skip (Lecture 2, slide 54).

    A step is executed when it ran in plan order, reordered when it ran but after a
    step that comes later in the plan, and skipped when no call ever matched it.
    """
    steps = plan_steps(plan)
    taken, extra = match(plan, trace)
    order = {str(s.get("id")): i for i, s in enumerate(steps)}

    # The plan positions of the matched steps, in the order their calls ran.
    ran = sorted(taken, key=lambda k: trace.index(taken[k]))
    reordered, highest = set(), -1
    for key in ran:
        if order[key] < highest:
            reordered.add(key)
        else:
            highest = order[key]

    labels = {}
    for step in steps:
        key = str(step.get("id"))
        if key not in taken:
            labels[key] = "skipped"
        else:
            labels[key] = "reordered" if key in reordered else "executed"
    return {"steps": labels, "extra": extra}
