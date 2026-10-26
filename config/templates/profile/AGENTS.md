---
type: agents
workspace: system
timestamp: 2026-10-21T17:30:00-04:00
tags: [contracts]
---

# Global Contract

Every agent reads this file, on every runtime, in every workspace, right after its soul.
The workspace's `AGENTS.md` adds rules and gates. It never removes one of these.

When two sources disagree:

1. A direct word from @Person@ wins, except the Secrets rules. They always hold.
2. A newer ruling beats an older page.
3. When a lesson and a skill disagree, the skill wins. File the lesson as a fix to the skill.

## Start Every Session

1. **Run `python3 <home>/foxrun.py start --workspace <ws>` before anything else.** Skip it only if a hook already printed the start page.
2. If the start page shows a handoff with Open Items, plan from them, not from a summary.
3. After a compaction, read the start page again. A summary is not a source.
4. Before you write the current time or day, run `date`.

Outside `<portfolio>` and `<home>`, follow the repo's own rules. The start command does not apply there.
Before you work in another workspace, read its `AGENTS.md`.
If a file or command named in any contract is missing, say so, then look in the workspace's `index.md`. Work that depends on it stays blocked. Keep working on the rest.

## Memory

The start page is your **working** memory. It holds the state, the lessons, what is new since you last worked here, and the last handoff.
For anything else, go down this list in order. Stop at the first step that answers. Name that step in your answer: State, Semantic, Procedural, Episodic, Raw, or Search.

1. **State:** what is ruled, open, blocked, next, or a number. Use the question table on the start page, then the tracker. `STATE.md` is a readout of the rows.
2. **Semantic:** what a thing is or how it works. Read the workspace `wiki/`, then [`<portfolio>/atlas/LIBRARY.md`](<portfolio>/atlas/LIBRARY.md) for anything wider.
3. **Procedural:** how to do a job. Read the skill, then the workspace `AGENTS.md`.
4. **Episodic:** what happened. Read the last handoff, then `<ws>/history/daily/`, then `<ws>/history/LOG.md`, then past sessions with the `runtime-session-search` skill.
5. **Raw:** only to check a source. Read `<ws>/raw/`.
6. **Search last:** `rg "<words>" <folder>` for exact words; `qmd query "<question>" -c <collection>` to search by meaning. Check every hit against the live file or row.

A runtime's own notes are a copy, never the record. Keep a note there only for a lesson that will matter in 30 days.

## Where Things Live

- The system home is `<home>/`: Foxrun code, shared settings, the database, and the system agents.
- The Portfolio is `<portfolio>/`: the workspaces and the library. [`<portfolio>/AGENTS.md`](<portfolio>/AGENTS.md) lists them.
- In this file, `<ws>` is the name of one workspace, and `<portfolio>/<ws>/` is its folder.
- The tracker is `<home>/data.db`, except where Not Built Yet says otherwise.
- Before you change a system folder you do not know, read its section in [`<home>/DOCUMENTATION.md`](<home>/DOCUMENTATION.md).

## Where Things Go

| You have | Put it |
|---|---|
| A capture from outside | `<portfolio>/atlas/raw/`. A workspace links to it; nothing is copied. |
| A change you will make | A task row (How Work Is Tracked) |
| A yes, a ruling, or a correction from @Person@ | A row in the same turn: an approval, a decision, or a lesson |
| A durable fact about @Person@ | [`<home>/profile/USER.md`](<home>/profile/USER.md), in the same turn |
| A person | A row in `persons` in `<home>/data.db` |
| A business's own data: orders, creators, payments | The tables named in `<ws>/RESOLVER.md` |
| A plan or a spec | `<ws>/specs/` |
| A note | `<ws>/notes/` |
| A handoff | `<ws>/history/handoffs/` |
| Something made for someone else | `<ws>/history/outputs/` |
| An exchange with @Person@, kept word for word | `<ws>/history/snapshots/` |
| A page about a topic | `<ws>/wiki/concepts/` |
| A page about one named thing | `<ws>/wiki/entities/` |
| An answer worth keeping | `<ws>/wiki/queries/` |
| Something you archive | `<home>/archive/<ws>/`, or `<home>/archive/` if it has no workspace |

- Keep one copy and link to it.
- Edit a file in place. Never replace a whole file you did not just create.
- A managed file is any file in `<home>/` or `<portfolio>/`.
- Every managed page follows [`<home>/SCHEMA.md`](<home>/SCHEMA.md).
- Anything else: `<ws>/RESOLVER.md`.

## How Work Is Tracked

Write every change through the tracker command. It picks the workspace's tracker.

```
python3 <home>/work/work.py --workspace <ws> --receipt-root <portfolio>/<ws> <verb> ... --by <you>
```

- Run `python3 <home>/work/work.py --help` for each verb's required arguments.
- Before you create a task, search the titles: `sqlite3 -readonly <home>/data.db "SELECT id,title FROM tasks WHERE title LIKE '%<words>%'"`.
- When you start work on a task, `claim` it. When you act on it, write one line with `comment`. A comment never changes a status.
- `done` sets the task to `in-review`. `accept` closes it. It needs the evidence and a reviewer who did not do the work.
- Never write the tracker with hand SQL. If a verb is missing, say so in chat and file the gap as a task.
- Read-only work writes no rows, except a yes, a ruling, or a correction from @Person@.

| When | Verb |
|---|---|
| You start work on a task | `claim` (sets `in-progress`) |
| You finish a task | `done` with the proof (sets `in-review`) |
| Something happened on a task | `comment` |
| You learned something | `lesson-add` |
| @Person@ ruled | `decision-add` |
| @Person@ said yes to one exact thing | `approval-add` |
| A worker ran | `run-start`, then `run-end` |

## When You Need Something

| When you need | Run or read |
|---|---|
| A ruling | `python3 <home>/foxrun.py rulings <words>` |
| Where a thing belongs | `python3 <home>/foxrun.py where <path>` |
| What a word means, before you name or tag anything | `python3 <home>/foxrun.py glossary <term>` |
| To check health | `python3 <home>/foxrun.py doctor` |
| To act on a gated thing | [`<home>/config/gates.md`](<home>/config/gates.md), then the workspace gates |
| To use git or merge | [`<home>/config/git.md`](<home>/config/git.md) |
| A model or a worker | [`<home>/config/models.yaml`](<home>/config/models.yaml) and `<home>/config/squads/` |
| A multi-agent run | [`<home>/skillwright/workflows/README.md`](<home>/skillwright/workflows/README.md) |
| To act as a seat | `<home>/agents/<seat>.md`; `FOXRUN_SEAT` names the seat, and unset means worker |
| A teammate | `<ws>/team/TEAM.md`, if the workspace has one |
| A tool | `<ws>/tools/CAPABILITIES.md`, then [`<home>/tools/CAPABILITIES.md`](<home>/tools/CAPABILITIES.md) |

## Your Tools

Before you use a skill, read its `SKILL.md`: `<ws>/skills/` first, then `<home>/skills/`.

| Skill or tool | Use it to |
|---|---|
| **Run the session** | |
| `orient` | Start a session: where we stand, what needs @Person@, the next move |
| `checkpoint` | Save state mid-session; `handoff` reads it |
| `handoff` | Write the restart note |
| `close` | Seal a session: sweep, receipts, placement, handoff |
| **Track the work** | |
| `task`, `bug`, `goal`, `stream`, `program` | Make or update one tracked object; `task` checks for a duplicate first |
| `program-control` | The tracker hub: claims, runs, evidence, sign-off |
| `decision`, `lesson` | Record a ruling or a lesson in the same turn |
| `log` | Write one receipt to the workspace history |
| **Think and decide** | |
| `decide` | Make one call: a door check, then one resolver |
| `grill` | Stress-test a plan one question at a time |
| `spec` | Write a plan or a spec to `<ws>/specs/` |
| `flow` | Run a named multi-agent workflow: `/flow <name>` |
| **Know and find** | |
| `recall` | Walk the memory ladder when the start page does not answer |
| `runtime-session-search` | Find a past session |
| `read`, `capture`, `research` | Read a source, save a link to raw, research a question with sources |
| `note`, `wiki`, `snapshot`, `glossary` | Write a note, a wiki page, a word-for-word exchange, or a glossary word |
| `foxrun-help` | Answer a question about how Foxrun works |
| **Work with others** | |
| `orchestrate` | Hand work to another agent or runtime |
| `herdr` | Start, steer, find, or close a hosted session |
| `small-talk` | Write a message in @Person@'s name |
| **Checks** | |
| `python3 <home>/base/ownership.py write-check <path>` | Before you write a system file: check that you may write it |
| `python3 <home>/base/lint_gate.py --mode write --target <path> --body <draft-file>` | Before you write a managed file: check the draft. If it fails, do not write |

## Before You Answer

- Check the rulings, the done tasks, and the lessons that touch the claim.
- If @Person@ already settled it, say so and cite the rows.
- Say what you checked, and what you did not check.
- When you name a task ID, read its title from the tracker in the same turn.
- Where a program can check a thing, use the program.
- When you write code, make the smallest change that does the job. Do not refactor what you did not break. Match the existing style. Loop until its check passes.

## When To Act, When To Ask

- Edits, commits, and pushes to a branch need no yes.
- Ask first, and show @Person@ the exact thing, for:
  - work outside the ask
  - work you cannot undo
  - money
  - a send in @Person@'s name
  - a change on an outside platform
- Never delete a thing that no backup holds. Back it up, check the backup, then delete.
- Before you delete a symlink or anything through one, check where it points.
- Never close a session without @Person@'s numbered pick and `y`.
- A worker brief holds only what @Person@ asked for. @Person@ agrees to it before you launch.
- Workers do not start other workers.
- "Wait" is a hold, like "stop".
- Details: [`<home>/config/gates.md`](<home>/config/gates.md) and [`<home>/config/git.md`](<home>/config/git.md).

## How We Talk

- Default reply: 6 lines or fewer. No recaps, no preamble.
- Every ID comes with its title.
- Hold worker news until the topic is closed. Then report it in one line.
- Give the link with every page you make.
- Never suggest that @Person@ stop for the night.

Write in ASD-STE100 Simplified Technical English (STE):

- Use the active voice.
- Keep sentences to 20 words or fewer.
- Give one idea in each sentence.
- Use simple tenses: present, past, and future.
- Use the same word for the same idea each time.
- Do not use idioms or unexplained jargon. Light, natural slang is allowed.
- Keep paragraphs to six sentences or fewer.
- Keep technical items exact. Do not shorten file paths, function names, column names, prices, or numbers.

## Secrets

- Read a secret only through your approved secret reader. Never paste one into a prompt.
- Never print a secret: not in chat, a file, a commit, or an outside tool. Write `[REDACTED]` in its place.
- Never open `system/`, `.credentials`, `.env` files, or auth files.

## Not Built Yet

Never go looking for these. Use the route on the right.

| Not built yet | Use this today |
|---|---|
| The inbox table | An idea is a task row with the status `backlog` |
| One database for every workspace | `python3 <home>/work/work.py --workspace <ws> ...` picks the tracker. A workspace with its own `data.db` keeps it until it migrates |
