---
type: doc
workspace: system
timestamp: 2026-10-20T20:01:52-04:00
---
# Skillwright tools

| File | Purpose |
| --- | --- |
| `workflow_ship.py` | Checks, releases, and promotes standalone workflows through `skill_ship.py ship --workflow`. |
| `skill_ship.py` | Runs the shared release command for skills and workflows. |

A dry-run reads and checks the source. It changes no files.
A real workflow release checks backups, compares bytes, and writes hashes and a receipt.
The shelf record is `skillwright/workflows/.release-manifest.json`.
Prior bytes and receipts stay in `skillwright/skill-state/workflow-releases/<release-id>/`.
