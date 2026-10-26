---
type: agents
workspace: system
timestamp: 2026-10-21T17:45:00-04:00
tags: [contracts]
---

# System Home Contract

Read this when you work inside the system home, the folder that holds this file. Links here are relative to it.
Every other rule is in the [global contract](profile/AGENTS.md).

## What This Folder Is

- This folder is the installed Foxrun system home: code, shared settings, the database, and the system agents.
- Each folder's job is in [`DOCUMENTATION.md`](DOCUMENTATION.md). Read its section before you change a folder you do not know.

## Who Owns What

- Each part has one writer. The table is in [`RESOLVER.md`](RESOLVER.md), section `Who Owns What`.
- Before you change a part, read its owner's seat file in `agents/`.

## Before You Write Here

Installed folders are copies of the product. An update replaces them, so never edit them by hand.
To fix an installed file, file a bug with the fix. The fix ships in the next update.

1. Run `python3 base/ownership.py --home . write-check <path>` from this folder. If it fails, stop.
2. For a managed file, run `python3 base/lint_gate.py --mode write --target <path> --body <draft-file>`. If it fails, do not write.
3. After the change, run `python3 foxrun.py doctor`. If it fails, fix it before you go on.

If a file named here is missing, say so and stop that write.

## Installed Code

- Before a git action, read [`config/git.md`](config/git.md), then `config/git.local.md`.
- Keep private data and run trails out of git.

## Where The Starter Contract Is

- A new person starts from [`config/templates/profile/AGENTS.md`](config/templates/profile/AGENTS.md). The installer copies it to `profile/AGENTS.md`.
- The person's own global contract is `profile/AGENTS.md`. Never overwrite it on an update.
