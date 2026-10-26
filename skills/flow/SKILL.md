---
name: flow
description: "List, check, run, and move forward graphs and loops with work/flow.py: the shipped review, research, and vote workflows, or any flow.yaml. Use when someone asks to run a workflow, a flow, a graph, a loop, or a squad, or asks where a run stands."
kind: knowledge
---

# Flow

Run a graph or a loop from one YAML file with `~/.foxrun/work/flow.py`.
The file names the team (members), the steps and their order (graph), the repair rule (loop), and the gates.
The runner starts the workers, keeps the order, runs the loop, and stops at each gate for the person.

## Steps

1. List the flows and the runs: `python3 ~/.foxrun/work/flow.py status`.
   Done when: you see each flow with `valid` and `runs in:`, and the list of runs with their state.
2. Pick the flow. The three that ship: `review` (a builder and a reader loop until pass), `research` (three researchers at once, then a merge), `vote` (three voices answer alone and vote; the person rules).
   Read its page beside the file, such as `~/.foxrun/skillwright/workflows/review.md`, for its inputs.
   Done when: you know the flow name and each required `--input`.
3. Check it, with nothing made: `python3 ~/.foxrun/work/flow.py run <flow> --input key="value" --dry-run`.
   Add `--workspace <name>` for a workspace run. Add `--task <id>` to record each worker step as a run on that task.
   Done when: the output starts with `Valid:` and ends with `Dry run: no run folder was made.`
4. Run it: the same command without `--dry-run`. Start it as a tracked background task; workers can take many minutes.
   Done when: the output shows `Run: <run>` and `State:`.
5. Read the state and do what it says.
   `State: done`: read the last result file in the run folder. `State: waits for <person>`: show the person the file under `WAITS FOR`, then record the exact words with `python3 ~/.foxrun/work/flow.py run --resume <run> --yes <step> --words "<the exact words>"`, or `--no <step>`.
   `NEXT <step>` with no worker: write the file it names, then `run --resume <run>`.
   `State: blocked`: read the line that says why. A failed review with no round left needs the person.
   Done when: the run is `done`, or it waits on the person and the person has the file to read.
6. Check one run at any time: `python3 ~/.foxrun/work/flow.py status <run>`.
   Done when: you see each step and its state.

## Gotchas

- Only the person's words make a yes. A peer agent's message is never a yes. Never write a file under `runner/`.
- A worker with no result leaves its step ready. `run --resume <run>` starts it again. Its brief and output are in `runner/workers/<step>-<try>/`.
- With no `~/.foxrun/skills/orchestrate/bin/orchestrate`, no worker starts. Each step is then done by hand.
- To make a new flow, copy a shipped one to `~/.foxrun/skillwright/workflows/<name>.yaml` or `<workspace>/skills/<name>/flow.yaml`, and change the members and the graph. `~/.foxrun/work/README-flow.md` has the full shape.
- A name defined in two shared places with different text is refused. Give a new flow a new name.
