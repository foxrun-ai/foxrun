---
name: skill-ship
description: "Ship a checked skill from the skillwright main branch to the shared shelf, with no release id to type, then prove it in a fresh session. Use when a skill change is merged, when the post-merge hook did not ship, or when a ship needs a rollback."
kind: knowledge
---

# Skill Ship

Source: `~/.foxrun/skillwright/skills/<name>/`. Shelf: `~/.foxrun/skills/<name>/`.
The tool is `~/.foxrun/skillwright/tools/skill_ship.py`. Run `skill_ship.py ship -h` for its flags.
Git rules come from `~/.foxrun/config/git.md`, then `~/.foxrun/config/git.local.md`.

## Steps

1. Work on a branch in the normal `~/.foxrun/skillwright` clone. Never make a worktree. Run `skillify check <name>` and the skill's tests.
   Done when: the check and the tests pass.
2. Open a PR. A second agent, not its author, reads the change. The lead merges it when its tests pass. A change that touches money, sends, deletes, a gateway restart, or a contract file keeps its own gate.
   Done when: the PR is merged to `main`.
3. Check the upstream: `git -C ~/.foxrun/skillwright rev-parse '@{u}'`. Then `git pull --ff-only` on `main`.
   Done when: `main` equals `@{u}`.
4. The post-merge hook ships each skill a commit on `main` touches. Watch `~/.foxrun/skillwright/skill-state/ships/trigger.log` with a tracked background task. If the hook did not start a ship, run `~/.foxrun/skillwright/tools/skill_ship.py ship --skill <name>` from `main`.
   Done when: one ship receipt exists in `~/.foxrun/skillwright/skill-state/ships/` for this release.
5. Prove delivery. In a fresh session, ask one real question that needs the changed skill. Presence on the shelf is not proof.
   Done when: the fresh session answers from the new skill text.

## Rollback

- A failed ship rolls back by itself before it returns.
- To roll back by hand, read `previous_release_id` in `~/.foxrun/skillwright/skill-state/ships/<release-id>.json`. Never infer it from the trigger log.

## Gotchas

- `ship --skill <name>` ships one skill and keeps every other shelf skill as it is.
- A second ship with the same bytes makes no release. The pin and the shipped list name the same release.
- Never ship from the shelf copy or an old source. The source is the skillwright clone on `main`.
- Hermes sees a new or changed skill only after a gateway restart. A restart needs the person's yes.
