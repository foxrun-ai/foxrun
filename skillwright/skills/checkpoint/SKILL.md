---
type: note
workspace: system
timestamp: 2026-10-26T14:25:00-04:00
name: checkpoint
description: "Save a light checkpoint mid-session as one task comment: where the work stands and the next move. Fast and frequent; handoff reads checkpoints when present. Use for /checkpoint, before a risky step, after a milestone, or when context is filling up."
kind: knowledge
argument-hint: "[task id]"
---

# checkpoint

A checkpoint is a small save in the middle of a session. It costs one command, so take one often.
It lives as a comment on the active task, in the tracker, so the next agent finds it with the task.
The `handoff` skill reads the latest checkpoints when it writes the restart note. Without checkpoints, handoff works as before.

## Find the tracker

Set `<ws>` to the workspace that owns the work. Do not route by the current folder alone.
Set `<tracker>` to `workspace_settings.<ws>.database` in `~/.foxrun/config/person.json`. If it is absent, use `~/.foxrun/data.db`.
In the commands below, `<work>` stands for this exact prefix:

```bash
python3 ~/.foxrun/work/work.py --workspace <ws> --db <tracker> --receipt-root ~/foxrun/<ws> --by <you>
```

Write `<you>` as your own agent name, never the runtime name.

## Steps

1. **Find the active task.** Use the task you claimed. If none: `sqlite3 -readonly <tracker> "SELECT id,title FROM tasks WHERE claimed_by='<you>' AND status NOT IN ('done','canceled')"`. Done when you have one task id, or you said there is no task and stopped.
2. **Write the checkpoint.** One comment, three parts, each short:
   `<work> comment <task id> "checkpoint: done <what finished>; open <what is open>; next <your next move>"`.
   If a run is open on the task, also run `<work> run-note <run id> "<step>"`. Done when the command prints `ok`.
3. **Read it back.** `sqlite3 -readonly <tracker> "SELECT id,at,body FROM comments WHERE subject_type='task' AND subject_id='<task id>' AND body LIKE 'checkpoint:%' ORDER BY id DESC LIMIT 1"`. Done when the newest row is the one you wrote.

## Gotchas

- A checkpoint is not a handoff. It holds no boot order and no state copy, only the three parts.
- Do not checkpoint every tool call. Take one at a milestone, before a risky step, or when context passes about half.
- A checkpoint never asks the person anything. If you need a yes, ask in chat.
