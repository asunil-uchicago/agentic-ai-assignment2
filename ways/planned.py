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

from agent.critique import self_critique, verify
from agent.plan import load_schema, make_plan, revise_plan, without_meta
from agent.validator import validate
from harness.formats import FILL, result_paths
from harness.schema import errors

MAX_REPLANS = 2        # Part B: so a run makes at most three planner calls
MAX_REVISIONS = 2      # Part C: revisions a run, accepted and rejected alike
MAX_ROUNDS = 2         # Part D: second-pass rounds a run, the same in both modes

EXECUTOR_PROMPT = "executor.md"
REWRITE_PROMPT = "rewrite.md"

# A step that has run cannot be picked up again, so the executor always moves forward.
# This only guards against a plan that somehow leaves a step pending for ever.
MAX_STEP_RUNS = 32

# How many times the executor may retry one step with different arguments before the
# step is failed. Retrying a step is the executor's to do and is not a revision: the
# plan's steps, their order and their tools are untouched (Lecture 2, slide 15).
MAX_STEP_RETRIES = 2


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
        self.checkpoints: set[str] = set()   # ids of search steps the check runs after
        self.attempts: dict[str, list[dict]] = {}   # what each step has already tried
        self.retries: dict[str, int] = {}           # retries spent on each step
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
            steps = [s for s in (plan.get("steps") or []) if isinstance(s, dict)]
            last = steps[-1].get("tool") if steps else None
            posts = sum(1 for s in steps if s.get("tool") == "post_comment")
            if last != "post_comment":
                problems = [f"the plan's last step is {last!r}, and a plan must end with post_comment"]
            elif posts > 1:
                # A run decides once. Two posting steps would put two comments on one
                # issue, which the grounded check reads as no decision at all.
                problems = [f"the plan posts {posts} comments, and a run posts one"]
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
        # What this step has already tried. Without it a retried step picks the same
        # obvious argument again and the run circles: the agent has no
        # representation of its own progress (Lecture 2, slide 44). These are the
        # run's own record, not anything new from outside it.
        # The comment names a file, and a model recalling a path from the middle of a
        # file's text invents its extension. These are the paths this run's own tool
        # calls returned, which is exactly what Part D's external check will hold the
        # draft against, so the author and the checker read the same list.
        if step.get("tool") == "post_comment":
            seen = self.seen_paths()
            if seen:
                parts.append("Every path this run has actually seen, exactly as the tools "
                             "returned them:\n" + "\n".join(f"- {p}" for p in seen) +
                             "\nName one of these, character for character, or none.")

        tried = self.attempts.get(str(step.get("id")))
        if tried:
            lines = "\n".join(f"- {json.dumps(t['args'])} returned {t['outcome']}" for t in tried)
            parts.append(
                f"This step has already been tried, and did not work:\n{lines}\n"
                "Choose different arguments. Repeating any of those wastes the step."
            )
        parts.append(
            f"Step {step.get('id')} of the plan: {step.get('action')}\n"
            f"Call {step.get('tool')} once. Supply only: {', '.join(blanks)}."
        )
        return [{"role": "user", "content": "\n\n".join(parts)}]

    def seen_paths(self) -> list[str]:
        """Every path this run's tool calls returned, oldest first, without repeats."""
        out: list[str] = []
        for entry in self.results:
            for path in entry.get("paths") or []:
                if path not in out:
                    out.append(path)
        return out

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

        step_id = str(step.get("id"))
        blanks = [k for k, v in args.items() if v == FILL]
        given = dict(args)
        # Posting is never retried. The second pass runs once per draft, and a retry
        # would run it again and write more critique lines than MAX_ROUNDS allows;
        # a post that the tracker refused is a failed step, for a person to look at.
        may_retry = bool(blanks) and step.get("tool") != "post_comment"

        while True:
            if blanks:
                args, problem = self.fill(step, given, blanks)
                if problem:
                    self.record(step, None, "failed", error_code=problem)
                    return

            if step.get("tool") == "post_comment":
                final = self.second_pass(str(args.get("body") or ""))
                if final is None:
                    self.record(step, args, "failed", error_code="draft_held")
                    self.end("escalated",
                             "the draft still failed its last round, so nothing was posted")
                    return
                args = {**args, "body": final}

            result = self.ctx.call_tool(self.step, step.get("tool"), args, plan_step=step_id)
            if result.is_error:
                # A tool that refused the arguments is the other thing a retry can
                # fix: a path that does not exist, or a directory where a file was
                # wanted. The step, its tool and its place in the plan do not change.
                self.attempts.setdefault(step_id, []).append(
                    {"args": args, "outcome": f"an error: {result.content[:140]}"})
                if may_retry and self.retries.get(step_id, 0) < MAX_STEP_RETRIES:
                    self.retries[step_id] = self.retries.get(step_id, 0) + 1
                    continue
                self.record(step, args, "failed", result.content, True, "tool_error")
                return

            count = _result_count(step.get("tool"), result.content, False)
            if step.get("tool") != "search_repo":
                break

            # Remember what this search tried, so a retry does not repeat it.
            paths = result_paths("search_repo", args, result.content, False)
            self.attempts.setdefault(step_id, []).append({
                "args": args,
                "outcome": f"{count} result(s)" + (f", in {sorted(set(paths))}" if paths else ", no files"),
            })
            if count:
                break

            # A search that matched nothing at all. Retrying the step with other
            # arguments is the executor's to do and changes no plan: the steps, their
            # order and their tools are exactly as the plan wrote them. Only when the
            # retries are spent does this become a failed step for the checkpoint to
            # repair (Lecture 2, slide 15).
            if may_retry and self.retries.get(step_id, 0) < MAX_STEP_RETRIES:
                self.retries[step_id] = self.retries.get(step_id, 0) + 1
                continue
            self.record(step, args, "failed", result.content, error_code="no_matches")
            self.outputs[step_id] = result.content
            return

        entry = self.record(step, args, "done", result.content)
        self.outputs[step_id] = result.content
        if step.get("tool") == "read_issue":
            self.issue_text = result.content
        self.after_step(step, entry)

    # -- hooks the later parts fill in -----------------------------------------------
    def after_step(self, step: dict, entry: dict) -> None:
        """Part G writes its progress file here."""

    def finish(self) -> None:
        """Part G compacts and asks its questions here, however the run ended."""

    # -- Part D: a second pass before posting ----------------------------------------
    def evidence(self) -> dict:
        """What the self critique is shown: exactly what the draft's author had."""
        return {
            "issue": self.issue_text,
            "paths_this_run_saw": self.seen_paths(),
            "steps": [{k: v for k, v in r.items() if k != "args"} for r in self.results],
        }

    def rewrite(self, draft: str, reason: str) -> str:
        """One model call that rewrites a failed draft, given the reason it failed."""
        self.step += 1
        response = self.ctx.client.create(
            system=self.ctx.prompt(REWRITE_PROMPT),
            messages=[{"role": "user", "content": "\n\n".join([
                f"The draft comment:\n\n{draft}",
                f"The check it failed:\n\n{reason}",
                "Every path this run has actually seen:\n"
                + "\n".join(f"- {p}" for p in self.seen_paths() or ["(none)"]),
                "Rewrite the comment so it passes. Answer with the comment alone.",
            ])}],
            tools=None,
        )
        self.ctx.trace.model_call(self.step, response, purpose="critique")
        return (response.text or "").strip() or draft

    def round_result(self, draft: str) -> tuple[str, str | None]:
        """One round's verdict on a draft: pass, or fail with a reason."""
        if self.ctx.critique == "external":
            verdict = verify(draft, self.ctx)          # code only, no model call
            if verdict["passed"]:
                return "pass", None
            return "fail", "; ".join(verdict["reasons"])
        verdict = self_critique(self.ctx.client, draft, self.evidence(), trace=self.ctx.trace)
        if verdict.get("decision") == "revise":
            return "fail", verdict.get("reason")
        return "pass", None

    def second_pass(self, draft: str):
        """Read the draft before it is posted, in the mode --critique names.

        Bounded and logged, which is the third of slide 41's gates. A draft that
        passes is posted; a draft still failing in the last round is held, nothing is
        posted, and the run escalates. Returns the text to post, or None to hold.
        """
        if self.ctx.critique == "off":
            return draft

        for round_number in range(1, MAX_ROUNDS + 1):
            result, reason = self.round_result(draft)
            # A failing draft gets one rewrite while a round remains. The rewrite
            # happens before the line is written, so "changed" records what it did.
            rewritten, changed = draft, False
            if result == "fail" and round_number < MAX_ROUNDS:
                rewritten = self.rewrite(draft, reason or "the check failed")
                changed = rewritten != draft
            self.ctx.trace.event("critique", round=round_number, mode=self.ctx.critique,
                                 result=result, reason=reason, changed=changed, draft=draft)
            if result == "pass":
                return draft
            if round_number == MAX_ROUNDS:
                return None                # held: not posted, and the run escalates
            draft = rewritten
        return None

    # -- Part C: one checkpoint, after a search -------------------------------------
    @staticmethod
    def found_source(paths) -> bool:
        """The checkpoint's check, in code rather than in a prompt.

        The search returned at least one source file: a .ts or .tsx file under src/,
        not counting translations. Asking only "did the search return anything" would
        almost never fire, because almost every term matches something;
        search_repo returns at most 20 hits in path order, so CHANGELOG.md, README.md
        and docs/ come first and a vague term fills the list with them before it
        reaches any code.
        """
        for path in paths or []:
            if path.startswith("src/") and path.endswith((".ts", ".tsx")) \
                    and not path.startswith("src/i18n/"):
                return True
        return False

    def searches_changed(self, before: dict, after: dict) -> set:
        """Ids of search steps a revision added or changed: the next checkpoints."""
        was = {str(s.get("id")): s for s in before.get("steps") or [] if isinstance(s, dict)}
        out = set()
        for step in after.get("steps") or []:
            if not isinstance(step, dict) or step.get("tool") != "search_repo":
                continue
            old = was.get(str(step.get("id")))
            if old is None or old.get("action") != step.get("action"):
                out.add(str(step.get("id")))
        return out

    def checkpoint(self, step: dict) -> None:
        """Revise the plan here and nowhere else (Lecture 2, slide 16).

        Only after a search step that is a checkpoint, only when the check there
        fails, and only while a revision is left. Everything between this and the
        search's tool call is a model call, so the revision line lands directly after
        the search in the trace, which is how the checkpoint can be read back.
        """
        step_id = str(step.get("id"))
        if step.get("tool") != "search_repo" or step_id not in self.checkpoints:
            return
        if self.revisions >= MAX_REVISIONS:
            return
        found = next((r for r in reversed(self.results) if str(r.get("id")) == step_id), None)
        paths = (found or {}).get("paths") or []
        if self.found_source(paths):
            return                      # the search did its job; nothing to repair

        if self.revisions >= MAX_REVISIONS:
            # Out of revisions. Go on with whatever the search did return; a search
            # that returned nothing at all leaves the step failed, and the run
            # escalates rather than reading a file nothing pointed at.
            if paths:
                step["status"] = "done"
            return

        self.revisions += 1
        self.checkpoints.discard(step_id)
        # The check is what "worked" means for a search step, so a search it rejects
        # is a failed step. That is also what lets the reviser rewrite it: a step
        # marked done comes back untouched however the plan is repaired.
        step["status"] = "failed"
        version = self.version + 1
        revised = revise_plan(self.ctx.client, self.plan, self.results, trace=self.ctx.trace)
        valid = self.acceptable(revised, version)
        self.ctx.trace.event("revision", checkpoint="after_search", version=version,
                             valid=valid, failures=[] if valid else validate(revised)["failures"])
        if not valid:
            # It never runs, and it still counts against the bound. The search keeps
            # whatever it found, so the run can still go on if it found anything.
            step["status"] = "done" if paths else "failed"
            return
        self.checkpoints |= self.searches_changed(self.plan, revised)
        self.plan = revised
        self.version = version
        self.ctx.trace.plan(version, revised)

    # -- the run ---------------------------------------------------------------------
    def execute(self) -> None:
        for _ in range(MAX_STEP_RUNS):
            step = next((s for s in self.plan["steps"] if s.get("status") == "pending"), None)
            if step is None:
                return                  # the plan is finished; the runner writes completed
            self.run_step(step)
            # The checkpoint runs before the halt: a revision may put this very step
            # back to pending, and then it is retried rather than being the end of
            # the run (Lecture 2, slide 16). Read the status back off the active
            # plan, because a revision replaces the step objects wholesale.
            self.checkpoint(step)
            current = next((s for s in self.plan["steps"]
                            if str(s.get("id")) == str(step.get("id"))), step)
            if current.get("status") == "failed":
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
            # The checkpoint is the first search step. A revision that changes a
            # search step adds that one too, so the check runs again after it.
            first = next((s for s in plan["steps"] if s.get("tool") == "search_repo"), None)
            self.checkpoints = {str(first.get("id"))} if first else set()
            self.ctx.trace.plan(1, plan)        # before the first tool call
            self.execute()
        finally:
            self.finish()


def run(ctx) -> None:
    PlannedRun(ctx).run()
