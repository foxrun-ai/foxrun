---
type: doc
workspace: system
---
# foxrun-setup product source

This folder holds the source of the `foxrun-setup` skill. It was named `setup` before ruling g-setup-skill-is-foxrun-setup.

| File | Purpose |
|---|---|
| `README.md` | Lists the foxrun-setup source files and their purposes. |
| `SKILL.md` | Defines the steps to rerun setup, whole or one part. |
| `bin/setup` | Reads each setup part's state and the next question; changes two setup answers. |
| `replays/set-runtime-dry-run.json` | Checks that a changed answer shows from and to and writes nothing. |
| `replays/refuse-name-change.json` | Checks that setup refuses a name change. |
| `replays/hooks-missing-in-fresh-home.json` | Checks that a fresh runtime home reports its missing hooks. |
| `tests/__init__.py` | Marks the foxrun-setup test package. |
| `tests/test_setup.py` | Checks part order, open questions, hook detection, backup items, and set. |
