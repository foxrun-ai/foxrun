---
type: doc
workspace: system
timestamp: 2026-10-20T20:01:52-04:00
---
# review

A builder does one job. A reader checks the work. When the reader fails it, the builder fixes it and the reader checks again, up to three fixes.

The file `review.yaml` runs. This page explains it.

## Run it

```sh
python3 "$FOXRUN_HOME/work/flow.py" run review --input job="Write a one-page guide to our returns rule" --input bar="Plain words, one page, every step numbered"
```

Add `--task <id>` to record each step as a run on that task. Add `--workspace <name>` to work in that workspace's folder.

## The team

| Member | Does | Runtime | Access |
|---|---|---|---|
| builder (the lead) | Does the job and records material progress, with proof. | codex | write |
| routine | Checks facts, tests, and relevant saved failures. | codex | read |
| checker | Rechecks findings against the proof. | codex | read |
| reader | Gives the judgment verdict against the job and the bar. | claude | read |

## The graph

`build` → `routine-read` → `recheck` → `read`. The reader's first line is `verdict: pass` or `verdict: fail`.

## The loop

On `verdict: fail`, the last round moves to `runner/attempts/<n>/`, and all four steps run again. The builder reads the last `read.md` there. After three fixes with no pass, the run stops as blocked, with the last read.

## Change it

Copy `review.yaml` to `<workspace>/workflows/<name>.yaml` for a local workflow. Change `runtime`, `model`, or `effort` for a member. Set `max_rounds` from 1 to 5.

## Bindings

Build uses `log` for material progress on an existing task. Routine-read uses `runtime-session-search` for earlier failures.
Build never creates a task just for a receipt. Reads never change the work.

Builder uses dev-lean build and Toolsmith. Routine uses routine-read and Keeper.
Checker uses recheck and Skillwright. Reader uses judgment-read and Architect.
The final reader fails when any required check fails or a finding lacks proof of resolution.

The runner counts repairs. `max_rounds: 3` permits one initial draft and three redrafts.
