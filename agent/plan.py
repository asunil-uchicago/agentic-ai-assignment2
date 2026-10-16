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
REVISER_PROMPT = "prompts/reviser.md"
PLAN_TOOL = "submit_plan"

# What a reviser is allowed to see of a step. Never args_json: the executor fills a
# search term in from the issue's text, so arguments are untrusted text in disguise.
REVISABLE_FIELDS = ("id", "action", "tool", "depends_on", "expected_result", "status")

# What a reviser is allowed to see of a step result (section 10.3, less its args).
RESULT_FIELDS = ("id", "tool", "status", "count", "paths", "error_code")

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


def _pick(source: dict, fields) -> dict:
    return {f: source.get(f) for f in fields if f in source}


def _redacted(plan: dict, step_results: list[dict]) -> tuple[list[dict], list[dict]]:
    """The plan and its results with every value that could carry issue text removed.

    Two things are stripped. A step's args_json, because the executor fills a search
    term into it from the issue, and a step result's args, for the same reason
    (section 10.3 says so in as many words). What is left is structure and outcomes:
    ids, tools, actions the planner wrote before it had read anything, statuses,
    counts, repository paths and error codes.
    """
    steps = [_pick(s, REVISABLE_FIELDS) for s in (plan.get("steps") or []) if isinstance(s, dict)]
    results = [_pick(r, RESULT_FIELDS) for r in (step_results or []) if isinstance(r, dict)]
    return steps, results


def _merge(old: dict, new: dict) -> list[dict]:
    """The revised steps, with every finished step put back as it was.

    Repair before replace. A step whose status is done comes back unchanged in every
    field but status, whatever the model wrote, and is restored to its old place if
    the model dropped it. A step that failed may be changed, and a change puts it
    back to pending so the executor runs it again; a failed step the model left alone
    stays failed, and the run stops on it.

    A step's args_json is carried over from the old plan whenever the tool is
    unchanged, because the reviser was never shown the arguments and so cannot write
    them back. Only a step whose tool actually changed takes the model's arguments.
    """
    old_steps = [s for s in (old.get("steps") or []) if isinstance(s, dict)]
    by_id = {str(s.get("id")): s for s in old_steps}
    merged: list[dict] = []

    for step in (new.get("steps") or []):
        if not isinstance(step, dict):
            continue
        was = by_id.get(str(step.get("id")))
        if was is None:
            merged.append(step)                       # a step the revision added
            continue
        if was.get("status") == "done":
            merged.append(dict(was))                  # finished: unchanged, whatever was written
            continue
        kept = dict(step)
        if step.get("tool") == was.get("tool") and "args_json" in was:
            kept["args_json"] = was["args_json"]
        changed = any(kept.get(f) != was.get(f) for f in REVISABLE_FIELDS if f != "status")
        if was.get("status") == "failed":
            kept["status"] = "pending" if changed else "failed"
        else:
            kept["status"] = was.get("status", "pending")
        merged.append(kept)

    # A finished step the revision dropped goes back where it was.
    present = {str(s.get("id")) for s in merged}
    for index, step in enumerate(old_steps):
        if step.get("status") == "done" and str(step.get("id")) not in present:
            merged.insert(min(index, len(merged)), dict(step))
    return merged


def revise_plan(client, plan: dict, step_results: list[dict], trace=None) -> dict:
    """Repair the active plan from what its steps returned (Lecture 2, slide 16).

    The request carries structured results only: no issue text, and no argument the
    executor filled in from the issue. Reading the issue here would plan better, and
    would let text a stranger wrote reshape the plan rather than merely fill it in.
    """
    steps, results = _redacted(plan, step_results)
    system = (ROOT / REVISER_PROMPT).read_text(encoding="utf-8")
    messages = [{
        "role": "user",
        "content": (
            "The plan so far, with its arguments withheld:\n\n"
            f"{json.dumps(steps, indent=1)}\n\n"
            "What each step that has run returned:\n\n"
            f"{json.dumps(results, indent=1)}\n\n"
            "Repair the plan. Leave every step whose status is done exactly as it is."
        ),
    }]
    response = client.create(system=system, messages=messages, tools=[plan_tool_definition()])
    if trace is not None:
        trace.model_call(0, response, purpose="revise")

    meta = dict(plan.get("meta") or {})
    meta["model"] = response.model
    meta["prompt"] = REVISER_PROMPT
    revised = _read_plan(response, meta)
    revised["steps"] = _merge(plan, revised)
    return revised
