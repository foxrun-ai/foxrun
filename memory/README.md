---
type: doc
name: wiki
workspace: foxrun-dev
tier: base
built_by: kit
version: 0.1.0
requires: []
timestamp: 2026-09-18T17:56:39-04:00
status: draft
tags: [object-model]
---

# Memory

Memory supplies handoff and link checks.
The before-compact hook reads runtime JSON and checks the latest workspace handoff. Compaction always continues.

From the system folder, inspect command options:

```sh
python3 memory/check.py --help
```

Read [the system guide](../GUIDE.md) and [the global contract](../profile/AGENTS.md).

| `lessons.py` | Reads active lessons for the workspace start page. |
| `lessons.sql` | Defines the lesson rows and views that the reader uses. |
