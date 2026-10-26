---
type: note
workspace: system
timestamp: 2026-10-26T14:20:00-04:00
name: lesson
description: "Add, promote, or prune a lesson in the tracker. A lesson is one rule the agents learned from a correction or a solved problem. Use for /lesson add, /lesson promote, /lesson prune, or when the person corrects how agents work, or a hard problem is solved and worth keeping."
kind: knowledge
argument-hint: "add | promote | prune | show [lesson id or words]"
---

# lesson

One skill for the lesson object. A lesson is one rule, in one line, that every agent reads at start.
Lessons live in the tracker so the start page shows them. Read the open ones from the `active_lessons` view.
A lesson is a waypoint, not a home. When a skill, contract line, or check can enforce it, promote it there.
When a lesson and a skill disagree, the skill wins, and the lesson becomes a fix to that skill.

## Find the tracker

Set `<ws>` to the workspace that owns the work. Do not route by the current folder alone.
Set `<tracker>` to `workspace_settings.<ws>.database` in `~/.foxrun/config/person.json`. If it is absent, use `~/.foxrun/data.db`.
In the commands below, `<work>` stands for this exact prefix:

```bash
python3 ~/.foxrun/work/work.py --workspace <ws> --db <tracker> --receipt-root ~/foxrun/<ws> --by <you>
```

Write `<you>` as your own agent name, never the runtime name.

## Steps

1. **Add.** When the person corrects how agents work, add the lesson in the same turn. When a hard problem is solved, add the one rule that would have saved the time.
   `<work> lesson-add --rule "<one line>" --source "<task id, comment:<id>, session, handoff, or file>" [--person-words "<their exact words>"] [--lesson-workspace <ws>|all] [--applies-to <seat>|all]`.
   Done when the command prints `ok lesson-add <id>`. A line that ends in `duplicate` names the lesson that already holds the rule; use it.
2. **Promote.** Find the skill, contract line, or check that should enforce the rule. Change it through its own owner: a skill through `skillify`, a contract through the person's yes. Then retire the lesson and point at the new home:
   `<work> lesson-update <lesson id> --status replaced --source "<path of the line that now enforces it>"`.
   Done when the enforcing line exists and the lesson row shows `replaced`.
3. **Prune.** Read the open lessons:
   `sqlite3 -readonly <tracker> "SELECT id,text,workspace,applies_to,created_on FROM active_lessons ORDER BY created_on"`.
   For each one, keep it, merge it, or retire it. Merge two lessons with `lesson-add --rule "<merged line>" --replaces <old id>`. Retire a stale one with `lesson-update <id> --status replaced --source "<why>"`. Done when each lesson you read has one of the three calls, and you listed them.
4. **Read it back.** Run `sqlite3 -readonly <tracker> "SELECT id,text,status,source FROM lessons WHERE id='<lesson id>'"`. Done when the row shows what you wrote.

## Gotchas

- Keep the rule to one line. Detail goes in the source the lesson points to.
- `--person-words` holds the exact words. Do not tidy them.
- Pruning only retires rows. It never deletes one.
- A lesson that keeps coming back is a sign the skill is wrong. Promote it.
