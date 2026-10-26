---
type: doc
workspace: foxrun-dev
timestamp: 2026-09-18T17:56:49-04:00
status: draft
tags: [object-model, data-model-definition]
---

# RESOLVER.md — {{workspace}}

## At a glance

```text
┌───────────────────────────────────────┐
│ Fact → owning source → allowed writer │
└───────────────────────────────────────┘
```

| Information | Authoritative home and format | Writer |
| --- | --- | --- |
| Local mutable state | Owning module's tables in {{workspace}}.sqlite | Authorized module commands |
| Outside facts | Outside system; local mirrors are dated copies | Source system; feeder refreshes copies |
| Rules and shapes | AGENTS.md, SCHEMA.md; linked definitions | Authorized contract author |
| Business words and tags | GLOSSARY-context.md | Person; keeper proposes |
| Explanations | notes/, specs/, and installed wiki kit | Document author or keeper |
| Historical evidence | Dated files, log.jsonl, and module history rows | Capturing author or event writer |
| Team identity | Agent-team source definitions | Agent-team; runtime copies are generated |
| Maps and capabilities | index.md and tools/CAPABILITIES.md, derived from their sources | Keeper and agent-team |

## Resolve a fact

Use the [lookup skill](../skills/lookup/SKILL.md) to identify an object and its home.
From the vault root, run:

```sh
python3 foxrun/modules/base/lookup.py "<name or path>" --db "<workspace sqlite>"
```

The command reads dictionary rows. Missing definitions remain unknown.

Use [index.md](index.md) to find the installed module and named table, mirror, trend, or view.
Read that module's field contract before choosing a writer.
Check mirror source and age; a local copy does not transfer ownership.
Reports and handoffs do not override current source rows.
If ownership remains unclear, preserve both sources and record the unresolved choice.

## Pointers

[Resolver definition]({{definition_root}}/README.md) defines this contract.
[Workspace definition]({{definition_root}}/README-workspace-pages.md) defines source boundaries and generated copies.
