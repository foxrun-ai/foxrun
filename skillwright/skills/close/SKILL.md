---
name: close
description: "Close a working session on Foxrun: sweep a named folder, land missing receipts, place the session's work on tasks, file each yes and ruling as a row, write the handoff, and rebuild the start page. Use when the person says close, wrap the session, seal this work, or prepare the next session."
kind: knowledge
---

# Close

Close seals one session so the next one starts from rows, not memory.
It runs blocks that each work alone: `log`, `program-control`, and `handoff`. Close only puts them in order.
Keep it lean. A close that turns into a cleanup project failed. Flag bigger work as a task and hand it off.

## Steps

1. Resolve the owning workspace and this session. Read the workspace `AGENTS.md`. The folder is `~/foxrun/<workspace>/` on a standard install. Read `workspace_settings.<workspace>.database` in `~/.foxrun/config/person.json`; if it is absent, the tracker is `~/.foxrun/data.db`.
   Done when: you can name the workspace, its tracker, and the session id. If either is unclear, ask one routing question and write nothing.
2. Sweep only a folder the person names. List each file and its home from the contract's `Where Things Go` table. Use `python3 ~/.foxrun/foxrun.py where <path>` when a home is unclear. Move nothing until the person says yes. Never delete.
   Done when: each named file has an approved home, or you wrote `no sweep target`.
3. Land one receipt for each material moment that has none: a decision, a direction change, shipped work, a source, or a blocker. Use the `log` skill.
   Done when: each moment has one receipt, and no receipt is a duplicate.
4. Place the session's work. List its runs and outcomes. Follow `program-control`, `Every run rolls up`: the brief's task, then open claims, then the stream's open tasks. If nothing fits, plan one task per distinct job. Show one line, such as `Today's work -> T86 under WS04, plus one new task under WS04: <title>`. Create nothing until the person says yes. After the yes, create the task and record each run on it.
   Done when: every run sits on a task, or waits on the placement line with zero tasks made before the yes.
5. File what the person said. Each yes is an `approval-add` row. Each ruling is a `decision-add` row. Each correction to how agents work is a `lesson-add` row. Check the counts with `python3 ~/.foxrun/memory/handoff_check.py --db <tracker> --session <session id> --rate`.
   Done when: every approval and ruling of this session has its row.
6. Write the handoff with the `handoff` skill. It points at rows by id and holds only what rows cannot.
   Done when: the handoff path exists and its coverage check passed.
7. Rebuild the start page: `python3 ~/.foxrun/memory/state.py build --workspace <workspace>`. Then run it again with `--check`.
   Done when: the check exits 0.
8. Report one short block: swept, receipts landed, work placed, rows filed, handoff path, start page rebuilt, and any blocker.
   Done when: each line says done, none, or blocked with its reason.

## Gotchas

- A block that waits for a yes or fails stops the sequence. Report what is done and what is left. Resume at that block after it clears.
- Do not make a receipt or an open item to fill a line. An empty result is a result.
- `snapshot` is not part of close. It runs only when the person blesses exact words.
- Close does not end the session or close a hosted pane. That needs the person's numbered pick and `y`.
- Follow `~/.foxrun/config/gates.md` at every block.
