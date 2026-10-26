---
type: note
workspace: system
timestamp: 2026-10-26T14:10:00-04:00
name: task
description: "Create, show, claim, finish, or move a task in a tracker with a duplicate-title check before every create. Use for /task create, /task show, /task claim, /task done, /task move, /task backlog, or when someone says add a task, close the task, or what is T123."
kind: knowledge
argument-hint: "create | show | claim | comment | done | accept | move | backlog | todo | block | cancel <task id or title words>"
---

# task

One skill for the task object. The operation is the argument: `/task create`, `/task done T12`.
This skill is a thin door onto `work.py`. The hub for runs, claims, and close-out rules is `program-control`.
Every write goes through `work.py`, never hand SQL, so each change leaves an activity row.

## Find the tracker

Set `<ws>` to the workspace that owns the work. Do not route by the current folder alone.
Set `<tracker>` to `workspace_settings.<ws>.database` in `~/.foxrun/config/person.json`. If it is absent, use `~/.foxrun/data.db`.
In the commands below, `<work>` stands for this exact prefix:

```bash
python3 ~/.foxrun/work/work.py --workspace <ws> --db <tracker> --receipt-root ~/foxrun/<ws> --by <you>
```

Write `<you>` as your own agent name, never the runtime name.

## Steps

1. **Check for a duplicate first.** Before any `create`, search the titles with two or three key words:
   `sqlite3 -readonly <tracker> "SELECT id,title,status,project FROM tasks WHERE title LIKE '%<words>%' ORDER BY id"`.
   If a row fits, use it and stop here. Done when the search ran and you named the match, or said there is none.
2. **Place it.** A new top-level task needs the person's yes on one placement line: the title and the work stream. A checklist item under a task (`--parent <task id>`) needs no yes. Done when you have the yes, or the row is a checklist item.
3. **Run the operation.** Use one command from the table. Run `<work> <verb> --help` for every option. Done when the command prints `ok`.

   | Operation | Command |
   |---|---|
   | create | `<work> create --title "<what it checks, fixes, or makes>" --project <stream id> --status todo --problem ... --job-when ... --job-want ... --job-so ... --body ... --acceptance ... --context ... --where <path>` |
   | show | `<work> show <task id>` |
   | claim | `<work> claim <task id>` |
   | comment | `<work> comment <task id> "<one line>"` |
   | done | `<work> --receipt history/outputs/<evidence file> --proof "<one-line result>" done <task id>` (sets `in-review`; the receipt path is relative to `--receipt-root`) |
   | accept | `<work> accept <task id>` (a signer who did not do the work) |
   | move | `<work> task-move <task id> --project <stream id> --note "<reason>"` |
   | backlog, todo | `<work> backlog <task id> --note "<reason>"` or `todo` |
   | block | `<work> block <task id> "<reason>"` |
   | cancel | `<work> cancel <task id> --reason "<reason>"` |
   | edit | `<work> task-update <task id> --title ... --note ... --add-tag ...` |

4. **Read it back.** Run `<work> show <task id>`. Done when the printed row has the id, title, and status you expect. Say a fact was recorded only after this read.

## Gotchas

- `done` does not close a task. It sets `in-review`. `accept` closes it, and the signer must not be the one who did the work.
- `task-update` refuses `--status` and `--project`. Use the status verbs and `task-move`.
- One task holds every run of one piece of work. Never make a task per reply, read, or receipt.
- `create` prints the new id. Use that id; do not guess the next number.
