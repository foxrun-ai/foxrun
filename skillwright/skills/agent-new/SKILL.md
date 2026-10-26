---
name: agent-new
description: "Create or update an agent worker from any runtime: write its identity file, render its Claude and Codex capes, and list the team. Use when the person or a lead says new agent, new worker, new specialist, add a role, update an agent, or rebuild a cape."
kind: tool
---

# agent-new

One identity file per agent. The capes are thin loaders rendered from it, so you change the identity, never the cape.
The wrapper `bin/agent-new` runs the installed program `~/.foxrun/agents/tools/agent_new.py`. Run `bin/agent-new <command> -h` for each command's flags.

## Where things go

- A workspace agent: `~/foxrun/<workspace>/team/<id>.md`. Its capes sit in `<workspace>/.claude/agents/<id>.claude.md` and `<workspace>/.codex/agents/<id>.toml`; both folders link to `<workspace>/team`.
- A system agent: `--client system`. Its capes sit in `~/.foxrun/agents/generated/claude/<id>.md` and `~/.foxrun/agents/generated/codex/<id>.toml`.
- Render receipts: `<workspace>/history/outputs/agent-new/<id>/`, or `~/.foxrun/agents/generated/<id>/` for a system agent.
- An id has one owner across both homes. A duplicate id is refused.

## Steps

1. Check the id is free: `bin/agent-new list`. For an existing seat, run `python3 ~/.foxrun/foxrun.py start --seat <id>` and read the file on its `File:` line. `base.paths.resolve_seat` selects that file.
   Done when: the id is free (create), or you have read its current identity file (update).
2. Create: run with `--dry-run` first, then without it.

   ```
   bin/agent-new create <id> --role "<role>" --summary "<one line>" --tier work --skills a,b --tools qmd --client <workspace> --runtimes claude,codex --hermes-mode none --dry-run
   ```

   Update: edit the identity file, bump its `version`, and go to step 3.
   Done when: the identity file exists with the right role, tier, skills, and version.
3. Render the capes: `bin/agent-new render <id> --dry-run`, then `bin/agent-new render <id>`.
   Done when: each cape names the exact identity path and carries the `managed-by: agent-new` marker.
4. Report the identity path, each cape path, and the receipt folder.
   Done when: `bin/agent-new list` shows the id with its client.

## Gotchas

- An identity is not a Hermes profile. Only `--hermes-mode none` works today. Child and profile modes are held.
- `probe`, `diff`, and `apply` stop today. They need an approved agent-folder plan and live loader proof. No stopped command falls back to an old home.
- Skills are ids on the shared shelf. Report a missing skill as a gap. Never invent one.
- New skill names follow `~/.foxrun/skillwright/standards/skill-law.md`.
- A hand-written cape has no marker. `render` never overwrites it.
- Tiers resolve to models in `~/.foxrun/config/models.yaml`.
