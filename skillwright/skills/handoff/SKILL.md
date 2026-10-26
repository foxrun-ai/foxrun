---
type: note
workspace: foxrun-dev
timestamp: 2026-09-18T22:45:00-04:00
name: handoff
description: "Write the restart baton for the next session: a thin, frozen note that points at live state in the database and holds only what rows cannot. Use on demand, at the end of a session, or when the runtime reports roughly 90% context usage."
argument-hint: [workspace | session | next objective]
---

# handoff

A handoff is a frozen note from one moment.
Boot Order step 0 loads live rules, lessons, and state. Step 1 rechecks status and approvals before any action.
Prose holds only what rows cannot and points at rows by id.
Task sign-off needs a passing check, attached evidence, and a signer other than the finisher, owner, or claimant.
No lead seat is required. A handoff alone does not close a task.

## Trigger phrases

`write the handoff` · `hand off` · `give me a reboot prompt` · `continue in a new chat` · `context is at 90%`

## Run

1. Resolve the owning workspace and its database (`<workspace>/data.db`; for foxrun-dev work, `~/.foxrun/data.db`). If no database is reachable, say so in the note and use the JSONL export.
2. For a lead, look for today's handoff with the same `session` in the workspace's `history/handoffs/`. Write one current handoff per lead per day. If this session wrote one today, put `supersedes: <older path>` in the new note's frontmatter; the newest is current. Do not edit the older note.
3. Run `handoff/bin/handoff-path <workspace folder> <kebab-subject>`. It reserves the date and number in `.YYYY-MM-DD-NNN.reserved`, then exclusively creates and prints `<workspace folder>/history/handoffs/YYYY-MM-DD-NNN-<subject>.md`. Write into that empty file. Never choose a number by scanning or overwrite a file.
4. At the moment you write frontmatter, run `handoff/bin/handoff-path --timestamp` and copy its output into `timestamp`. It reads the clock then, equivalent to `date +%Y-%m-%dT%H:%M:%S%z` with a colon inserted in the UTC offset. Never type or estimate the time. Frontmatter: `type: handoff`, `workspace`, `timestamp`, `session`, `agent`, optional `seat` (such as `seat: chief-of-staff`), and `supersedes` when step 2 applies. No status field.
5. Write only the seven sections below, in order. Fill every required section; omit Snapshot when it is not needed. In Codex, put the reboot prompt inside Boot Order.
6. For a lead, run `python3 ~/.foxrun/memory/handoff_check.py --db <owning tracker> --session <session id> --handoff <path> --kind lead --out <path>.coverage.md` before close. Fix each real gap in the new handoff with one line under the right section, or mark it `not mine` with its id or path. Rerun the check after fixes. Report its `coverage ids=... files=... gaps=...` line with the coverage path. Workers and one-shots skip this step.
7. Land one log receipt in the owning workspace (log).
8. Verify the note exists, then report its path and its first boot query. For a lead, include the coverage line and path.

## The seven sections

### Boot Order
Live queries, not remembered facts. Always in this order:
0. **Boot Foxrun.** Run `python3 ~/.foxrun/foxrun.py start --workspace <ws> --seat <seat>` with this handoff's workspace and seat. Read its rules, lessons, and state before any other step.
1. **Recheck first.** Task status and approvals may have changed since this note was written. An old boot order can restart canceled work. Run the status and approvals queries before acting on anything below.
2. The views to run, as exact commands: needs me, open tasks for the named project, the latest decisions. Example: `sqlite3 -readonly <db> "select * from needs_me"`.
3. The contracts to read, by path, in load order.
4. The one next action, as a task id. If there is no task row for it, create the row first; never put a next action only in prose.
5. Add one ready-to-paste boot prompt here, in every runtime. It runs the start command with `--seat <the seat that wrote this handoff>` (leave `--seat` out for a worker with no seat), reads this handoff whole, runs Boot Order before the first reply, builds the first plan from Open Items line by line, then continues the first item quietly. Do not add another section.

### State
Only what rows cannot hold. Point to the live task, decision, approval, or log row by id. Do not restate a status, count, or decision text as current.

### Open Items
Unresolved items only, by task or blocker id. Point to the row for live status and ownership.

### Context
Hand-written why, traps, open judgment calls, what annoyed the person, and what worked. Point at rows by id, such as a task id or a decision id.

### Lessons
One line per lesson: the lesson, its source task id, and the file or skill where it should live. Use `none` if there is no lesson.

### Snapshot
Optional fallback. Render it from the same views at write time and stamp it `as of <ISO time>`. It serves an agent without database access. When the database is reachable, Boot Order's live queries win. Do not edit it after the handoff is finished.

### Without The Database
For a cloud agent or another machine: the path to the JSONL export, its version, and its export time. If the export time is unknown, label it historical. Say how to submit changes back (proposal lines), never direct writes.

## Failure modes

- Workspace or session ambiguous: ask one routing question before writing.
- A fact cannot be verified against a row or a file: mark the exact uncertainty in Context; never turn chat memory into fact.
- Number collision: `handoff-path` retries the next number through exclusive creation. Never rescan and write a name by hand.
- Write fails: report the failure and give the Boot Order in chat without claiming a handoff exists.

## Boundaries

- Follow `~/.foxrun/config/gates.md` before any gated action.
- On demand or at reported context pressure; no scheduled trigger.
- Before a compaction, `bin/handoff-precompact` writes this same shape from rows and the settlement check, and lists any @Person@ settlement with no row under `## Unpromoted`. Read `references/precompact-hook.md` when you register, check, or remove that hook; it is not registered until @Person@ approves.
- Boot reads in a fixed order: `bin/handoff-boot` prints the newest hand-written handoff for the seat and session, then every newer pre-compaction note, oldest first. Never boot from a thin pre-compaction note alone when a hand-written handoff exists.
- No deletes, no source-state changes, no edits to previous handoffs.
