---
name: skillify
description: "Turn text, a session, or a Hermes skill into a Dojo skill that passes the skill law, and check any skill against that law. Use when someone says make this a skill, skillify this, turn this session into a skill, promote a Hermes skill, or check a skill."
kind: tool
---

# Skillify

Author in `~/.foxrun/skillwright/skills/<name>/`. The repository root is `~/.foxrun/skillwright/`. The shared shelf is `~/.foxrun/skills/`.
Three doors have one ending: a checked Dojo skill that ships to Claude, Codex, and Hermes.
Names, kinds, replay cases, and writing rules come from `~/.foxrun/skillwright/standards/skill-law.md`. Read it before a new or changed skill.

## Commands

- `bin/skillify new <name> --description "..." [--kind knowledge|tool|driving] [--from-text FILE] [--with-bin] [--with-tests]`
- `bin/skillify from-session --runtime claude|codex|hermes --id <native-session-id> --name <name>`
- `bin/skillify promote <hermes-skill-name>`
- `bin/skillify check <name> [--replay-agent claude]`

Run each with `-h` for its flags.

## Steps

1. Pick the door. `new` scaffolds by kind and refuses an existing name. `from-session` keeps the successful tool calls and results, in order, with no model reasoning. `promote` copies a Hermes-managed skill into the Dojo and leaves the Hermes copy in place.
   Done when: the skill folder exists with `SKILL.md` and `replays/`.
2. Write the skill. Replace the example replay case with one to three real scenarios.
   Done when: each step has a done check, and `## Gotchas` exists.
3. Check it: `bin/skillify check <name>`. It checks frontmatter and names, catalog scope (read only), tests, the ship dry run, and the law checks: trigger opener, catalog budget, body size, dead links, Gotchas, script rules, and replay cases. Add `--replay-agent claude` to run the `read` cases in a fresh Claude session with no tools.
   Done when: `check` prints no refusal.
4. Ship it with the `skill-ship` skill: branch, PR, a second agent reads it, merge, pull with `git pull --ff-only`. The post-merge hook starts the ship.
   Done when: the ship receipt exists.

## Catalog routing

- The system `~/.foxrun/config/catalog.yaml` is the one catalog. No `where` line means global. `off` turns a skill off. A workspace list narrows the route.
- Draft sources stay in skillwright. `check` validates the scope and adds no publish entry.
- Preview routes: `tools/skill_ship.py route --candidate <frozen-release> --portfolio ~/foxrun --global-root ~/.agents/skills --global-root ~/.claude/skills --global-root ~/.codex/skills --dry-run`.
- Inspect both hooks: `tools/skill_ship.py install-trigger --check`.
- Change scope only with `python3 -B ~/.foxrun/base/catalog.py apply --input <reviewed-json> --expected-sha256 <current-sha256> --by <actor>`. Never edit the catalog by hand.

## Gotchas

- `check` warns about a changed skill whose name breaks the law. It does not rename. `--name-override "<reason>"` records why a name breaks the rule.
- A failed replay case refuses any skill. A new or changed skill with no replay case is refused.
- Hermes sees a new or changed skill only after a gateway restart. A restart needs the person's yes.
- Money, sends, deletes, contract files, and gateway restarts keep their own gates. A merge does not open them.
