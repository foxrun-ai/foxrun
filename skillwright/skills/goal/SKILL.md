---
type: note
workspace: system
timestamp: 2026-10-26T14:10:00-04:00
name: goal
description: "Create or show a goal row in the tracker and tie tasks to it, with a duplicate-title check before every create. Goals have a horizon: north-star, 3-year, 1-year, or quarter. Use for /goal create, /goal show, /goal link, or when someone asks what a goal is or which tasks serve it."
kind: knowledge
argument-hint: "create | show | link <goal id or title words>"
---

# goal

One skill for the goal object. A goal says what the work is for, over a horizon.
Tasks roll up to a goal, so the person can see which work serves which goal.

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
   `sqlite3 -readonly <tracker> "SELECT id,title,horizon,period,status FROM goals WHERE title LIKE '%<words>%' ORDER BY id"`.
   Done when you named the match, or said there is none.
2. **Get the yes.** A goal is the person's call. Show the title, horizon, and period, and wait for the yes. Done when the person said yes.
3. **Run the operation.** Done when the command prints `ok`.

   | Operation | Command |
   |---|---|
   | create | `<work> goal-create --title "<goal>" --horizon quarter --period 2026-Q4 [--owner <name>] [--tags ...]` |
   | link | `<work> task-goal <task id> --goal <goal id>` |
   | show | `sqlite3 -readonly <tracker> "SELECT id,title,horizon,period,owner,status FROM goals WHERE id='<goal id>'"` |

4. **Read it back.** Run the `show` query. Done when the row shows the title and horizon you wrote.

## Gotchas

- `--horizon` takes only `north-star`, `3-year`, `1-year`, or `quarter`.
- The owner is a person's plain name. Read it from the `persons` table; do not type a name from memory.
