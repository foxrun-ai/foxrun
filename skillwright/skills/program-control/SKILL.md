---
name: program-control
description: "Control tracked work in a Foxrun workspace tracker: find it, check for duplicates, claim tasks, record runs and evidence, report defects, and close out on evidence. Use when a job reads or writes the tracker, or when the person asks what is open, claimed, or next."
kind: knowledge
---

# Program Control

This is the hub for the tracker. The object skills (`task`, `stream`, `bug`, `program`, `goal`, `decision`) sit on it and use the same commands.
The reader is `~/.foxrun/work/program.py`. The writer is `~/.foxrun/work/work.py`. Run `work.py --help` and `<verb> -h` for each verb's arguments.
Never write tracker rows with hand SQL. If a verb is missing, say so and file the gap as a task.

For the lead role, the worker brief, checks, and handoffs, read [references/lead.md](references/lead.md) when you lead workers.

## Steps

1. Find the workspace and its tracker. Start from the current folder or the named workspace. `<workspace folder>` is `~/foxrun/<workspace>` on a standard install. Set `<tracker>` to `workspace_settings.<workspace>.database` in `~/.foxrun/config/person.json`. If it is absent, use `~/.foxrun/data.db`.
   Done when: `<tracker>` exists. If it is absent or unclear, stop and say so.
2. Read the program before you write:

   ```bash
   python3 ~/.foxrun/work/program.py --db <tracker> --receipt-root <workspace folder> show
   python3 ~/.foxrun/work/program.py --db <tracker> --receipt-root <workspace folder> next
   python3 ~/.foxrun/work/program.py --db <tracker> --receipt-root <workspace folder> pick-up <work stream>
   ```

   Add `--json` for agent-readable output.
   Done when: you know the stream, its open tasks, and its open runs.
3. Check for a duplicate before any create. Search titles for every object type you might make:

   ```bash
   sqlite3 -readonly <tracker> "select id,title,status from tasks where title like '%<words>%'"
   sqlite3 -readonly <tracker> "select id,title from projects where title like '%<words>%'"
   sqlite3 -readonly <tracker> "select id,title from bugs where title like '%<words>%'"
   ```

   Done when: you use the matching row, or you can say no row matches.
4. Claim the task, then start one run on it with your agent name, the exact model id, the runtime, and the native session id:

   ```bash
   python3 ~/.foxrun/work/work.py --workspace <workspace> --db <tracker> --receipt-root <workspace folder> --by <agent> claim <task id>
   python3 ~/.foxrun/work/work.py --workspace <workspace> --db <tracker> --receipt-root <workspace folder> --by <agent> --model <model id> --runtime <runtime> --session <session id> run-start <task id>
   ```

   Done when: the command prints `ok` and a run id.
5. Do the work. Write a step note at each milestone with `run-note <run id> "<step>"`. Write evidence inside `<workspace folder>/history/outputs/`.
   Done when: the evidence file exists.
6. End the run every time, early stops and failures too. The result is one word, `pass` or `fail`. Detail goes in the evidence file.

   ```bash
   python3 ~/.foxrun/work/work.py --workspace <workspace> --db <tracker> --receipt-root <workspace folder> --result pass --evidence history/outputs/<file> --fix-rounds <n> run-end <run id>
   ```

   Done when: the run has a result and an evidence path.
7. Submit and close on evidence. `done` sets the task to `in-review`. `accept` closes it. A signer other than the finisher, owner, or claimant runs `accept` after the check passes.

   ```bash
   python3 ~/.foxrun/work/work.py --workspace <workspace> --db <tracker> --receipt-root <workspace folder> --by <agent> --receipt history/outputs/<file> --proof "<one-line result>" done <task id>
   python3 ~/.foxrun/work/work.py --workspace <workspace> --db <tracker> --receipt-root <workspace folder> --by <signer> accept <task id>
   ```

   Done when: `show` lists the task as `in-review` or `done`.
8. End the reply with exactly one line: `Recorded: <task id> · <run id> · <result>` or `Not recorded: <reason>`.
   Done when: the line is the last line.

## Every run rolls up

- Every run belongs to a task. The task rolls up through a work stream, a program, and a goal. The run also ties to its function.
- One task holds every run of one piece of work. Recurring work is one standing task tagged `recurring`. Never make a task per day.
- Find the task in this order: the task in the brief, the session's open claims, the stream's open tasks.
- If nothing fits, the lead plans one task per distinct job at session wrap. If no stream fits either, say so and say where you think it belongs. The person decides. Never make a stream on your own.
- Show the person one placement line and wait for the yes before you make a top-level task.
- Never make a task per receipt, read, reply, order, or other outcome. Record each outcome as a change row on the record it changed.
- Steps of one job are checklist items: `create --parent <task id>`. They need no yes.
- Title each task with what it checks, fixes, or makes, and for what.

## Create a task

Create a top-level task only after the placement yes.

```bash
python3 ~/.foxrun/work/work.py --workspace <workspace> --db <tracker> --receipt-root <workspace folder> --by <agent> create \
  --title "<what it checks, fixes, or makes, and for what>" --project <work stream> --status todo \
  --problem "<the problem>" --job-when "<when ...>" --job-want "<I want ...>" --job-so "<so I can ...>" \
  --body "<the work>" --acceptance "<the check that proves it>" --context "<what to read>" --where "<workspace folder>"
```

`--status` defaults to `todo`. Use `backlog` for work that is not next. Omit `--ord` to put the task last in its stream.
`task-update` changes the title, note, acceptance, or tags. It refuses `--status`, `--project`, `--program`, `--theme`, and `--function`.
Tags are lowercase comma lists with no spaces or duplicates.

## Defects

Open a bug for a tool or system defect. Open an incident when the defect has a start time. Run `bug-open -h`, `incident-open -h`, and `link -h` for their fields.
`bug-close` needs a bug-to-task `fix` link. Use `--status wont-fix --note "<reason>"` when no fix applies. Every incident close needs `--rca-cause`.

## What the person says

- Write the person's direct direction on the task with `comment`. Start the text with the person's name and a colon.
- A yes to one exact thing is an `approval-add` row. A ruling is a `decision-add` row. A correction to how agents work is a `lesson-add` row, the same turn:

  ```bash
  python3 ~/.foxrun/work/work.py --workspace <workspace> --db <tracker> --receipt-root <workspace folder> --by <agent> lesson-add --rule "<one line>" --source "<task, comment:<id>, session, handoff, or file>" --person-words "<exact words>"
  ```

- Read open lessons from the `active_lessons` view.
- At each milestone, check the counts: `python3 ~/.foxrun/memory/handoff_check.py --db <tracker> --session <session id> --rate`.

## Session ids

- Claude: `$CLAUDE_CODE_SESSION_ID`.
- Codex: the thread id from `/status`, or the first `thread.started` JSON event.
- Hermes: the id supplied by `--pass-session-id`.
- No exposed id: use `runtime-session-search find` with the task title, runtime, folder, and time. Write `unknown` when no unique id exists, and say so in the evidence.

## Gotchas

- Say a fact was recorded only after the command prints `ok`.
- Use `--takeover "<reason>"` on `claim` only when another session left a stuck claim.
- When you hand work to another agent, record its run on the same task, or make it follow this skill. When you only consult one, write a comment: `Consulted <agent> (<model>): <question> -> <answer>`.
- Write your own agent name in `--by` and the exact resolved model id in `--model`. Never write the runtime name as the agent.
- A lead makes structure with `program-create`, `theme-create`, and `stream-create`. Run each with `-h`.
- To see what changed since a time, read `programs`, `projects`, `tasks`, `runs`, `bugs`, and `comments` with `sqlite3 -readonly` and a `created_on`, `started_at`, or `at` filter. Read `projects` as work streams.
