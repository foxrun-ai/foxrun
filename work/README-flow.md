---
type: doc
workspace: system
timestamp: 2026-10-19T19:35:51-04:00
---
# Flow runner

`work/flow.py` runs graphs and loops. It uses Python 3.9 and the standard library only.
It has two commands: `run` and `status`.

## Where a flow lives

- A local workflow: `<workspace>/workflows/<name>.yaml`.
- A released shared workflow: `skillwright/workflows/<name>.yaml`.
- A released product fallback: `skillwright/workflows/.product/<name>.yaml`.

The local workflow wins, then the shelf, then the product fallback. Authoring source never changes a live workflow.
- The flow of one skill: `skills/<name>/flow.yaml` or `skillwright/skills/<name>/flow.yaml`.
- A workspace's own flow: `<workspace>/skills/<name>/flow.yaml`. With `--workspace`, it wins over a shared one.

The YAML file runs. A Markdown page beside it explains it.
A place that is not there is read as empty. `status` names it.

Two starter workflows ship, each with its page. Vote stays on the person's own shelf:

| Flow | What it does |
|---|---|
| `review` | A builder drafts; routine and judgment readers check it; the loop permits at most three repairs. |
| `research` | Three researchers look on their own at the same time; a writer merges what they found. |

## Commands

```sh
python3 "$FOXRUN_HOME/work/flow.py" status                       # every flow, every place, every run
python3 "$FOXRUN_HOME/work/flow.py" run review --input job="..." --dry-run    # check it; make nothing
python3 "$FOXRUN_HOME/work/flow.py" run review --input job="..." [--workspace <name>] [--task <id>]
python3 "$FOXRUN_HOME/work/flow.py" run --resume <run>           # move a run forward
python3 "$FOXRUN_HOME/work/flow.py" run --resume <run> --yes <step> --words "<the exact words>"
python3 "$FOXRUN_HOME/work/flow.py" run --resume <run> --no <step> --words "<the exact words>"
python3 "$FOXRUN_HOME/work/flow.py" status <run> [--json]        # where one run stands
```

`--no-workers` with `run` starts no worker. Every member step is then done by hand.
Exit codes: 0 fine; 1 the run is blocked or refused; 2 the call is refused; 3 another call holds the run; 4 an error it did not expect.

## The shape

```yaml
version: 1
flow: review                 # the file name
kind: workflow               # or flow, for the flow.yaml of one skill
purpose: "One sentence."
inputs:
  job: {required: true, what: "The job"}
lead: builder                # optional: the member who leads the team
worker_minutes: 30           # optional: the time each worker gets, 1 to 240
members:                     # the team
  builder: {what: "Does the job.", runtime: claude, model: <model>, effort: high, access: write}
  reader: {seat: <seat>, runtime: codex, access: read}
graph:
  build:
    member: builder
    needs: []
    output: "What the step gives."
    done_when: {file: build.md}
  read:
    member: reader
    needs: [build]
    verdict: true            # the first line of read.md is verdict: pass or verdict: fail
    done_when: {file: read.md}
  publish:
    run: [python3, tools/publish.py]    # a code step: a script inside the system home
    needs: [read]
    gate: production         # waits for the person's yes
loop:
  repair: {on: read, repeat: [build, read], max_rounds: 3}
rules:
  - "The reader never changes the work it reads."
```

A member has `seat` (a seat file: `<workspace>/team/<seat>.md` or `agents/<seat>.md`), `runtime` (claude, codex, hermes), or `what`.
It may add `model`, `effort` (low to max), and `access` (read, the default, or write).
The members block is the team. One file holds a team and its graph. The runner does not read `config/squads/`.
A step has `member` or `run`, never both. `needs` sets the order. A step starts only when every step it needs is done.
Cycles, unknown keys, and unknown steps are refused before a run starts.

## Workers

A member with a `runtime` is a worker. When its step is ready, `run` and `run --resume` start it.
All ready workers start at the same time. The runner waits for each, up to `worker_minutes`.
The runner asks the installed resolver `skills/orchestrate/bin/orchestrate` in the system home for a one-shot route.
The `orchestrate` skill ships with the product and installs on that shelf, for Claude and Codex; Hermes is optional.
`access: read` asks for a read-only route; `access: write` asks for one that may change files.
The member's `model` and `effort` go into the native command. The route keeps its safety flags.
Workers work in the workspace folder with `--workspace`, else in the run folder.

Each worker gets a brief: the step, its job, the inputs, the full paths of the earlier results, and the rules.
In a repair round, the brief also lists the results of the round before, under `runner/attempts/`.
The worker's final reply is its result. The runner writes it at the step's file, unless the worker wrote that file itself.
It never overwrites a file. Each start is kept in `runner/workers/<step>-<try>/`: brief, route, command, output, end.
A worker that gives no result leaves its step ready. The next `run --resume` starts it again.
With no installed resolver, the readout names it, and the step is done by hand.

A member with no `runtime` is done by hand. The readout shows `NEXT`, the file to write, and the next command.

## The loop and the gate

`loop.repair` names a step with `verdict: true`. On `verdict: fail`, that round moves to `runner/attempts/<n>/`.
The `repeat` steps, and every step after them, run again. `max_rounds` counts repair rounds, from 1 to 5.
When no round is left, the run stops as blocked, with the last review.

A step with `gate` waits for the person. Only `--yes <step> --words "..."` records a yes, for that exact result.
A yes file the runner did not record is not a yes. A `--no` ends the whole run as refused.

## The tracker

With `--task <id>`, each worker step and each code step is a run on that task (`work/work.py run-start` and `run-end`).
The run's proof is the step's result file. A step done by hand is part of the lead's own run.
The tracker is the workspace's `data.db` when it has one, else the system `data.db` (the rule of `work.py --workspace`).
The task must be there, or no run starts.

## The run folder

Each run is `runs/<date>-<flow>/` in the system home.
A run for a workspace with its own `data.db` is `<workspace>/history/runs/<date>-<flow>/`, next to its tracker.
A run name is one name in every runs folder. `status` lists the runs of each.
`runner/` holds what only the runner writes: `run.yaml` (the frozen definition and its sha256), `events.jsonl`, `lock`, `end.json`, `decisions/`, `attempts/`, `workers/`.
Every other file is the result of one step, at the name its `done_when` gives.
A run works from its frozen copy. A later change to the flow file changes nothing in that run.
