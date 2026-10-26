---
type: note
workspace: system
timestamp: 2026-10-26T14:25:00-04:00
name: spec
description: "Write a spec to the owning workspace's specs/ folder from what the session already settled, with no new interview. Problem first, testable success criteria, and the seams to test. Use for /spec, or when someone says spec this out, write the plan, or turn this thread into a spec."
kind: knowledge
argument-hint: "<name> [workspace] [task id]"
---

# spec

A spec turns a settled thread into a plan another session can build cold.
Write from what the session already knows. Do not interview the person again; if a question is still open, grill first.
A spec lives in `~/foxrun/<ws>/specs/` and names its task, so the work and the plan point at each other.

## Steps

1. **Find the home.** Set `<ws>` to the workspace that owns the work. Check that `~/foxrun/<ws>/AGENTS.md` exists, and read it. If the workspace does not exist, stop: do not guess a folder. Done when you read the workspace's `AGENTS.md`.
2. **Read the ground.** Read the code, pages, rulings, and rows the spec touches. Run `python3 ~/.foxrun/foxrun.py rulings <words>`. Use the glossary words. Done when each ruling that touches the work is named.
3. **Find the seams.** Name the places where a test can prove the work, highest first. Prefer one seam that exists. Show the seams to the person in a few lines. Done when the person agreed the seams, or you noted they were not asked.
4. **Draft.** Follow [references/template.md](references/template.md). Match depth to risk: a cleanup gets a short spec; a data move or a delete gets every section. Name the file `<task id>-<kebab-slug>.md` when a task exists. Done when every required section has content and each success criterion says how it is measured.
5. **Check, then write.** Run `python3 ~/.foxrun/base/lint_gate.py --mode write --target ~/foxrun/<ws>/specs/<name>.md --body <draft file>`. Done when the gate passed and the spec is at its path.
6. **Tie it to the task.** `python3 ~/.foxrun/work/work.py --workspace <ws> --db <tracker> --receipt-root ~/foxrun/<ws> --by <you> comment <task id> "spec: specs/<name>.md"`. Done when the comment prints `ok`, or you said no task exists yet.

## Gotchas

- No problem means no spec. Lead with what breaks and the evidence.
- Leave out file paths and code that will go stale, unless a prototype settled a shape that prose cannot hold.
- A spec is a plan, not a go. Building it needs its own task and, for a one-way door, the person's yes.
