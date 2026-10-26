---
type: note
workspace: system
timestamp: 2026-10-26T14:10:00-04:00
name: bug
description: "Open, show, update, link, or close a bug in the tracker, with a duplicate-title check before every open. A bug is a lasting tool or system defect. Use for /bug open, /bug show, /bug link, /bug close, or when someone says file a bug or this tool is broken."
kind: knowledge
argument-hint: "open | show | update | link | close <bug id or title words>"
---

# bug

One skill for the bug object. A bug is a lasting defect in a tool or a system.
A defect with a start time and an impact is also an incident: open it with `<work> incident-open` and link the bug.
A bug closes as `fixed` only through a task that fixes it, so the fix has an owner and evidence.

## Find the tracker

Set `<ws>` to the workspace that owns the work. Do not route by the current folder alone.
Set `<tracker>` to `workspace_settings.<ws>.database` in `~/.foxrun/config/person.json`. If it is absent, use `~/.foxrun/data.db`.
In the commands below, `<work>` stands for this exact prefix:

```bash
python3 ~/.foxrun/work/work.py --workspace <ws> --db <tracker> --receipt-root ~/foxrun/<ws> --by <you>
```

Write `<you>` as your own agent name, never the runtime name.

## Steps

1. **Check for a duplicate first.** Before any `open`, run:
   `sqlite3 -readonly <tracker> "SELECT id,title,status,capability FROM bugs WHERE title LIKE '%<words>%' OR capability LIKE '%<words>%' ORDER BY created_on"`.
   If an open bug fits, add to it with `bug-update` or a comment. Done when you named the match, or said there is none.
2. **Run the operation.** Done when the command prints `ok`.

   | Operation | Command |
   |---|---|
   | open | `<work> bug-open --id B-<yyyymmdd>-<short-slug> --title "<defect>" --capability "<capability>" --description "<what fails>" --problem ... --job-when ... --job-want ... --job-so ... --body "<what the fix changes>" --acceptance ... --context ... --where <path>` |
   | update | `<work> bug-update <bug id> --add-tag <tag> --context "<new evidence>"` |
   | link to a fix | `<work> link <bug id> --subject-type bug --target-type task --target-id <task id> --relation fix` |
   | close | `<work> bug-close <bug id> --status fixed --note "<task id> fixes it"` |
   | close, no fix | `<work> bug-close <bug id> --status wont-fix --note "<reason>"` |

3. **Read it back.** Run `sqlite3 -readonly <tracker> "SELECT id,title,status,capability FROM bugs WHERE id='<bug id>'"`. Done when the row shows the status you expect.

## Gotchas

- `bug-close --status fixed` refuses a bug with no `fix` link to a task. Link first.
- A bug is not a task. The task that fixes it holds the work and the runs.
- `link` also takes `--relation caused-by`, `found-in`, `updated`, and `about`. Run `<work> link -h`.
