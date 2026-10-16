"""Assignment 2, Part B: the validator. This file is yours.

Four checks you can run before anything executes (Lecture 2, slide 17). The checker
calls validate directly, on slide 18's specimen, on the good plans in
fixtures/plans/, and on plans of its own with one defect each, so keep this exact
signature:

    validate(plan) -> {"valid": bool, "failures": [{"step": id, "check": n}]}

    plan      a plan (checks/FORMATS.md, section 10.1)
    valid     True when nothing failed
    failures  one entry for each step and check that fails, in any order; "step"
              is the step's id, or None for check 4, which is about the whole plan

The checks, defined exactly in section 10.2:

    1  every referenced tool exists: a step's tool is in the plan's own list,
       plan["meta"]["tools"]
    2  no step depends on a later step: every id in depends_on is an earlier step's
       (a dependency on itself, or on a step that does not exist, fails too)
    3  every step has an observable outcome: a tool, and an expected_result
    4  the step count is within bounds: at least one, and at most max_steps in
       agent/bounds.yaml (agent.loop.load_bounds())

Building it is half the job. The other half is in ways/planned.py: a plan that
fails is rejected, re-planned up to your bound, then escalated. Never executed.
"""

from __future__ import annotations

from agent.loop import load_bounds


def _steps(plan: dict) -> list[dict]:
    """The steps a validator can read: the list's entries that are objects.

    Anything else in the list is not a step at all, so it is dropped rather than
    half-read. A plan whose steps are all unreadable is an empty plan, and check 4
    is what rejects it.
    """
    steps = plan.get("steps") if isinstance(plan, dict) else None
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def _allowed_tools(plan: dict) -> set[str]:
    """The plan's own tool list, from its metadata.

    Check 1 reads the plan's list, never RepoMind's, because the fixtures carry
    plans for other agents with other tools (checks/FORMATS.md, section 10.7).
    """
    meta = (plan.get("meta") or {}) if isinstance(plan, dict) else {}
    return set(meta.get("tools") or [])


def validate(plan: dict) -> dict:
    """The four checks, run before anything executes (Lecture 2, slide 17).

    One entry in failures for each step and check that fails, so a step with two
    defects is named twice. Ids are compared as text, so 2 and "2" are one step.
    """
    steps = _steps(plan)
    tools = _allowed_tools(plan)
    limit = load_bounds().max_steps

    # Where each id sits in the running order. A repeated id keeps its first position,
    # so a later copy cannot be used to satisfy an earlier dependency.
    position: dict[str, int] = {}
    for index, step in enumerate(steps):
        position.setdefault(str(step.get("id")), index)

    failures: list[dict] = []
    seen: set[tuple[str | None, int]] = set()

    def fail(step_id, check: int) -> None:
        key = (None if step_id is None else str(step_id), check)
        if key not in seen:
            seen.add(key)
            failures.append({"step": step_id, "check": check})

    for index, step in enumerate(steps):
        step_id = step.get("id")
        tool = step.get("tool")

        # 1. Every referenced tool exists. A step with no tool is not a naming
        #    mistake, it is a step with no outcome, so it falls to check 3 instead.
        if tool and tool not in tools:
            fail(step_id, 1)

        # 2. No step depends on a later step. An id that belongs to no step is
        #    treated as sitting past the end, so it fails here too, and so does a
        #    step that lists itself.
        depends_on = step.get("depends_on")
        depends_on = depends_on if isinstance(depends_on, list) else []
        if any(position.get(str(d), len(steps)) >= index for d in depends_on):
            fail(step_id, 2)

        # 3. Every step has an observable outcome: a tool to run, and a statement of
        #    what it returns when it worked. "Think about the likely cause" has neither.
        if not tool or not str(step.get("expected_result") or "").strip():
            fail(step_id, 3)

    # 4. The step count is within bounds: at least one, and no more than the loop's
    #    own step limit. This one is about the plan, so its step is None.
    if not 1 <= len(steps) <= limit:
        fail(None, 4)

    return {"valid": not failures, "failures": failures}
