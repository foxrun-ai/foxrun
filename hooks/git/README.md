---
type: doc
workspace: system
timestamp: 2026-10-20T17:17:53-04:00
---
# Git hooks

These shared hooks run the secret check and chain the original Git hooks.
Set a repo local `core.hooksPath` to this folder only after backing up its hooks and Git settings.
An existing custom `core.hooksPath` needs its own preserved dispatch path.
The installer ships these files but does not change repo settings.

| File | Purpose |
|---|---|
| `README.md` | Explains shared hook setup and preservation. |
| `post-commit` | Runs the original post-commit hook with the same arguments and exit status. |
| `post-merge` | Runs the original post-merge hook with the same arguments and exit status. |
| `pre-commit` | Runs the original pre-commit hook, then checks its final staged changes. |
