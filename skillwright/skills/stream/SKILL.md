---
type: note
workspace: system
timestamp: 2026-10-26T14:10:00-04:00
name: stream
description: "Create, show, or rename a work stream in the tracker with a duplicate-title check before every create. A work stream is a projects row. Use for /stream create, /stream show, /stream rename, /stream order, or when someone asks what a work stream holds."
kind: knowledge
argument-hint: "create | show | rename | order <stream id or title words>"
---

# stream

One skill for the work stream object. A work stream is a row in the `projects` table, with an id such as `WS12`.
A stream sits under a program and a theme, and tasks sit under it.
Never create a stream on your own. Propose it, and create it only on the person's yes.

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
   `sqlite3 -readonly <tracker> "SELECT id,title,status,program FROM projects WHERE title LIKE '%<words>%' ORDER BY id"`.
   Done when you named the match, or said there is none.
2. **Get the yes.** Show one line: the title, the program, the theme, and the function. Done when the person said yes to that line.
3. **Run the operation.** Done when the command prints `ok`.

   | Operation | Command |
   |---|---|
   | create | `<work> stream-create --program <program id> --theme <theme id> --function <function id> --title "<title>" --status todo` |
   | rename | `<work> stream-update <stream id> --title "<title>" --note "<reason>"` |
   | order | `<work> stream-update <stream id> --ord <integer>` |
   | show | `python3 ~/.foxrun/work/program.py --db <tracker> --receipt-root ~/foxrun/<ws> pick-up <stream id>` |

4. **Read it back.** Run `sqlite3 -readonly <tracker> "SELECT id,title,status,program,theme FROM projects WHERE id='<stream id>'"`. Done when the row shows the values you wrote.

## Gotchas

- `stream-create --status` takes only `backlog` or `todo`.
- Find the program, theme, and function ids with `program.py --db <tracker> --receipt-root ~/foxrun/<ws> show` before you create.
- `stream-update` with no changed field prints `duplicate` and writes nothing.
