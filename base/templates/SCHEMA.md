---
type: doc
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
---

# SCHEMA.md — {{workspace}}
Show the installed shapes; keep full field definitions with their owning module.

## Shapes in this workspace
Repeat one row per installed module; link the manifest and name its exact stored shapes.
| Module | Shapes | Field definition |
|---|---|---|
| {{module}} | {{tables_mirrors_trends_views_and_files}} | [[{{module_manifest}}]] |
Knowledge and procedures live in files; current records live in rows.
History uses frozen files or appended rows. Reports own no business state.

## Names and frontmatter
Use short kebab names, reserved contract names, and the subtype's required fields.
Dated artifacts use `YYYY-MM-DD-###-<slug>`; native wiki files follow their kit.
```yaml
type: "{{object_type}}"
workspace: "{{workspace}}"
timestamp: "{{iso_timestamp_with_offset}}"
status: draft
tags: ["{{approved_tag}}"]
```
This draft's metadata does not approve business work. Select tags from [[{{workspace}}/GLOSSARY-context]].

## Status lists and where they came from
Name each pick field, its exact choices, and the definition that supplied them.
| Field | Allowed values | Source |
|---|---|---|
| {{object_type}}.{{field}} | {{pick_values}} | [[{{pick_source}}]] |
The `lookup` skill reads `fields.pick_values` and `fields.pick_source`; it must not invent a choice.
Keep outside status text separate from local status. Missing is unknown, never zero or complete.

## Pointers up to the definition
Use [[{{definition_root}}/README]] for shared shapes and [[{{definition_root}}/README-workspace-pages]] for file homes.
Use [[{{workspace}}/RESOLVER]] for writers and [[{{workspace}}/index]] for observed counts.

## Backlinks
List contracts that point here: [[{{workspace}}/AGENTS]], [[{{workspace}}/RESOLVER]], and [[{{workspace}}/GLOSSARY-context]].
