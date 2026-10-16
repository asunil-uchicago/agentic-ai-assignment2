"""Assignment 2, Part D: the second pass before posting. This file is yours.

Two ways to read a drafted comment before it is posted (Lecture 2, slides 31 to 34).
The checker runs your planned way in each mode against scripted models, so keep
these exact signatures (checks/FORMATS.md, section 10.2). You may add keyword
arguments with defaults; the checker passes only these.

    verify(draft, ctx) -> {"passed": bool, "reasons": [str, ...]}

        The external mode: checks in code, against the repository and this run's
        own record. Four checks:
          1. the draft parses: a `label:` line with a known label, and a `file:`
             line with a path or none (section 1; harness.formats.parse_triage_comment);
          2. a path it names exists in the repository (ctx.root / "fixtures" / "repo");
          3. this run saw that path: a search_repo result or a read_file call in this
             run's trace returned it. Each tool_call line's `paths` field lists the
             files it returned; read the trace so far with
             harness.trace.read_trace(ctx.trace.path);
          4. the label and the file agree: a question names none, and every other
             label names a file.
        "reasons" says why each failed check failed; it is empty when all pass.
        verify reads only what the run itself can see: never the answer key, and
        never Assignment 1's grounded check in eval/. The checker flags a second
        pass that does.

    self_critique(client, draft, evidence, trace=None) -> {"decision": "accept" | "revise", "reason": str | None}

        The self mode: one model call that rereads the draft, given the issue and
        what the run's steps returned (`evidence`, a dict of your design), and
        accepts it or asks for a revision with a reason. Given a trace, trace the
        call: trace.model_call(n, response, purpose="critique").

    draft   the comment your executor drafted, the text post_comment would post
    ctx     the run's harness.runner.WayContext
    client  harness.client.ModelClient

The loop that uses them, its rewrite call and MAX_ROUNDS live in ways/planned.py.
Keep your prompts in prompts/.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.formats import LABELS, normalize_path, parse_triage_comment
from harness.trace import read_trace

ROOT = Path(__file__).resolve().parent.parent
CRITIQUE_PROMPT = "prompts/self_critique.md"

# The self critique answers through a tool, so its verdict comes back as data rather
# than as a sentence someone has to parse.
VERDICT_TOOL = {
    "name": "verdict",
    "description": "Give your verdict on the draft comment. Call this exactly once.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["decision", "reason"],
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["accept", "revise"],
                "description": "accept if the draft is right; revise if it should be rewritten.",
            },
            "reason": {
                "type": ["string", "null"],
                "description": "On revise, what is wrong, in one sentence. Null on accept.",
            },
        },
    },
}


def seen_paths(ctx) -> set[str]:
    """Every path this run's own tool calls have returned so far.

    Read off the trace, which is the run's record of what it actually saw, not off
    anything the model said about what it saw.
    """
    out: set[str] = set()
    try:
        records = read_trace(ctx.trace.path)
    except (OSError, ValueError):
        return out
    for line in records:
        if line.get("type") == "tool_call":
            out.update(line.get("paths") or [])
    return out


def verify(draft: str, ctx) -> dict:
    """The external mode: four checks in code, against the repository and this run.

    This is verification, not critique (Lecture 2, slide 34). It knows two things the
    author did not: what is on disk, and what this run actually looked at. It reads
    nothing else: not the answer key, not Assignment 1's grounded check.
    """
    reasons: list[str] = []
    label, file = parse_triage_comment(draft or "")

    # 1. The draft parses: a known label, and a path or none.
    if label not in LABELS or file is None:
        if label not in LABELS:
            reasons.append(f"the label is {label!r}, and it must be one of {', '.join(LABELS)}")
        if file is None:
            reasons.append("there is no 'file:' line, which must name a path or none")
        return {"passed": False, "reasons": reasons}

    names_file = file != "none"

    # 2. A path it names exists in the repository. A draft naming none skips this.
    exists = True
    if names_file:
        root = Path(getattr(ctx, "root", ROOT) or ROOT)
        target = root / "fixtures" / "repo" / normalize_path(file)
        exists = target.is_file()
        if not exists:
            reasons.append(f"no file named {file} exists in the repository")

    # 3. This run saw that path: a search returned it, or a read read it.
    if names_file and exists and file not in seen_paths(ctx):
        reasons.append(f"this run never saw {file}: no search returned it and no read read it")

    # 4. The label and the file agree. Without this a rewrite could pass by changing
    #    the file to none rather than by finding the right one.
    if label == "question" and names_file:
        reasons.append(f"a question names no file, but this one names {file}")
    if label != "question" and not names_file:
        reasons.append(f"a {label} must name the file responsible, but the file is none")

    return {"passed": not reasons, "reasons": reasons}


def self_critique(client, draft: str, evidence: dict, trace=None) -> dict:
    """The self mode: the model rereads its own draft, and knows nothing new.

    It is given the draft, the issue and what the run's steps returned, which is what
    the author of the draft already had. Slide 33's question, what does the critic
    know that the agent did not, has no answer here, and that is the point of
    measuring it beside the external checks.
    """
    system = (ROOT / CRITIQUE_PROMPT).read_text(encoding="utf-8")
    messages = [{
        "role": "user",
        "content": "\n\n".join([
            f"The draft comment:\n\n{draft}",
            f"What the run has to go on:\n\n{json.dumps(evidence, indent=1, default=str)}",
            "Accept the draft, or ask for a revision and say why.",
        ]),
    }]
    response = client.create(system=system, messages=messages, tools=[VERDICT_TOOL])
    if trace is not None:
        trace.model_call(0, response, purpose="critique")

    for call in response.tool_calls:
        if call.name == VERDICT_TOOL["name"] and isinstance(call.input, dict):
            decision = call.input.get("decision")
            reason = call.input.get("reason")
            if decision == "revise":
                return {"decision": "revise", "reason": reason or "the critic asked for a revision"}
            return {"decision": "accept", "reason": None}
    # No verdict is not a reason to hold a draft: a critic that would not answer has
    # found nothing, so the draft stands.
    return {"decision": "accept", "reason": None}
