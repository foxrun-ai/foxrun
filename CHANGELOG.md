---
type: doc
workspace: system
timestamp: 2026-10-19T19:35:51-04:00
---
# Changelog

## 10.19 changes (still 0.1.0)

The core ships fewer parts. The business packs left the product. People ships with Small Talk. The design framework left the core.
Nothing personal ships. Names come from `config/person.json`, and the shipped files carry front matter.
The person's own files install once and then belong to the person: the soul, gates, git rules, words, and lint lists.
`AGENTS.md`, `RESOLVER.md`, and `CLAUDE.md` were merged into one version each.
Install connects the session-start check and the nightly job for Claude, Codex, and Hermes. A new person's first session works end to end.
Lessons are rows now, and the start page shows them.
Skillwright ships skills from two sources. The person's skill wins over a product skill with the same name.
`flow.py` runs a named flow and records each step on its task.
`GUIDE.md` and `INSTALL.md` stay installed. Install builds `SCHEMA.md` with `base/generate_pages.py`.
Each top-level file, `health.json`, `state/`, `capture/`, and `workspaces/` has one owner.
The product tests that sat at the top moved into `tests/`. The old index builder `base/generate_index.py` is gone; `base/generate_index_v2.py` stays.

## 0.1.0

Initial product assembly with core modules, agents, and two skills.

Workspace task commands use the existing tracker tables and select the workspace database when present.
Start rejects unknown workspaces and shows only the selected workspace tasks.
Before-compact hooks discover the latest handoff and always allow compaction.
Installation validates the shipped table names without a missing-blueprint warning.
The product retains all tests of shipped code.
