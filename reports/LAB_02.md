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

### How those predictions fared

| Prediction | Outcome |
|---|---|
| 4206 fails in every configuration, `external` included | **right**, 0 of 3 in all four, and `external` passed the wrong file on all nine planned runs |
| `off_plan` is 0 across all 54 planned runs | **right**, 0 |
| `external` costs less than `self` | **right**, 0.4 per cent of prompt tokens against 8.4 |
| Few runs with an exact repeat | **right**, 1 run, and it was the agent's |
| 4205 is where the plan hurts | **half right**: `planned_off` lost one run to it, but `external` matched the agent at 3 of 3, and the damage came from `self`, which I had not expected to do harm at all |
| All four between 4 and 9 of 18 | **wrong**, `planned_self` came in at 2 |
| `self` changes almost nothing | **wrong**, and the most useful thing measured: it changed 2 drafts, broke both, and held 3 more |
| The plan is cheaper than the agent | **wrong**, 10,189 tokens against 9,592; the planning call is not paid for by shorter searching |
| `drafts_fixed` exceeds `drafts_broken` for `external` | **neither**, both 0; `external` changed one draft and the run still failed |
| At least one draft held at the bound in `external` | **wrong**, 0 in `external` and 3 in `self` |
| 4203's checkpoint fires on nearly every run | **right** on firing, wrong on hope: it fired, and all nine planned runs still failed |

The three predictions about cost and about `self` were wrong in the same direction:
I assumed a second pass that knows nothing new would be inert, and that planning
would pay for itself by shortening the search. Neither held.

| Measure | Agent | Planned, off | Planned, self | Planned, external |
|---|---|---|---|---|
| Passes, of 18 | 8 | 4 | 2 | 6 |
| Per issue, 4201 to 4206, of 3 each | 3, 0, 2, 0, 3, 0 | 2, 0, 0, 0, 2, 0 | 2, 0, 0, 0, 0, 0 | 3, 0, 0, 0, 3, 0 |
| Spread: the lowest and highest sweep, of 6 | 2 to 3 | 0 to 2 | 0 to 1 | 2 to 2 |
| Tokens per run | 9,592 | 10,189 | 11,843 | 10,449 |
| Latency per run: median, and slowest | 6.3 s, 11.5 s | 7.2 s, 13.8 s | 11.5 s, 14.6 s | 8.2 s, 16.4 s |
| Plan overhead: the mean share of prompt tokens, and how it changes with run length | | 0.231 | 0.245 | 0.246 |
| Second-pass overhead: the mean share of prompt tokens | | | 0.084 | 0.004 |
| Runs with at least one exact repeat | 1 | 0 | 0 | 0 |
| `off_plan` lines | | 0 | 0 | 0 |
| Revisions per run: mean, and maximum | | 0.78, 2 | 1.06, 2 | 0.89, 2 |
| Second-pass rounds per run: mean, and maximum | | | 0.89, 2 | 0.83, 2 |
| Drafts changed; of those fixed, and broken | | | 2; 0 fixed, 2 broken | 1; 0 fixed, 0 broken |
| Drafts held at the bound | | | 3 | 0 |

Plan overhead against run length, over all 54 planned runs, as the plan call alone
and as plan plus revise:

| Model calls | Runs | Plan call alone | Plan and revise |
|---|---|---|---|
| 4 | 7 | 0.211 | 0.211 |
| 6 | 9 | 0.141 | 0.187 |
| 8 | 11 | 0.116 | 0.334 |
| 10 | 6 | 0.088 | 0.248 |

The plan call's share falls from 21 to 9 per cent as runs lengthen, because it is one
fixed call against a growing conversation. Revisions move the other way, so the two
together stay near a quarter of all prompt tokens however long the run.

Built by `eval/summarize_02.py`, run as `python -m eval.summarize_02`.

### 1. What did the plan buy RepoMind, concretely?

Artifacts and counts, over the 54 planned runs:

- **103 `plan` lines in the run logs**, one version 1 per run and 49 revisions. Before
  this assignment nothing recorded what a run intended.
- **A validator that ran before any tool call in all 54 runs**, and rejected 3 plans
  outright. Those 3 runs made a second planner call; no tool ran from a rejected
  plan, in any run.
- **Version 1 logged before the first `tool_call` line in all 54 runs**, so there is
  exactly one place a person could have approved the run, rather than one per action.
- **A diff of the plan against the trace for every run.** On the 4203 runs it shows
  all four steps `executed` and two `extra` calls, which is how a reader sees the
  executor retried a search twice without the plan changing.
- **0 `off_plan` lines in 54 runs.** The boundary was never crossed, which is a count
  rather than a claim.
- **1 run with an exact repeat, and it was the agent's.** None of the 54 planned runs
  repeated a tool call, because a retried step is shown what it already tried.

And one thing the plan bought that shows up as accuracy rather than as an artifact:
**the planned way posts.** The agent posted nothing in 7 of 18 runs, five of them
hitting the turn limit mid-search. `planned_off` posted nothing in 3 of 18. A plan
whose last step is `post_comment` reaches a decision or escalates; it does not run
out of turns halfway through exploring.

What the plan did **not** buy is accuracy. `agent` passed 8 of 18, `planned_off` 4.
On 4203 the agent passed 2 of 3 and all nine planned runs failed, for a reason worth
naming: the agent searched `Malformed row`, saw the one hit in `src/i18n/en.json`,
then searched **`rowShape`**, the translation key visible in that result, and found
the parser. My executor could not do that, because a step result records the paths a
search returned and not the matching lines, so a retry never sees the key. The
freedom to pivot on the content of a result is what the plan took away.

### What this model can reach at all, from Assignment 1

Three of the six issues are not reachable on this model, and that is measured rather
than guessed. Assignment 1 ran all four of its ways over the same six issues on
`gpt-4o-mini`, ten sweeps each, 60 runs a way:

| | Assignment 1, of 60 | 4201 | 4202 | 4203 | 4204 | 4205 | 4206 |
|---|---|---|---|---|---|---|---|
| direct | 20 (33%) | 0 | 0 | 10 | 0 | 10 | 0 |
| workflow | 20 (33%) | 10 | 0 | 0 | 0 | 10 | 0 |
| agent | 20 (33%) | 10 | 0 | 0 | 0 | 10 | 0 |
| hybrid | 20 (33%) | 10 | 0 | 0 | 0 | 10 | 0 |

**4202, 4204 and 4206 scored zero in every way, in all 240 runs.** The same three
scored zero in all 72 runs here. Against that baseline the figures in this
assignment read differently: this agent at 8 of 18 (44%) is above Assignment 1's
agent, helped by now having `read_file`; `planned_external` at 6 of 18 (33%) matches
the old baseline exactly; `planned_off` at 4 (22%) is below it; and `planned_self`
at 2 (11%) is below every way Assignment 1 measured.

So the ceiling on this fixture set is two or three issues out of six, whatever is
built on top of this model. The honest reading of the table above is not that the
plan failed to reach the answers, but that only `planned_self` moved the number by
more than the spread, and it moved it down.

### 2. Where did it not pay?

Slide 52's four cases, against these six issues:

- **The task is one step.** 4205 asks whether uploaded files are kept. The answer is
  `question` with `file: none` and there is nothing in the repository to find. Every
  plan nonetheless contains a search and a read, because it is written before the
  issue is known. The agent passed 3 of 3; `planned_off` 2 of 3, losing one run to a
  search that found no source file. This is the clearest case in the set where the
  plan cost more than the execution.
- **The steps are fully known in advance, so write a workflow.** This is the
  strongest finding of the part. The planner wrote **the identical four-step shape in
  all 54 runs**: `read_issue`, `search_repo`, `read_file`, `post_comment`. Not a
  similar shape, the same one, every time, for six different issues. If the plan is
  known before the issue is read and never varies, the planning call buys nothing
  that a hard-coded workflow would not, and Assignment 1 already had that workflow.
  Nine per cent to 21 per cent of every run's prompt tokens went on deciding
  something that was never in doubt.
- **The plan would cost more than the work.** 4205 again, and 4202, where the whole
  task is to notice that a request for a new export format is a `feature` and to name
  where export formats live. Both are one search and a judgement.
- **Nothing will ever read the plan.** This one does not apply, and is the reason the
  rest is worth having: the plan was read, by the validator before every run, by the
  diff after each, and by the detectors in Part E.

### 3. What did each second pass buy, and what did it cost?

| | `off` | `self` | `external` |
|---|---|---|---|
| Passes of 18 | 4 | **2** | **6** |
| Posted nothing | 3 | **8** | 4 |
| Drafts changed | | 2 | 1 |
| of those, fixed / broken | | 0 / **2** | 0 / 0 |
| Held at the bound | | **3** | 0 |
| Share of prompt tokens | 0 | 0.084 | **0.004** |
| Median latency | 7.2 s | 11.5 s | 8.2 s |

**`self` was the worst configuration measured, and it was worse than no second pass
at all.** It did not merely fail to help: of the drafts it changed, 0 were fixed and
2 were broken, and it held 3 more at the bound so they were never posted. Slide 36
warns that a second pass can make a right answer wrong; here it did so on every
draft it touched.

The mechanism is visible in the trace, on 4205. All three `self` runs drafted
`label: question` with `file: none`, which is the right answer, and all three ended
`escalated` with nothing posted. The critic's own reason, recorded in the `critique`
line, was:

> "A 'question' label must name 'none', but the draft incorrectly identifies the file
> as 'none'."

It states the rule and then declares the draft wrong for obeying it. On the other two
runs it rewrote `file: none` into `docs/API.md` and `README.md`, then rejected those
too. **The same check, written in code as `verify`'s check 4, passed 4205 three
times out of three.** That is slide 33's question answered as sharply as a measurement
can answer it: the critic that knows nothing the author did not know invented a
fault, and the check that knows the repository did not.

**`external` bought 2 passes over `off` and cost almost nothing**, 0.4 per cent of
prompt tokens against `self`'s 8.4, because its check is code and a passing draft
costs no model call at all. But the 2 passes sit inside the sweep spread (`off` 0 to
2, `external` 2 to 2), so this pilot cannot separate them from noise. What it can
say is that `external` broke nothing and held nothing, while `self` broke everything
it touched.

**Issue 4206 under each mode.** `off`, `self` and `external` all posted
`src/export/csv.ts` on all nine runs. The answer is `src/ingest/dedupe.ts`. The
issue's title and first line blame `csv.ts` by name, the file exists, and every run
read it, so `external`'s four checks all pass: it parses, the path exists, the run
saw it, and `bug` with a file agrees. **Verification against the repository and the
run's own record cannot tell that a file the run really did read is not the guilty
one.** The agent failed 4206 differently: all three runs searched nine to eleven
times, hit the turn limit, and posted nothing at all. One configuration is
confidently wrong, the other is silent, and neither is right.

Slide 41's three gates are tabulated in Part D. Only `external` passes all three.

### 4. Which failure did no detector catch?

Premature stopping, and I saw it in my own runs rather than only in slide 51's.

Take a `planned_off` run on 4203. It posted `file: src/api/uploads.ts`; the answer is
`src/ingest/parser.ts`. Run the ladder over its plan and its trace:

| Question | Did the detector fire? |
|---|---|
| q1 Did any two steps do the same thing? | no, no repeats |
| q2 Is any step's result never used? | no, every result was used |
| q3 Did every planned step execute? | no, all four ran and returned |

Every detector is silent. The diff labels all four steps `executed`. The run ended
`completed`, with a comment posted and every step's `expected_result` satisfied: the
search returned paths, the read returned a file, the comment was posted. Nothing
inside the run disagrees with it. The run reports success, and it is wrong, and the
only thing that says so is `fixtures/answers.yaml`, which no part of the run may read.

That is the shape of the failure across the whole set. Of the 12 issue-configuration
cells that failed, the great majority failed exactly this way: a complete plan,
completely executed, every expected result met, and the wrong file named. Three of
the six issues, 4202, 4204 and 4206, were failed by all four configurations, and no
detector fired on any of them. The expected-result check catches a step that was
skipped; it cannot catch a plan that was too short, nor a step that returned
something true and useless.

## Part G · Note-taking against compaction

**`COMPACT_AT = 40` tokens**, counted over the history with
`harness.scripted.estimate_tokens`. A deliberately low test setting, not advice: a
RepoMind run's history is four or five one-line step results, perhaps seventy
tokens in all, so any realistic threshold would never be crossed and nothing would
be measured. At 40 the compaction fires partway through, with two steps still to
run, which is where it can actually cost the run something.

**What the progress file holds**, at `runs/<run_id>.progress.json`, rewritten after
every step: an `about` line saying it is a record and not a list of things to do,
`steps_done` as the ids that have run in order, `paths` as every path a search
returned or a read read in order, and a `paths_means` line saying what those paths
are. It never holds a search term, because the terms are taken from the issue's
text and this file outlives the conversation that may carry it.

### Predictions, written 2026-10-16, before Part G's 12 runs

- **I expect the progress file to buy little or nothing, and I expect that to be
  the finding.** RepoMind's runs are four or five steps long. The honest first
  question about context is how long your runs are (slide 30), and these are short
  enough that compaction has almost nothing to throw away.
- **I expect `--notes off` to score close to 6 of 6 anyway**, because of a choice
  made in the compaction itself: `prompts/summarize.md` tells the summariser to
  keep every file path exactly as it appears, ahead of everything else. A
  compaction told to preserve the paths does preserve them, so the conversation
  still holds what the questions ask about. A generic summariser would lose more,
  and the gap between those two is a note-taking decision made inside the
  compaction rather than outside it.
- **I expect `--notes on` to score 6 of 6 on nearly every run**, since the file
  lists exactly the paths the questions are drawn from.
- **I expect the errors, where they occur, to be false `yes` answers** on the three
  filler paths rather than false `no` answers on the paths the run saw. The filler
  paths are real repository files, and a model asked whether it saw a plausible
  file is being invited to agree.
- **I expect 4204 to be the interesting run.** If its searches find nothing, as the
  handout suggests, the run escalates before it posts, and there may be fewer than
  three paths to ask about; the six questions then lean on filler paths, and the
  score becomes mostly a test of whether the model will deny seeing things it never
  saw.
- **Cost:** the file costs one write per step, which is free, plus its text on
  every executor call with `--notes on`. At roughly 60 tokens of JSON across four
  calls I expect under 300 prompt tokens a run, well under 5 per cent.

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
