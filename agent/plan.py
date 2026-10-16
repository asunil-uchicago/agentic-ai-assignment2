"""Assignment 2, Parts A and C: the planner and the reviser. This file is yours.

The contract (checks/FORMATS.md, section 10). The checker calls both functions
directly, with a scripted model that keeps a copy of every request, so keep these
exact signatures. You may add keyword arguments with defaults; the checker passes
only these.

    make_plan(client, issue_number, tool_schemas, trace=None) -> dict
    revise_plan(client, plan, step_results, trace=None) -> dict

    client        harness.client.ModelClient: client.create(system=, messages=, tools=)
    issue_number  the issue to triage, an int
    tool_schemas  the tool definitions, as ctx.tools.schemas gives them
    plan          the active plan, its steps' statuses brought up to date
    step_results  one entry per step that has run (section 10.3)
    trace         a harness.trace.TraceWriter, or None. When you get one, trace your
                  model call: trace.model_call(0, response, purpose="plan") in
                  make_plan, purpose="revise" in revise_plan
    returns       a plan (section 10.1): {"meta": {...}, "steps": [...]}

make_plan writes the plan and stops (Lecture 2, slide 15). Its request carries the
task, the issue number and the tool list, and nothing from the issue: not its body,
not its title. The checker looks for each issue's sentinel string in every request.
The usual way to get the plan back as data: offer the model one tool whose
input_schema is agent/plan_schema.json, and read the plan from its call. Mark an
argument that waits on an earlier step's result "$fill"; the executor fills it in.

revise_plan repairs before it replaces: it never changes a step whose status is
done; it may change a step that failed, to retry it, and any step not yet run. A
step whose step result says "done" comes back unchanged, every field but status,
whatever the model wrote. Its request carries structured step results only (status, counts, paths,
error codes): never the issue's text, and never a step result's `args`, which the
executor may have filled in from the issue.

Keep your prompts in prompts/.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.formats import FILL

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "agent" / "plan_schema.json"

PLANNER_PROMPT = "prompts/planner.md"
PLAN_TOOL = "submit_plan"

# Whether the plan tool goes out marked "strict": true. OpenAI and Anthropic both have
# a strict mode, and the harness passes the flag through to the vendor
# (harness/backends.py). A vendor accepting a strict request is not the same as it
# enforcing the schema, which is why ways/planned.py checks every plan anyway.
STRICT = True


def load_schema() -> dict:
    """agent/plan_schema.json, as the planner's tool offers it.

    The checker requires the tool's input_schema to be this file's content exactly,
    so it is loaded and passed through untouched.
    """
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def without_meta(plan: dict) -> dict:
    """The part of a plan the schema describes: everything our own code did not add."""
    return {key: value for key, value in (plan or {}).items() if key != "meta"}


def plan_tool_definition() -> dict:
    """The one tool a planner or reviser is offered: its input is a whole plan."""
    tool = {
        "name": PLAN_TOOL,
        "description": "Submit the plan. Call this exactly once, with every step in the order it runs.",
        "input_schema": load_schema(),
    }
    if STRICT:
        tool["strict"] = True
    return tool


def _normalize_fills(plan: dict) -> dict:
    """Make every blank the whole value, as section 10.1 defines a blank.

    A blank is the string "$fill" and nothing else: "any other value is fixed by the
    plan". Models write templates anyway. gpt-4o-mini, told twice and shown the wrong
    form, still returns a comment body of "label: $fill\\nfile: $fill", which the
    executor would read as a value the plan had already decided and post word for
    word. A prompt is a request, not a control (prompts/README.md), so the convention
    is enforced here: a string argument that contains "$fill" becomes "$fill".

    Only argument values are touched. A step's other fields come back as the model
    wrote them, so the schema check in ways/planned.py still sees any damage.
    """
    for step in plan.get("steps") or []:
        if not isinstance(step, dict) or not isinstance(step.get("args_json"), str):
            continue
        try:
            args = json.loads(step["args_json"])
        except (TypeError, ValueError):
            continue          # not JSON: the schema check and the executor deal with it
        if not isinstance(args, dict):
            continue
        fixed = {k: (FILL if isinstance(v, str) and FILL in v else v) for k, v in args.items()}
        if fixed != args:
            step["args_json"] = json.dumps(fixed)
    return plan


def _read_plan(response, meta: dict) -> dict:
    """The plan a response carries, with our meta attached.

    A response with no call to the plan tool is a planner that answered in prose. It
    comes back as a plan with no steps, which fails check 4 and is rejected like any
    other bad plan: we never try to parse a plan out of free text.

    Whatever the model did put in the call is kept exactly as it wrote it, extra
    properties and missing fields included, so that the schema check in
    ways/planned.py is what catches them.
    """
    calls = [c for c in response.tool_calls if c.name == PLAN_TOOL]
    plan = {"meta": meta}
    if calls and isinstance(calls[0].input, dict):
        plan.update(without_meta(calls[0].input))
    plan.setdefault("steps", [])
    return _normalize_fills(plan)


def make_plan(client, issue_number: int, tool_schemas: list[dict], trace=None) -> dict:
    """Write the plan for one issue, then stop (Lecture 2, slide 15).

    The request carries the task, the issue number and the tool list, and nothing
    from the issue itself, so the list of steps is fixed before any text a stranger
    wrote reaches the run. An argument that depends on what a step finds is left as
    "$fill" for the executor.
    """
    system = (ROOT / PLANNER_PROMPT).read_text(encoding="utf-8")
    messages = [{
        "role": "user",
        "content": (
            f"Write the plan for triaging issue #{issue_number}.\n\n"
            f"You have not read this issue and you will not be shown it. Wherever an "
            f"argument depends on what an earlier step finds, write \"$fill\". The "
            f"issue number, {issue_number}, is the one value you know: write it out."
        ),
    }]
    response = client.create(system=system, messages=messages, tools=[plan_tool_definition()])
    if trace is not None:
        trace.model_call(0, response, purpose="plan")
    meta = {
        "model": response.model,
        "prompt": PLANNER_PROMPT,
        "tools": [t["name"] for t in tool_schemas],
    }
    return _read_plan(response, meta)


def revise_plan(client, plan: dict, step_results: list[dict], trace=None) -> dict:
    raise NotImplementedError("Assignment 2 Part C: the reviser")
