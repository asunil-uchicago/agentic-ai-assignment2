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
How your diff matches a traced call to a plan step.

**The looping run.** Questions 1 to 3, each with the turns or steps that fired, and
how you answered question 2 without `depends_on`. Question 4, in one sentence.

**Slide 51's run.** Questions 1 to 3, each with the steps that fired. Question 4, in
one sentence. The diff's label for every step of the plan.

## Part F · What the plan and the second pass bought
Three sweeps a configuration: a pilot, not a settled difference.

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
