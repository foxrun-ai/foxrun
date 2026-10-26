# Workspace capability previews

`render_capabilities.py` reads this repository's identity loader, teams,
workflows, skills, and execution policy. It also reads the module repository's
capability template and command sources, plus the vault's ruled decision export.
It does not execute capabilities, read credentials, or change operational records.

Run with Python 3 and PyYAML:

```sh
python3 tools/render_capabilities.py \
  --repo /path/to/agent-team \
  --vault /path/to/portfolio \
  --workspace /path/to/portfolio/example-work \
  --skill-shelf /path/to/skills \
  --output /private/preview/example-work/CAPABILITIES.md
```

Add `--check` to compare the page and its manifest against current sources.
Exit codes: 0 unchanged/success; 1 drift; 2 invalid input or unsafe output.
The manifest stores source hashes, generation time, and the output hash.
Regeneration requires a matching generated page and manifest. Authored files,
incomplete pairs, symlinks, and hard-linked outputs are refused.
Each file is replaced atomically. A crash between the two replacements can
leave a mismatched pair; the next write refuses it for review.

Only exact team workspace bindings assign roles. Workflow rows are candidates
whose step agents all belong to that team; that does not prove installation.
Unbound workspaces omit unrelated role, workflow, skill, and MCP rows.
Module CLIs are a shared source inventory, with workspace installation unknown.
Python entry points require an AST-confirmed `__main__` guard.

These are labeled previews, not accepted workspace contracts. Functions,
reports, schedules, hooks, plugins, and runtime activation still need verified
source mappings. Skill availability means `SKILL.md` exists; its body is not read.
This command neither fills those gaps nor supplies an installation schedule.

Run the synthetic regression suite with:

```sh
python3 tests/test_render_capabilities.py
```
