# CHANGES.md

Three lines per assignment: what it added, what it removed, what it constrained.
Removals are logged like additions.

## Assignment 1
- **Added:** a bounded tool loop; four ways to triage an issue (a direct call, a workflow, an agent, and a hybrid of the two); a grounded success check that reads the tracker; a results script
- **Removed:** nothing
- **Constrained:** every agent run to three bounds checked in code (steps, tokens, wall clock); success to what the tracker holds for the run's ID

## Assignment 2
- **Added:** a plan artifact written as JSON before the issue is read, and a schema that compiles under strict mode; a validator running four checks on it before anything executes, with a reject exit that escalates; a revision checkpoint after the first search, and a reviser that sees step results but never the issue; a second pass before posting, in three modes (none, the model rereading its own draft, and checks in code against the repository and the run's own trace); three detectors and Lecture 2's ladder over a trace; a diff of the plan against what ran; a progress file written outside the conversation, and a compaction of the history past a token threshold
- **Removed:** nothing
- **Constrained:** the executor to the active plan, which it may run, retry or halt but never add to, drop from or reorder; the comment to one post, after the second pass's last round, and none at all when a draft is still failing or a plan never passed the checks; the planner and the reviser to requests carrying no issue text, so untrusted text can change what a step carries and never which steps run
