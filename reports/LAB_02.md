# Assignment 2 report · A plan RepoMind cannot quietly abandon

Every number here that has a field in `reports/LAB_02.json` goes there too: the
checker reads that file (format: `checks/FORMATS.md`, section 10.10). Give each
number its run count. Mark any vendor figure you cite with its source and the date
you read it.

## Part A · The plan artifact

**The `args` choice: `args_json`.** RepoMind's four tools take four different
argument shapes, and strict mode rejects a free-form object, so the choice was
between one JSON-encoded string and a `oneOf` branch per tool. I took `args_json`
because the union budget is the scarce resource here and `oneOf` would have spent
four of it on information the executor can get for free: it already knows which tool
a step names, so it can check the decoded arguments against that tool's own
`input_schema` before calling. The cost is one `json.loads` in the executor and
arguments that a human reading the plan sees escaped.

**The strict-mode count: 0 optional fields and 2 union types, against budgets of 24
and 16.** Every one of the step object's seven properties is listed in `required`
and both objects carry `additionalProperties: false`, so nothing is optional; the
two unions are `tool` and `expected_result`, written `["string", "null"]` because
the schema has to be able to express the plans the validator must reject (a step
with no tool, or no expected result) while still compiling. The schema is 8 object
properties and 5 levels deep, against limits of 5,000 and 10. A strict request
carrying it was **accepted**: `gpt-4o-mini-2024-07-18` returned a four-step plan
through the `submit_plan` tool with `"strict": true` set, and the returned plan
passed `harness.schema.errors` against the file.

**One thing strict mode did not buy.** Acceptance is not enforcement of the
*convention*, only of the *shape*. The planner repeatedly returned a comment body of
`"label: $fill\nfile: $fill"`, a template rather than a blank, which section 10.1
defines as a value "fixed by the plan" and which the executor would therefore have
posted word for word. Two rounds of prompting, including the wrong form shown
explicitly, did not stop it. It is enforced in code instead, in
`agent/plan.py:_normalize_fills`, which is the point `prompts/README.md` makes: a
sentence in a prompt is a request, not a control.

## Part B · The validator and the boundary

| Plan | Valid | Failures (step, check) |
|---|---|---|
| `good_export_fix.json` | yes | none |
| `good_triage.json` | yes | none |
| `s18_specimen.json` | no | (2, 2), (3, 3), (5, 1) |

Built by `eval/summarize_02.py`, which writes `fixture_validation` in
`reports/LAB_02.json`; the table is that list.

Slide 18's specimen fails three times, each for a different reason, and passes
check 4. Step 2, "apply the fix from step 4", depends on a step that has not run
yet. Step 3, "think about the likely cause", has no tool and no
`expected_result`, so nothing it does can be observed; it fails check 3 rather
than check 1, because a step with no tool has not named a tool wrongly, it has
failed to be a step. Step 5 calls `export_report`, which is not in the plan's own
tool list. Five steps is inside the bound, so the plan is the right length and
wrong in every other way, which is the point: a length check is the cheapest of
the four and catches the least.

**`MAX_REPLANS = 2`, so a run makes at most three planner calls.** The planner is
given the failures and re-plans, and the defects the validator catches are the
kind a second attempt fixes. Past the third attempt a planner that is still
writing invalid plans is not going to converge, and every further attempt spends a
call to reach the same escalation.

*(The count of plans that broke the schema or lacked a final `post_comment` is
measured over Part F's runs and is reported with them.)*

## Part C · Revision at a checkpoint

**The check:** after a search step, the search must have returned at least one
source file, a `.ts` or `.tsx` under `src/` that is not a translation, and if it
returned only documentation, translations or nothing at all, the plan is revised.

**`MAX_REVISIONS = 2`.** The plan has one search step, so two revisions give the run
three chances to find source code, and a third revision has never changed the answer
in development: by then the issue's distinctive words are used up and the reviser,
which cannot see the issue, has nothing new to say. Keeping it at 2 also keeps
revisions well below the step count, which is the sign that a checkpoint is tight
rather than a tool loop wearing a plan.

Issue 4203 is what the checkpoint is for. The obvious search, the error message
`Malformed row`, returns exactly one hit, and it is `src/i18n/en.json`: the run has
found where the message is written, not the code that produces it. The check fails,
the plan goes to version 2 with the search step rewritten, and the executor searches
again. The `revision` line sits directly after that search's `tool_call` line, which
is how the trace shows where adaptation was allowed to happen.

**Retrying is not revising.** The executor may also retry a step up to
`MAX_STEP_RETRIES = 2` times when a search matches nothing at all or a tool refuses
the arguments, and that is not a revision: the plan's steps, their order and their
tools are untouched, only the arguments change. This matters because without it the
planned way was strictly worse than Assignment 1's agent, which can search six or
seven times inside its step budget. Keeping retries separate from revisions is what
lets the revision bound stay at 2 while the run still gets a fair number of searches.

## Part D · A second pass before posting

**The four external checks** in `agent/critique.py`, in order:

1. **It parses.** The first two lines are `label:` and `file:`, the label is one of
   the four, and the file is a path or `none`.
2. **The path exists** under `fixtures/repo`. A draft naming `none` skips this.
3. **This run saw the path.** It appears in the `paths` of one of this run's own
   `tool_call` lines, read back off the trace. Not that the file is plausible: that
   a search returned it or a read read it.
4. **The label and the file agree.** A `question` names `none`; every other label
   names a file. Without this check a failing draft could pass by changing the file
   to `none` rather than by finding the right one.

**`MAX_ROUNDS = 2`:** check, rewrite once if the check fails, check again, then post
or hold. One round would be a gate with no repair, and would make the cost of a
second pass pure overhead on every run that fails it; a third round never changed a
draft in development, because the rewriter is given the same reason it was given the
first time.

### Slide 41's three gates, by mode

| | Can a check find the error? | Does the critic know more? | Is there a limit and a log? |
|---|---|---|---|
| `off` | no check runs | no critic | nothing to bound |
| `self` | only what one reading can notice | **no**: it is shown the issue and the step results, which is exactly what the author had | yes: `MAX_ROUNDS`, and a `critique` line a round |
| `external` | **yes**, for four named faults, in code | **yes**: it knows what is on disk and what this run actually saw | yes: the same bound and the same line |

So `external` is the only mode that passes all three, and it is the only one that is
verification rather than critique (slide 34). It is also the cheaper of the two: its
check is code, so a passing draft costs **no model call at all**, while `self` costs
one every run whatever it concludes.

### What the checks actually catch

Run against eight drafts, holding this run's own trace as the record of what it saw:

| Draft | Verdict |
|---|---|
| a path the run saw | pass |
| `ExportButton.js`, the extension invented | fail, check 2 |
| a real file the run never opened | fail, check 3 |
| a bare filename, directories stripped | fail, check 2 |
| `bug` with `file: none` | fail, check 4 |
| `question` naming a file | fail, check 4 |
| an unknown label | fail, check 1 |
| no `file:` line | fail, check 1 |

The second of those is not hypothetical: a Part C development run posted
`src/components/ExportButton.js` for a file that is `.tsx`, with the directory
right and the extension invented. That is the kind of fault a check in code is for,
and the kind a model rereading its own draft has no way to notice.

### What neither mode can catch

A development run on 4191 drafted `label: question` with `file: none`, and
`external` **passed it**, correctly: a question that names no file is consistent,
nothing in the repository contradicts it, and the run genuinely did not need to see
a file to write it. The answer is `docs` with `README.md`. Both checks are satisfied
by a draft that is simply wrong about what kind of issue it is reading. That is the
semantic error of slide 41, and no amount of checking against the repository or the
run's record reaches it.

## Part E · Detectors and the diff

**How the diff matches a traced call to a plan step.** By `plan_step` where the
line carries one, which the executor writes on every call it makes. The recorded
runs in `fixtures/traces/` have no `plan_step`, so there the match is by tool and by
the arguments the plan fixes, an argument written `"$fill"` being fixed by nothing.
One call consumes one step, and a call that matches no unconsumed step is `extra`.

That last rule is what slide 51's run turns on. Its plan has two `run_tests` steps,
step 1 with no arguments and step 5 with `test: test_export_csv`. The first call,
`run_tests` with no arguments, matches step 1, whose fixed arguments are empty and
so match anything. The sixth call, `run_tests test_export_csv`, would also match
step 1 on that reasoning, but step 1 is already consumed, so it falls through to
step 5, whose fixed argument it satisfies exactly. Without consumption both calls
would claim step 1 and step 5 would read as skipped, which would be the wrong
diagnosis: the test was re-run, and it still failed.

### The looping run

| | Fired | What fired |
|---|---|---|
| q1 Did any two steps do the same thing? | yes | turns 1 and 3, and turns 2 and 4 |
| q2 Is any step's result never used? | yes | turns 1, 2, 3, 4, 5 |
| q3 Did every planned step execute? | yes | steps 3, 4, 5, 6 never ran |

**How question 2 was answered without `depends_on`.** This plan records no
dependencies at all, so the dependency graph cannot answer it and the trace has to.
The rule in code: a call's result counts as used when a later call's arguments name
a path that call returned. The looping run was transcribed without paths, its
results being `247 results` and `1,400 lines`, so there is nothing recorded for a
later call to name, and no use can be demonstrated for any call. Every call but the
last is reported unused.

That is the honest reading rather than a satisfying one, and the gap is the finding.
A person looking at turns 5 and 6, `search("exportButton")` then
`read(ExportButton.tsx)`, would say plainly that the search fed the read. The only
reason to think so is that the path resembles the query. The trace does not record
that the search returned that path, so the detector cannot know it, and a detector
that guessed from resemblance would also "find" that turn 1's search for `export`
fed turn 5's search for `exportButton`, which is circling, not progress.

**Question 4: did the plan match the task?** No. The task was to find out why one
button does not work, and the plan commits to fixing it and opening a pull request
before anything has been read, so steps 3 to 6 are written as though the cause were
already known.

### Slide 51's run

| | Fired | What fired |
|---|---|---|
| q1 Did any two steps do the same thing? | yes | turns 2 and 4, the identical search |
| q2 Is any step's result never used? | no | every step but the last is in a later `depends_on` |
| q3 Did every planned step execute? | yes | step 6, "confirm the button works" |

The diff: steps 1 to 5 `executed`, step 6 `skipped`, and one `extra` call, turn 4.

**Question 4: did the plan match the task?** Yes, and that is what makes the run
worth reading: a sound plan still ended in a false report, because the agent stopped
at step 5 and reported success while `test_export_csv` was still failing.

**What the ladder is actually doing here.** Three of these four detectors fall out
of things built for other reasons: the schema gave the step ids, `depends_on` gave
the graph, and `status` gave the record of what ran. None of them is clever. The
cleverness was in having recorded the plan at all, which is the whole argument for
making it data (slide 53).

**Treating repetition as the defect.** In the looping run the repeat is the symptom.
The defect is step 3, "Identify the bug": a step with no tool and no expected
result, which the validator rejects on check 3 before the run ever starts. Because
nothing can observe whether that step succeeded, the agent has no way to tell
whether it has made progress, so it goes back and searches again. Slide 44's
question, does the agent have any representation of its own progress, is answered
by the plan's own shape, and the answer is no.

## Part F · What the plan and the second pass bought

Three sweeps a configuration: a pilot, not a settled difference.

### Predictions, written 2026-10-16, before any evaluation run

Recorded before `make reset` and before the first measured run, so that the numbers
below can disagree with them. Development was on 4191 and 4192 only, where the
planned way passed 5 of 6 and Assignment 1's agent 2 of 6; neither issue is in the
measured set, so these are reasoning from the issue text and the fixtures, not from
evidence.

**Per issue.**

- **4201**, the reset link pointing at localhost. The responsible file is the one
  that builds the URL, not the one that handles the reset, and a reporter describing
  a password reset pulls a search towards authentication. I expect this to pass
  sometimes and to fail by naming the auth path.
- **4202**, a request for TSV export. Two risks, and they are independent: the label
  has to be `feature` rather than `bug`, and the repository has both an
  `src/export/` directory and a single top-level export helper, so a search for
  `csv` returns the wrong one first. I expect this to fail more often than it passes.
- **4203**, "Malformed row". The one issue the checkpoint was built for: the error
  message matches exactly one line in the repository and it is a translation file.
  The checkpoint will fire on nearly every run. Whether the revision then finds the
  parser is the open question, and in development the second search went to
  documentation instead. I expect it to fail more often than it passes, with a
  revision in almost every run.
- **4204**, the Monday email arriving on Tuesday. The words in the issue are the
  reporter's, not the code's, and nothing in it names anything a literal search will
  match. I expect searches to return nothing or only documentation, the retries and
  the revision to be spent, and a high share of runs to end `escalated` with no
  comment. This is the issue where the planned way should post least often.
- **4205**, the security team's question. The answer is `question` with `file: none`,
  and nothing needs to be found at all. **I expect the plan to hurt here.** Every
  plan the planner writes contains a search and a read, because it is written before
  the issue is known and cannot tell that this issue needs neither. A search that
  finds no source file fires the checkpoint, a read with no path to read fails, and
  the run escalates with nothing posted, while the agent can simply stop and answer.
  This is slide 52's first case in the measured set: a task of one step, given a plan
  of four.
- **4206**, the misattributed currency bug. The issue names `src/export/csv.ts` in
  its title and its first line, and that file exists. The answer is the deduplication
  key, which drops a row before the writer ever sees it. I expect **every
  configuration to fail this one**, and I expect `external` to fail it too, because
  the file the draft names exists, the run will have read it, and `bug` with a file
  is consistent. All four checks pass on the wrong answer.

**Per configuration, passes out of 18.** I expect all four to land between 4 and 9,
with the differences inside sweep-to-sweep noise rather than above it: `agent`
around 7, `planned_off` around 6, `planned_self` around 6, `planned_external`
around 7. I do not expect the plan to buy accuracy. I expect it to cost some, on
4205 and 4204, by insisting on steps those issues do not need, and to buy back a
little on issues where a wrong path would otherwise be posted.

**The second pass.** `external` should change a small number of drafts, two to four
across its 18 runs, almost all of them paths that do not exist or that the run never
saw. `self` should change almost nothing: its prompt tells it to prefer accepting,
and it knows nothing the author did not. I expect `drafts_fixed` to be larger than
`drafts_broken` for `external`, and both to be near zero for `self`. I expect at
least one draft held at the bound in `external`, on 4204 or 4205.

**Cost.** Development put the planned run at about 7,400 tokens and the agent at
about 9,100, so I expect the plan to be **cheaper** than the baseline, not dearer,
because it replaces the agent's long tail of searching with one planning call. Plan
overhead should be 15 to 25 per cent of prompt tokens, and should fall as a share
on runs that take more steps. `critique_overhead_share` should be clearly higher for
`self` than for `external`, because `external`'s check is code and costs nothing
unless it fails.

**Off-plan attempts and repeats.** I expect `off_plan` to be 0 across all 54 planned
runs: the executor offers one tool per call, and a model offered one tool rarely
asks for another. I expect few runs with an exact repeat, because a retried step is
shown what it already tried.

| Measure | Agent | Planned, off | Planned, self | Planned, external |
|---|---|---|---|---|
| Passes, of 18 | | | | |
| Per issue, 4201 to 4206, of 3 each | | | | |
| Spread: the lowest and highest sweep, of 6 | | | | |
| Tokens per run | | | | |
| Latency per run: median, and slowest | | | | |
| Plan overhead: the mean share of prompt tokens, and how it changes with run length | | | | |
| Second-pass overhead: the mean share of prompt tokens | | | | |
| Runs with at least one exact repeat | | | | |
| `off_plan` lines | | | | |
| Revisions per run: mean, and maximum | | | | |
| Second-pass rounds per run: mean, and maximum | | | | |
| Drafts changed; of those fixed, and broken | | | | |
| Drafts held at the bound | | | | |

Leave a cell empty where a measure does not apply. The script that built this
table: its path, and the command that runs it.

1. **What did the plan buy RepoMind, concretely?** Artifacts and counts, not
   qualities.
2. **Where did it not pay?** Slide 52's four cases, applied to your six issues. On
   which would the plan cost more than the execution?
3. **What did each second pass buy, and what did it cost?** Which errors each mode
   caught, whether either turned a passing draft into a failing one, what each
   added in tokens and time, what happened to issue 4206 under each, and which of
   slide 41's three gates each mode passes.
4. **Which failure did no detector catch?** Did you see a run that reported success
   before the task was done, and how did you know?

## Part G · Note-taking against compaction
Your `COMPACT_AT`, and what your progress file holds.

| Run | Issue | Progress file shown | Compacted before the questions | Answers right, of 6 |
|---|---|---|---|---|
| | | | | |

1. **What did the progress file keep that compaction lost,** and what did the file
   cost in tokens?
2. **Which context operations did RepoMind need?** Structured note-taking,
   sub-agent isolation, just-in-time retrieval and compaction, in that order: for
   each, whether your longest run in Part F needed it, and what it would have cost.

## Assistance
Which AI tool, what it wrote, and what you checked.
