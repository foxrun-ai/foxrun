---
type: note
workspace: system
timestamp: 2026-10-26T14:10:00-04:00
name: program
description: "Create or show a program and its themes in the tracker as a plan, with a duplicate-name check before every create. Programs hold themes, and themes hold work streams. Use for /program create, /program show, /program next, /program theme, or when someone asks for the plan."
kind: knowledge
argument-hint: "create | show | next | theme <program id or name words>"
---

# program

One skill for the program object. A program holds themes, and a theme holds work streams.
Read the plan with `program.py`. Write with `work.py`.
Only a lead creates a program or a theme, and only on the person's yes, because it reshapes the whole plan.

## Find the tracker

Set `<ws>` to the workspace that owns the work. Do not route by the current folder alone.
Set `<tracker>` to `workspace_settings.<ws>.database` in `~/.foxrun/config/person.json`. If it is absent, use `~/.foxrun/data.db`.
In the commands below, `<work>` stands for this exact prefix:

```bash
python3 ~/.foxrun/work/work.py --workspace <ws> --db <tracker> --receipt-root ~/foxrun/<ws> --by <you>
```

Write `<you>` as your own agent name, never the runtime name.

## Steps

1. **Check for a duplicate first.** Before any `create`, run:
   `sqlite3 -readonly <tracker> "SELECT id,name,status FROM programs WHERE name LIKE '%<words>%' ORDER BY id"`.
   Done when you named the match, or said there is none.
2. **Run the operation.** Done when the command prints `ok`, or the plan prints.

   | Operation | Command |
   |---|---|
   | show | `python3 ~/.foxrun/work/program.py --db <tracker> --receipt-root ~/foxrun/<ws> show` |
   | next | `python3 ~/.foxrun/work/program.py --db <tracker> --receipt-root ~/foxrun/<ws> next` |
   | create | `<work> program-create --name "<name>" --objective "<one line>"` |
   | theme | `<work> theme-create --program <program id> --name "<name>" --tagline "<one line>"` |

   Add `--json` to `program.py` for output an agent reads.
3. **Read it back.** Run `sqlite3 -readonly <tracker> "SELECT id,name,objective,status FROM programs WHERE id='<program id>'"`. Done when the row shows the name you wrote.

## Gotchas

- `program-create` prints the new `PG` id. Use that id for the theme.
- To make a work stream under a theme, use the `stream` skill.
