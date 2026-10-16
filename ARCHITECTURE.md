# ARCHITECTURE.md · RepoMind on the seven layers

For each layer: what does this job, and where is it enforced. Cite code as a file
path and line number joined by a colon, inside backticks; a checker opens every
reference (`checks/FORMATS.md`, section 8). A layer held only by a sentence in a
prompt (any file under `prompts/`) is **EMPTY**, and so is a layer nothing does
yet. Status is one of: present, partial (say what is missing), or **EMPTY**. Each
assignment brings this file up to date.

What each layer is for (Lecture 1, slides 40 to 42):

- **Model**: reasoning, choosing tools, generating text.
- **Harness**: runs the loop, builds each prompt, trims old history.
- **Tools**: where the system acts on the world.
- **Memory & State**: what survives a step, a session, a restart.
- **Control & Policy**: what the system may do, and when it must ask.
- **Observability**: a step-by-step record of what it did.
- **Evaluation**: measuring quality, before and after release.

The table below is RepoMind after Assignment 2. The Harness row now cites the
validator and the boundary, and three other rows moved with them: a plan is state
that outlives a step, holding a draft back is a decision made in code rather than
asked for in a prompt, and the trace records intent as well as action.

| Layer | What does this job | Where it is enforced | Status |
|---|---|---|---|
| Model | The configured model, called only through the metered client | `harness/client.py:116` | present |
| Harness | The loop's three bounds, checked in code before every call; a validator that runs four checks on the plan before anything executes; an executor that refuses any call that is not the current step's tool | `agent/loop.py:38`, `agent/validator.py:55`, `ways/planned.py:135`, `ways/planned.py:257` | present |
| Tools | Four tools behind one registry (read_file arrived with Assignment 2's starter); post_comment stamps the run_id | `tools/__init__.py:52`, `harness/tracker.py:60` | present |
| Memory & State | The plan carries each step's status across the run; Part G's progress file is written outside the conversation, where a compaction cannot reach it | `ways/notes.py:101`, `ways/notes.py:154` | partial: within a run only, nothing survives a restart |
| Control & Policy | A draft that fails its check is held and the run escalates rather than posting; a plan that fails the checks never runs at all | `agent/critique.py:93`, `ways/planned.py:436`, `ways/planned.py:532` | partial: it refuses, but it still cannot ask a person and wait |
| Observability | A trace line per model call and per tool call, and now the plan itself, each revision, each second-pass round, each refused call and each compaction | `agent/loop.py:50`, `ways/planned.py:257` | partial: traces, no alerts |
| Evaluation | The grounded check reads the tracker, never the agent | `eval/check_triage.py:7` | partial: offline only |

**Empty layers: 0 of 7**, and four are partial. Assignment 2 emptied both of the
blanks, though neither is finished: Memory and State keeps a plan and a progress
file but nothing that survives a restart, and Control and Policy can refuse to post
but cannot yet hand a run to a person and wait for an answer. Lecture 1, slide 46 expects
four of the seven to be missing from a first build; Assignment 1 filled
Observability and Evaluation just enough to measure.
