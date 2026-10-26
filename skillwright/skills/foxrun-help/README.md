---
type: doc
workspace: system
---
# foxrun-help product source

This folder holds the source of the `foxrun-help` skill. It was named `ask` before ruling g-ask-skill-is-foxrun-help.

| File | Purpose |
|---|---|
| `README.md` | Lists the foxrun-help source files and their purposes. |
| `SKILL.md` | Defines the steps to answer a Foxrun question from its own pages. |
| `references/skill-map.md` | Maps a situation to the Foxrun skill that fits, along the session path. |
| `bin/ask-sources` | Names the nearest AGENTS.md and DOCUMENTATION.md files and the lines that match. |
| `replays/nightly-from-system-docs.json` | Checks that a system question starts with the system DOCUMENTATION.md. |
| `replays/workspace-rule-from-agents.json` | Checks that a workspace question starts with the nearest AGENTS.md. |
| `tests/__init__.py` | Marks the foxrun-help test package. |
| `tests/test_ask_sources.py` | Checks source order, the nearest file, no duplicates, no pages, and no writes. |
