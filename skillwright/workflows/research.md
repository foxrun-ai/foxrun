---
type: doc
workspace: system
timestamp: 2026-10-20T20:01:52-04:00
---
# research

Three researchers look at one question at the same time, each on its own. A writer then merges what they found into one answer.

The file `research.yaml` runs. This page explains it.

## Run it

```sh
python3 "$FOXRUN_HOME/work/flow.py" run research --input question="Which backup tool fits a small shop with one laptop?"
```

Add `--task <id>` to record each step as a run on that task.

## The team

| Member | Does | Runtime | Access |
|---|---|---|---|
| sources | Finds the primary sources: official pages, the code, the data. | codex | read |
| practice | Finds how others do it, and the results they got. | codex | read |
| doubt | Finds risks, limits, and evidence against the easy answer. | claude | read |
| writer (the lead) | Checks and merges findings, then records the material answer. | codex | write |

## The graph

`find-sources`, `find-practice`, and `find-doubt` need nothing, so they start together. `merge` needs all three and writes `answer.md`.

## The loop

None. Add a reader step with `verdict: true` and a `loop` to check the answer, as `review.yaml` does.

## Change it

Change a researcher's `what` and `output` to change its angle. Add a researcher: one member, one step, and its file in `merge`'s `needs`.

## Bindings

Practice uses `runtime-session-search` for saved examples. Merge uses `log` for material results on an existing task.
No task is created just for a receipt. A missing history source stays a reported gap.

Sources use dev-lean build, practice uses routine-read, doubt uses judgment-read, and writer uses recheck.
Their seats are Toolsmith, Keeper, Architect, and Skillwright. Models and effort match the approved dev-lean fill.
