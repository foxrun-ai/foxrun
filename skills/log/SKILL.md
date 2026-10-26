---
type: note
workspace: <workspace>
timestamp: 2026-09-18T23:05:00-04:00
name: log
description: "Write one receipt to the owning workspace's history at a material moment: a decision, a direction change, shipped work, a material source, or a blocker. Use mid-session or at the end of a session when the person says log this, land the receipt, note that decision, or record what shipped."
argument-hint: [workspace | material moment | type]
---

# log

History only grows. One receipt per material moment, written once, never edited.

## Trigger phrases

`log this` · `land the receipt` · `note that decision` · `record what shipped`

## Run

1. Resolve the workspace that owns the changed work; never route by the current directory alone.
2. Confirm the moment is material: a decision, a direction change, a shipped result, a material source, or a blocker. Skip routine narration and duplicates.
3. Choose one type: `progress`, `decision`, `source`, `blocked`, or `done`.
4. Select `<workspace>`, its confirmed `<tracker>`, and the existing task that owns this moment.
   Read `workspace_settings.<workspace>.database` in `~/.foxrun/config/person.json`.
   If it is absent, use `~/.foxrun/data.db`. Pass the workspace and tracker to the installed command.
   Record one event with the installed command:

```bash
python3 ~/.foxrun/events/log.py add comment --workspace <workspace> --db <tracker> --receipt-root ~/foxrun/<workspace> --by <agent> <task id> "<type>: <title>; <body>; refs: <ids or paths>"
python3 ~/.foxrun/events/log.py show --db <tracker> --subject-type task --subject-id <task id>
```

5. Read back the new comment in the `show` output. Confirm its comment ID, workspace, and type in one line.
   Events live in the selected tracker. Keeper builds `<workspace>/history/LOG.md` from events.
   A missing task waits for placement through `program-control`; do not create a separate log file.

## Failure modes

- Owning workspace ambiguous: ask one routing question before writing.
- Tracker or task absent: stop and name the missing owner. Do not invent another history.
- Receipt already exists: report it and do not duplicate it.
- Uncertain command result: read back before any retry.

## Boundaries

- Follow `~/.foxrun/config/gates.md` before any gated action.
- Fires by hand, mid-session or at the end of a session. No schedule.
- No deletes, rewrites, cleanup, backfill, or edits to prior receipts, ever. Moving a workspace from `log.md` to `log.jsonl` is a separate, approved step done with `~/.foxrun/events/log_switch.py`.

`log_switch.py` stages legacy history for review. It does not write new event receipts or authorize promotion.
