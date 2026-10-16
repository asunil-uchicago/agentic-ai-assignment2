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
| `good_export_fix.json` | | |
| `good_triage.json` | | |
| `s18_specimen.json` | | |

Your re-plan bound, `MAX_REPLANS`, and one line on why. How many of your planner's
plans, in your measured runs, broke the schema or did not end with `post_comment`
(your `schema` lines), out of how many plans.

## Part C · Revision at a checkpoint
The checkpoint's check, in one sentence, and your revision bound, `MAX_REVISIONS`.

## Part D · A second pass before posting
Your four external checks, one line each, and your bound, `MAX_ROUNDS`, in one
line. For each mode, `off`, `self` and `external`, which of slide 41's three gates
it passes: can a check find the error, does the critic know more than the agent,
is there a limit and a log?

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
