"""Way 6, notes: the planned way with a progress file and a compaction. This file is yours.

Assignment 2, Part G. Your planned way with the second pass off, plus two things,
so that Part F's configurations stay as they were (checks/FORMATS.md, section 10):

    python run.py --way notes --notes off --issues 4203,4204,4206 --runs 2
    python run.py --way notes --notes on --issues 4203,4204,4206 --runs 2

  1. A progress file, ctx.progress_path (runs/<run_id>.progress.json): JSON outside
     the conversation, written after every step, holding at least
       "steps_done"  the ids of the steps that have run, in order
       "paths"       every path a search returned or a read read, in order
     and never a search term: terms come from the issue's text. Say in the file what
     it records (an "about" line, or labelled keys): a bare list of paths can be read
     as a to-do list. With ctx.notes == "on", every executor call and the questions'
     call after its first write show the model the file's text, exactly as written
     (not the planner, not the reviser). With "off", it is still written, and never
     shown.
  2. A history and a compaction: every model call sees the run's history so far,
     its step results oldest first. Once that history passes COMPACT_AT tokens, the
     oldest entries become a model-written summary and the recent ones stay as
     they were. Write ctx.trace.event("compaction", threshold=COMPACT_AT, tokens=...)
     each time. It runs whatever ctx.notes says. A low threshold is a test setting
     here, not advice.

Then, at the end of the run, however it ended (comment posted, escalated, halted),
one model call asks six closed questions, each "Has this run seen `<path>`: did a
search return it, or did you read it?", and returns six answers, yes or no: about
the three earliest paths the run saw (its tool_call lines returned them; all of
them, if it saw fewer), and paths it did not see for the rest. If the run has not
compacted yet, compact its history once first. Write each answer as
ctx.trace.event("question", path=..., answer=...), the six together.

Part G's 12 runs are the ones on issues 4203, 4204 and 4206; a notes run on a
development issue is development, and reports/LAB_02.json's context leaves it out.
"""

from __future__ import annotations

import json
import re

from harness.scripted import estimate_tokens
from ways.planned import PlannedRun

# The context size, in tokens, past which the history is compacted. Deliberately low,
# so that a run of four or five steps crosses it and Part G has something to measure.
# A real threshold would be a large fraction of the model's window; this is a test
# setting, as the handout says, not advice.
COMPACT_AT = 40

QUESTIONS_PROMPT = "questions.md"
SUMMARY_PROMPT = "summarize.md"

# How many of the most recent history entries a compaction leaves alone.
KEEP_RECENT = 2

# Part G asks six questions: the three earliest paths the run saw, and the rest
# filled with paths it did not see.
QUESTIONS = 6
ASK_ABOUT_SEEN = 3


class NotesRun(PlannedRun):
    """The planned way, plus a progress file and a compaction (Lecture 2, slides 25 to 30).

    Everything here is a hook the planned way already left open, so Part F's 54 runs
    came from a version of ways/planned.py this file has not touched.
    """

    def __init__(self, ctx):
        super().__init__(ctx)
        self.history: list[str] = []    # step results, oldest first
        self.compactions = 0
        self.asked = False

    def second_pass(self, draft: str):
        """Part G runs with the second pass off, whatever --critique says."""
        return draft

    # -- the progress file, outside the conversation ---------------------------------
    def progress_state(self) -> dict:
        """What the file records. The wording matters: a bare list of paths gets read
        as a list of things to do (slide 27), so the file says what it is."""
        seen: list = []
        for entry in self.results:
            for path in entry.get("paths") or []:
                if path not in seen:
                    seen.append(path)
        steps_done: list = []
        for entry in self.results:
            if entry.get("id") not in steps_done:
                steps_done.append(entry.get("id"))
        return {
            "about": "A record of what this run has already done. Not a list of things to do.",
            "steps_done": steps_done,
            "paths": seen,
            "paths_means": "every file path a search returned or a read read, oldest first",
        }

    def write_progress(self) -> None:
        """Written after every step. It holds paths and step ids, never a search
        term: the terms come from the issue's text, and this file outlives the
        conversation that may carry it."""
        path = self.ctx.progress_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.progress_state(), indent=1), encoding="utf-8")

    def progress_text(self) -> str | None:
        """The file's text, exactly as written, when --notes says to show it."""
        if self.ctx.notes != "on" or not self.ctx.progress_path.exists():
            return None
        return self.ctx.progress_path.read_text(encoding="utf-8")

    def record(self, step, args, status, content="", is_error=False, error_code=None):
        entry = super().record(step, args, status, content, is_error, error_code)
        self.history.append(
            f"step {entry['id']} called {entry['tool']}: {entry['status']}"
            + (f", {entry['count']} result(s)" if entry.get("count") is not None else "")
            + (f", returned {entry['paths']}" if entry.get("paths") else "")
            + (f", error {entry['error_code']}" if entry.get("error_code") else "")
        )
        self.write_progress()
        return entry

    # -- the history, and the compaction ---------------------------------------------
    def compact(self, force: bool = False) -> bool:
        """Replace the oldest history entries with one model-written summary.

        The one operation of the four that throws information away (slide 26). What
        it keeps is whatever the summary happens to mention; what the progress file
        keeps is every path, because the file is not in the conversation at all.
        """
        tokens = estimate_tokens(self.history)
        # Nothing to fold away until there is something older than the recent
        # entries; without this guard a lone summary would be summarised again.
        if not force and (tokens <= COMPACT_AT or len(self.history) <= KEEP_RECENT):
            return False
        older, recent = self.history[:-KEEP_RECENT], self.history[-KEEP_RECENT:]
        if not older:
            older, recent = self.history, []
        if older:
            self.step += 1
            response = self.ctx.client.create(
                system=self.ctx.prompt(SUMMARY_PROMPT),
                messages=[{"role": "user", "content":
                           "Summarise these entries into one short paragraph:\n\n" + "\n".join(older)}],
                tools=None,
            )
            self.ctx.trace.model_call(self.step, response)
            summary = (response.text or "").strip() or "(the summary came back empty)"
            self.history = [f"Earlier, summarised: {summary}"] + recent
        self.compactions += 1
        self.ctx.trace.event("compaction", threshold=COMPACT_AT, tokens=tokens,
                             summarised=len(older), kept=len(recent))
        return True

    def executor_messages(self, step: dict, blanks: list[str]) -> list[dict]:
        """The planned way's message, with the history before it and, with --notes on,
        the progress file's text exactly as written."""
        self.compact()
        messages = super().executor_messages(step, blanks)
        before = []
        if self.history:
            before.append("What this run has done so far, oldest first:\n" + "\n".join(self.history))
        note = self.progress_text()
        if note:
            before.append("A note this run keeps in a file outside this conversation:\n" + note)
        if before:
            messages[0]["content"] = "\n\n".join(before + [messages[0]["content"]])
        return messages

    # -- the six questions, at the end of every run -----------------------------------
    def unseen_paths(self, how_many: int, exclude: set) -> list[str]:
        """Real files of the repository that this run did not see.

        Chosen by reading the repository at run time rather than from a list written
        into this file, so that no path can be baked into the source.
        """
        from tools.search_repo import EXCLUDED_DIRS

        root = self.ctx.root / "fixtures" / "repo"
        out: list[str] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if set(rel.parts) & EXCLUDED_DIRS:
                continue
            name = rel.as_posix()
            if name not in exclude:
                out.append(name)
            if len(out) >= how_many:
                break
        return out[:how_many]

    def ask_questions(self) -> None:
        """One model call, six closed questions, then six question lines together."""
        seen = self.seen_paths()
        asked = list(seen[:ASK_ABOUT_SEEN])
        asked += self.unseen_paths(QUESTIONS - len(asked), set(seen))
        if not asked:
            return

        numbered = "\n".join(f"{i}. Has this run seen `{p}`: did a search return it, "
                             f"or did you read it?" for i, p in enumerate(asked, 1))
        self.step += 1
        response = self.ctx.client.create(
            system=self.ctx.prompt(QUESTIONS_PROMPT),
            messages=[{"role": "user", "content": "\n\n".join(x for x in (
                # What the conversation still holds after compaction, which is the
                # thing being tested, and then the file, which compaction cannot touch.
                ("What this run has done so far, oldest first:\n" + "\n".join(self.history))
                if self.history else None,
                self.progress_text(),
                numbered,
            ) if x)}],
            tools=None,
        )
        self.ctx.trace.model_call(self.step, response)

        found = [t.lower() for t in re.findall(r"\b(yes|no)\b", response.text or "", re.IGNORECASE)]
        if len(found) == 1:
            found = found * len(asked)            # one answer offered for all of them
        answers = (found + ["no"] * len(asked))[:len(asked)]
        for path, answer in zip(asked, answers):
            self.ctx.trace.event("question", path=path, answer=answer)

    def finish(self) -> None:
        """However the run ended: compact if it has not, then ask the six."""
        if self.asked:
            return
        self.asked = True
        if not self.compactions:
            self.compact(force=True)
        self.ask_questions()


def run(ctx) -> None:
    NotesRun(ctx).run()
