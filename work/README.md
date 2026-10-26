---
type: module
workspace: foxrun
name: work
tier: base
built_by: ours
version: 0.3.0
requires: []
timestamp: 2026-09-21T03:30:00-04:00
status: draft
tags: [work, modules]
---

# Work

Work creates and reads tracker tasks.
Use --workspace to select a workspace tracker. Use --db to select a specific tracker.

From the system folder, inspect command options:

```sh
python3 work/work.py --help
```

Read [the system guide](../GUIDE.md) and [the global contract](../profile/AGENTS.md).

A signer other than the finisher, owner, or claimant can accept after evidence review.
Evidence is a done receipt or a hashed proof attachment. A plain `Proof:` comment does not qualify.
No lead seat is required.

`accept --approval <id>` uses recorded task approval as signer and records the acting seat and approval ID.

## Flows

`flow.py` runs a workflow or a flow. It has two words.

```sh
python3 work/flow.py run <flow> --workspace <workspace> --input <key>=<value>
python3 work/flow.py run --resume <run>
python3 work/flow.py status
python3 work/flow.py status <run>
```

A workflow connects many skills. It is one file in `skillwright/workflows/`.
A flow belongs to one skill. It is the file `flow.yaml` inside that skill.
Both files have one shape: `members`, `graph`, `loop`.

Two rules hold at every place where `flow.py` decides.

1. **Fail closed.** What `flow.py` can not prove is valid stops the run, before a step is offered and before code runs. It never goes on with what is left.
2. **Strict schema.** The table `SCHEMA` in `flow.py` lists every key of a definition, of the run file, of an event, and of the record of a yes, with its type.
   A key that is not in the table, a wrong type, an empty value: each is a named problem, and the file is not valid.
   One validator checks a definition before a run starts and again each time a run is read.

One rule says which file a name means. `run` and `status` use the same rule and see the same files.

| Level | Place | File |
|---|---|---|
| workspace | the skills of a workspace | `<workspace>/skills/<name>/flow.yaml` |
| shared | the system workflows | `skillwright/workflows/<name>.yaml` |
| shared | the shelf | `skills/<name>/flow.yaml` |
| shared | the small-talk skills | `small-talk/skills/<name>/flow.yaml` |
| shared | the installed product skills | `skillwright/skills/<name>/flow.yaml` |

A name resolves only when every place it could come from was read, and every definition found under that name is valid.
A run with `--workspace` reads the place of that workspace and the four shared places. A shared run reads the four shared places.
A place that is missing, is a file, is a link that leads nowhere, or can not be listed stops every name for the runs that read it.
The error names the place. A lower level is never taken in its stead. `status` shows the place and ends with exit code 1.
The workspaces are the list `workspaces` in `config/person.json`. With no list, each folder of the portfolio is a workspace.
With `--workspace`, the definition of that workspace wins. The run and `status` say: local definition overrides shared.
A name that two places of one level define with different text is refused, with both paths. The same text in two places is one definition.
A definition is one real file. A file that many places reach through links is one definition with many places.
`status` shows it one time, with each place and with each workspace that can run it.
A link from a workspace to a shared file is that shared file. It is not an override.
A flow can be given by its path. The path must be one of the places above.
A shared path gives a shared run. `--workspace` puts the run in that workspace. A path inside a workspace gives a run in that workspace only.
The run and the dry run say `Workspace: <name>` or `Workspace: none (a shared run)`.
A file outside the two homes is never taken. A link is followed first, then checked.
A link loop and a link with no target are listed as not valid and are never taken.
A file that can not be read as a flow is listed as not valid. It stops its own name in every place, and no other name.
A member with a `seat` needs its seat file: `<workspace>/team/<seat>.md`, or `agents/<seat>.md`. Without it no run starts.
A code step is `run: [python3, <script>]`. The script is a file inside the system home. Without it no run starts.
A skill of a step can be `null`, or a name that is not built yet. The readout says `not bound` or `(not built)`.
A run keeps the full path and the sha256 of the file it took. It works from its frozen copy only. A later change of the file is shown and changes nothing in the run.
Each call reads and checks the whole run first: `runner/run.yaml`, each line of `runner/events.jsonl`, the seat files, the scripts.
An event that `flow.py` does not know, an unknown key, a missing key, a key two times: the call stops, and nothing is accepted or run.
`run` checks the file, makes the folder `runs/<date>-<flow>/`, and names the next step.
A member writes its result as a file into that folder. Then `run --resume` accepts it and moves the run forward.
A result counts only when every step it needs is done. A result written before that is not accepted.
An accepted result is frozen. If its file changes, the run is blocked.
A review step starts its file with `verdict: pass` or `verdict: fail`. A fail starts a repair round.
A step with a gate waits for the person. Only a recorded yes passes a gate:

```sh
python3 work/flow.py run --resume <run> --yes <step> --words "<the exact words>"
python3 work/flow.py run --resume <run> --no <step> --words "<the exact words>"
```

The yes is for one exact result. A changed result needs a new yes. A yes file that `flow.py` did not record is not a yes.
A code step with a gate does not run before its yes.
A no ends the whole run. The state is `refused`, and it is final: nothing in any branch is accepted, offered, or run after it.
`run --resume` on a refused run changes nothing and says so. Only a new run starts work again.
A blocked run does nothing more in any branch until the cause is gone. A run that is done is final too.
`--dry-run` changes nothing, with every other flag. With `--resume` it says what a real call would do first.
One program at a time works on a run. The lock is the file `runner/lock`. A second caller fails at once with exit code 3.
A lock whose program is gone is reported. `flow.py` never removes it: read `runner/events.jsonl`, then remove the lock by hand.
Before a code step runs, the event `code-start` is written. A start with no end blocks the run: the step may have run, and it is not run again.
`status` reads only. It changes nothing. It ends with 1 when a place can not be read, a definition is not valid, or a run can not be read.
Exit codes: `0` fine. `1` the run is blocked or refused, or `status` found a problem. `2` the call is refused. `3` another program holds the run. `4` an error `flow.py` did not expect; it stops.

A run folder has two kinds of file, and they never mix:

```text
runs/<date>-<flow>/
├─ runner/          only flow.py writes here: run.yaml, events.jsonl, lock, end.json, decisions/, attempts/
└─ <file>           the result of one step, at the name the step gives in done_when
```

Nothing in `runner/` is ever read as the result of a step. `flow.py` never writes or overwrites a result.
A flow is refused before a run starts when a step names a file of the runner, the folder `runner`, a `.yes.md` or `.no.md` name,
the file of another step, or a path with a folder or `..`. Capital and small letters count as the same name.

## Collections
Object types and supertypes follow the installed system SCHEMA.md.
Collection names identify the business subjects; they are the exact SQL names.
`measure_history` is a trend stored in a SQLite table.

| Collection | Object type | Supertype | Lens | Database type | Who writes it |
|---|---|---|---|---|---|
| `functions` | table | database | records | table | Person and authorized local writers |
| `goals` | table | database | records | table | Person and authorized local writers |
| `measures` | table | database | records | table | Person and authorized local writers |
| `measure_history` | trend | database | history | trend | Authorized measure writer |
| `programs` | table | database | records | table | Program-control seed |
| `themes` | table | database | records | table | Program-control seed |
| `projects` | table | database | records | table | Person and authorized local writers |
| `tasks` | table | database | records | table | Authorized task writers; `work` for these agent actions |
| `runs` | table | database | history | table | `work run-start` and `work run-end` |
| `task_links` | table | database | records | table | Authorized link writers; `work done` adds receipts |
| `activity` | table | database | history | table | Authorized change writers; `work` records selected actions |
| `comments` | table | database | history | table | Authorized writers; `work comment`, `block`, and `done` |
| `attachments` | table | database | records | table | Authorized attachment writers |
| `decisions` | table | database | records | table | Authorized writers recording decisions and their status |
| `approvals` | table | database | history | table | Authorized writer recording Person's response |
| `incidents` | table | database | history | table | Incident loader and `work incident-*` |
| `bugs` | table | database | records | table | Incident loader and `work bug-open` |
| `record_links` | table | database | records | table | Incident loader and `work link` |
| `open_decisions` | view | database | records | view | No row writer; blueprint defines selection |
| `open_tasks` | view | database | records | view | No row writer; blueprint defines selection |
| `needs_me` | view | database | records | view | No row writer; blueprint defines selection |
| `close_now` | view | database | records | view | No row writer; blueprint defines selection |
| `needs_business_input` | view | database | records | view | No row writer; blueprint defines selection |
| `this_week` | view | database | records | view | No row writer; blueprint defines selection |
| `next_step` | view | database | records | view | No row writer; blueprint defines selection |
| `eisenhower` | view | database | records | view | No row writer; blueprint defines selection |
| `program_plan` | view | database | records | view | No row writer; blueprint defines selection |
| `stream_brief` | view | database | records | view | No row writer; blueprint defines selection |
