"""Way 5, planned: RepoMind with a plan it cannot quietly abandon. This file is yours.

Assignment 2, Parts B, C and D. Like every way, run(ctx) -> None (see ways/__init__.py):

    python run.py --way planned --set dev
    python run.py --way planned --critique self --set dev      # or external; off is the default

The run, in order (checks/FORMATS.md, section 10):

  1. Plan: agent.plan.make_plan(ctx.client, ctx.issue_number, ctx.tools.schemas,
     trace=ctx.trace). The planner never sees the issue.
  2. Check, then validate. First the plan against agent/plan_schema.json, with
     harness.schema.errors (a vendor may accept "strict" and not enforce it), and
     that its last step is post_comment (a plan without one passes the four checks
     and posts nothing); a plan that breaks either writes
     ctx.trace.event("schema", errors=...). Then agent.validator.validate(plan). A
     plan that fails any of these is rejected and re-planned, at most MAX_REPLANS
     times; then the run escalates: ctx.trace.end("escalated", detail), no tool
     call, nothing posted.
  3. Log: ctx.trace.plan(1, plan), before the first tool call.
  4. Execute the steps in order, each tool call through ctx.call_tool, naming the
     plan step it runs for: ctx.call_tool(n, tool, args, plan_step=step["id"]). Where a step
     has arguments marked "$fill", one model call fills them in: offer it that
     step's tool alone, and trace it with ctx.trace.model_call(n,
     response, purpose="execute"). Act on the tool calls a response holds,
     whatever its stop_reason says. The executor may run, retry or halt a step; it
     may not add, drop or reorder one. A call that is not the current step's tool
     never runs: refuse it and write ctx.trace.event("off_plan", step=..., tool=...).
  5. Part C: revise only at one checkpoint, after a search step: the first search
     step, and any search step a revision added or changed, until MAX_REVISIONS is
     spent; and only when the check there fails (a check in code, not in a prompt,
     such as "the search returned at least one source file, not only documentation
     or translations"): revise_plan, which never changes a step that is done but may
     change a failed one to retry it, then check the new version against the schema
     and validate it, write
     ctx.trace.event("revision", checkpoint=..., version=..., valid=...), and log a
     valid one with ctx.trace.plan(version, plan). A revision that fails the
     validator never runs, and counts against the bound.
  6. Part D: before post_comment, the second pass, in the mode ctx.critique names
     (off, self or external), at most MAX_ROUNDS rounds. A round checks the
     current draft (agent.critique.verify, or agent.critique.self_critique) and
     writes ctx.trace.event("critique", round=..., mode=..., result="pass" or
     "fail", reason=..., changed=..., draft=...). A draft that fails, with a round
     left, is rewritten by one model call given the reason, traced with
     purpose="critique", and the next round checks the new draft. A draft still
     failing in the last round is held: not posted, and the run ends escalated.
     Nothing is posted until the last round, and a run posts one comment at most.

The comment is Assignment 1's: two lines, label: and file: (section 1). A run that
finishes its plan can leave its ending to the runner, which writes completed.

Part G's ways/notes.py extends this way without changing it, so build this one with
hooks it can override: for example an executor class whose methods run after every
step, build what each model call sees, and run before the comment.

The checker reads MAX_REPLANS, MAX_REVISIONS and MAX_ROUNDS from this module, and
runs this way against scripted models (harness/scripted.py). You can run them too,
free:

    python run.py --way planned --backend harness.scripted:AlwaysInvalidPlanner --set dev
    python run.py --way planned --backend harness.scripted:OffPlanExecutor --set dev
    python run.py --way planned --critique external --backend harness.scripted:DraftNamesUnseenFile --set dev
"""

from __future__ import annotations

import json

from agent.plan import load_schema, make_plan, without_meta
from agent.validator import validate
from harness.formats import FILL, result_paths
from harness.schema import errors

MAX_REPLANS = 2        # Part B: so a run makes at most three planner calls
MAX_REVISIONS = 2      # Part C: revisions a run, accepted and rejected alike
MAX_ROUNDS = 2         # Part D: second-pass rounds a run, the same in both modes

EXECUTOR_PROMPT = "executor.md"

# A step that has run cannot be picked up again, so the executor always moves forward.
# This only guards against a plan that somehow leaves a step pending for ever.
MAX_STEP_RUNS = 32


def _result_count(tool: str, content: str, is_error: bool):
    """How many results a step returned, or None where that is not a count."""
    if is_error:
        return 0
    if tool == "search_repo":
        if content.strip() == "No matches.":
            return 0
        return len([line for line in content.splitlines() if line.strip()])
    return None


class PlannedRun:
    """RepoMind held to a plan it cannot quietly abandon.

    Part G's ways/notes.py subclasses this, so everything it needs to change is a
    method: what a model call sees (executor_messages), what happens after each step
    (after_step), and what happens at the very end (finish).
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.schema = load_schema()
        self.plan: dict | None = None
        self.version = 0
        self.step = 0                  # model calls, numbered as Assignment 1's loop does
        self.replans = 0
        self.revisions = 0
        self.results: list[dict] = []        # step_results, checks/FORMATS.md section 10.3
        self.outputs: dict[str, str] = {}    # what each step returned, for the next call
        self.issue_text: str | None = None
        self._ended = False

    # -- endings ---------------------------------------------------------------------
    def end(self, reason: str, detail: str = "") -> None:
        """End the run once. A way that finishes its plan leaves this to the runner."""
        if not self._ended:
            self._ended = True
            self.ctx.trace.end(reason, detail)

    # -- the plan --------------------------------------------------------------------
    def acceptable(self, plan: dict, version: int) -> bool:
        """Everything that must hold before a plan is allowed to run.

        The schema first, because a vendor can accept "strict" and not enforce it;
        then the rule that a plan ends by posting, since a plan without a final
        post_comment passes all four checks and decides nothing; then the four checks.
        """
        problems = errors(without_meta(plan), self.schema)
        if not problems:
            steps = plan.get("steps") or []
            last = steps[-1].get("tool") if steps and isinstance(steps[-1], dict) else None
            if last != "post_comment":
                problems = [f"the plan's last step is {last!r}, and a plan must end with post_comment"]
        if problems:
            self.ctx.trace.event("schema", errors=problems, version=version)
            return False
        return bool(validate(plan)["valid"])

    def first_plan(self) -> dict | None:
        """Plan, and re-plan a rejected plan, up to the bound. None means escalate.

        A rejected plan never runs: no tool has been called at this point, and none
        will be unless a plan gets past every check here.
        """
        for attempt in range(MAX_REPLANS + 1):
            self.replans = attempt
            plan = make_plan(self.ctx.client, self.ctx.issue_number,
                             self.ctx.tools.schemas, trace=self.ctx.trace)
            if self.acceptable(plan, version=1):
                return plan
        return None

    # -- what a model call sees ------------------------------------------------------
    def system_prompt(self) -> str:
        return self.ctx.prompt(EXECUTOR_PROMPT)

    def executor_messages(self, step: dict, blanks: list[str]) -> list[dict]:
        """The issue, and the results of the steps this one declares it depends on.

        Not everything the run has seen. The issue is already untrusted by the time
        the executor runs, so narrowing to the declared dependencies costs nothing in
        safety; what it buys is that depends_on has to be right for the plan to work,
        which keeps it honest for Part E's orphan check.
        """
        parts = []
        if self.issue_text:
            parts.append(f"The issue:\n\n{self.issue_text}")
        for dep in step.get("depends_on") or []:
            returned = self.outputs.get(str(dep))
            if returned is not None:
                parts.append(f"What step {dep} returned:\n\n{returned}")
        parts.append(
            f"Step {step.get('id')} of the plan: {step.get('action')}\n"
            f"Call {step.get('tool')} once. Supply only: {', '.join(blanks)}."
        )
        return [{"role": "user", "content": "\n\n".join(parts)}]

    # -- running one step ------------------------------------------------------------
    def tool_schema(self, name) -> dict | None:
        return next((t for t in self.ctx.tools.schemas if t.get("name") == name), None)

    def fill(self, step: dict, args: dict, blanks: list[str]):
        """One model call, offered this step's tool alone, to supply the blanks.

        Only the blanks are taken from the model. Every other argument stays as the
        plan wrote it, so text injected into an issue can change what a step carries
        and never which step runs.
        """
        schema = self.tool_schema(step.get("tool"))
        if schema is None:
            return None, "unknown_tool"
        self.step += 1
        response = self.ctx.client.create(
            system=self.system_prompt(),
            messages=self.executor_messages(step, blanks),
            tools=[schema],
        )
        self.ctx.trace.model_call(self.step, response, purpose="execute")

        # A tool call is acted on whatever stop_reason says.
        calls = response.tool_calls
        if not calls:
            return None, "no_tool_call"
        call = calls[0]
        if call.name != step.get("tool"):
            # The boundary. This call never runs.
            self.ctx.trace.event("off_plan", step=step.get("id"), tool=call.name,
                                 input=call.input, expected=step.get("tool"))
            return None, "off_plan"

        given = call.input if isinstance(call.input, dict) else {}
        filled = {k: (given.get(k, v) if v == FILL else v) for k, v in args.items()}
        if any(v == FILL for v in filled.values()):
            return None, "not_filled"
        return filled, None

    def record(self, step: dict, args, status: str, content: str = "",
               is_error: bool = False, error_code: str | None = None) -> dict:
        """One entry of step_results (checks/FORMATS.md, section 10.3)."""
        tool = step.get("tool")
        done = status == "done"
        entry = {
            "id": step.get("id"),
            "tool": tool,
            "status": status,
            "count": _result_count(tool, content, is_error) if done else 0,
            "paths": result_paths(tool, args or {}, content, is_error) if done else [],
            "error_code": error_code,
            "args": args,
        }
        self.results.append(entry)
        step["status"] = status
        return entry

    def run_step(self, step: dict) -> None:
        """Run, retry or halt one step. Never add, drop or reorder one.

        Sets the step's status, and nothing else decides it: the caller halts on a
        step left failed, which gives Part C's checkpoint a chance to repair one
        first.
        """
        try:
            args = json.loads(step.get("args_json") or "{}")
        except (TypeError, ValueError):
            args = None
        if not isinstance(args, dict):
            self.record(step, None, "failed", error_code="bad_args_json")
            return

        blanks = [k for k, v in args.items() if v == FILL]
        if blanks:
            args, problem = self.fill(step, args, blanks)
            if problem:
                self.record(step, None, "failed", error_code=problem)
                return

        if step.get("tool") == "post_comment":
            final = self.second_pass(str(args.get("body") or ""))
            if final is None:
                self.record(step, args, "failed", error_code="draft_held")
                self.end("escalated", "the draft still failed its last round, so nothing was posted")
                return
            args = {**args, "body": final}

        result = self.ctx.call_tool(self.step, step.get("tool"), args, plan_step=step.get("id"))
        if result.is_error:
            self.record(step, args, "failed", result.content, True, "tool_error")
            return

        # A search that found nothing ran without failing, and still did not return
        # what the step was for. It is a failed step, so that the checkpoint can
        # rewrite it and the executor can retry; with no revision left, the run
        # escalates rather than reading a file no search pointed at.
        count = _result_count(step.get("tool"), result.content, False)
        if step.get("tool") == "search_repo" and not count:
            self.record(step, args, "failed", result.content, error_code="no_matches")
            self.outputs[str(step.get("id"))] = result.content
            return

        entry = self.record(step, args, "done", result.content)
        self.outputs[str(step.get("id"))] = result.content
        if step.get("tool") == "read_issue":
            self.issue_text = result.content
        self.after_step(step, entry)

    # -- hooks the later parts fill in -----------------------------------------------
    def after_step(self, step: dict, entry: dict) -> None:
        """Part G writes its progress file here."""

    def finish(self) -> None:
        """Part G compacts and asks its questions here, however the run ended."""

    def second_pass(self, draft: str):
        """Part D reads the draft here. None holds it, and the run escalates."""
        return draft

    def checkpoint(self, step: dict) -> None:
        """Part C revises here, after a search step whose check failed."""

    # -- the run ---------------------------------------------------------------------
    def execute(self) -> None:
        for _ in range(MAX_STEP_RUNS):
            step = next((s for s in self.plan["steps"] if s.get("status") == "pending"), None)
            if step is None:
                return                  # the plan is finished; the runner writes completed
            self.run_step(step)
            # The checkpoint runs before the halt: a revision may put this very step
            # back to pending, and then it is retried rather than being the end of
            # the run (Lecture 2, slide 16).
            self.checkpoint(step)
            if step.get("status") == "failed":
                self.end("escalated",
                         f"step {step.get('id')} could not be run, so a person should look at it")
                return
        self.end("escalated", "the executor ran more steps than any plan should hold")

    def run(self) -> None:
        try:
            plan = self.first_plan()
            if plan is None:
                self.end("escalated",
                         f"no plan passed the checks in {MAX_REPLANS + 1} attempts, so nothing ran")
                return
            self.plan = plan
            self.version = 1
            self.ctx.trace.plan(1, plan)        # before the first tool call
            self.execute()
        finally:
            self.finish()


def run(ctx) -> None:
    PlannedRun(ctx).run()
