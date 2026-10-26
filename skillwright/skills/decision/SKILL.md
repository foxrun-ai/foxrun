---
type: note
workspace: system
timestamp: 2026-10-26T14:10:00-04:00
name: decision
description: "Record a ruling as one decision row in the tracker, with the exact words of the person, after a duplicate check. Also replaces or updates an old ruling. Use for /decision add, /decision show, /decision replace, or when the person rules on something. To work out what to decide, use decide."
kind: knowledge
argument-hint: "add | show | replace | update <decision id or words>"
---

# decision

One skill for the decision object. A decision row records what the person ruled, in their own words.
This skill records a ruling. It does not make one. To work out what to decide, use the `decide` skill.
Record a ruling in the same turn the person gives it, so the next agent finds it.

## Find the tracker

Set `<ws>` to the workspace that owns the work. Do not route by the current folder alone.
Set `<tracker>` to `workspace_settings.<ws>.database` in `~/.foxrun/config/person.json`. If it is absent, use `~/.foxrun/data.db`.
In the commands below, `<work>` stands for this exact prefix:

```bash
python3 ~/.foxrun/work/work.py --workspace <ws> --db <tracker> --receipt-root ~/foxrun/<ws> --by <you>
```

Write `<you>` as your own agent name, never the runtime name.

## Steps

1. **Check for a duplicate first.** Run `python3 ~/.foxrun/foxrun.py rulings <words>`. Also run:
   `sqlite3 -readonly <tracker> "SELECT id,name,status FROM decisions WHERE name LIKE '%<words>%' OR statement LIKE '%<words>%'"`.
   If an old ruling covers it, the new row replaces it. Done when you named the match, or said there is none.
2. **Write the row.** Done when the command prints `ok`.

   | Operation | Command |
   |---|---|
   | add | `<work> decision-add --id g-<short-slug> --name "<short name>" --statement "<the rule in one or two sentences>" --person-words "<their exact words>" --source comment:<id> [--replaces <old id>]` |
   | update | `<work> decision-update <decision id> --status <status> --note "<reason>"` |
   | link a task | `<work> task-decision-link <task id> --decision <decision id> --step <number>` |
   | show | `sqlite3 -readonly <tracker> "SELECT id,name,statement,status,decided_on FROM decisions WHERE id='<decision id>'"` |

3. **Read it back.** Run the `show` query. Done when the row shows the statement and status you wrote.

## Gotchas

- `--person-words` holds the exact words. Do not tidy them.
- `decision-add` refuses a duplicate id, and a second decision that cites the same comment.
- A yes to one exact thing is an approval, not a ruling. Use `<work> approval-add <subject id> --call approve --person-words "<words>"`.
