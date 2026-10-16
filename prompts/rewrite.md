A triage comment was drafted, checked before posting, and failed the check. Rewrite
it so that it passes, and answer with the rewritten comment and nothing else.

No preamble, no explanation of what you changed, no code fence. Your whole answer is
the comment, and its first two lines must be exactly:

```
label: <bug | feature | question | docs>
file: <path relative to the repository root, or none>
```

You are told what the check objected to. Fix that, and change nothing else: the
draft was produced by a run that did the searching and reading, and the rest of it
is more likely right than anything you would put in its place.

What the objections mean:

- **No file of that name exists.** The path was misremembered, usually its
  extension or a directory in the middle. Pick the closest path from the list of
  what the run actually saw, copied character for character.
- **This run never saw that path.** The draft named a file from general knowledge
  rather than from the run's own results. Replace it with one the run saw.
- **The label and the file disagree.** A `question` names `none`; every other label
  names a file. Change whichever of the two is wrong, and prefer changing the label:
  a run that found a responsible file has evidence, while `file: none` throws that
  evidence away and is almost never the right repair.
- **The first two lines do not parse.** Rewrite them in exactly the form above.

Name one file, never two, never a directory. Write the path bare, with no backticks,
no quotes, no line number and no repository prefix.
