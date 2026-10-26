---
type: doc
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
---

# RESOLVER.md — {{workspace}}
Name the source to read and the writer to use before changing a fact.

## Look it up
Use the lookup command; supply a name or path and the verified tracker.
Command: `python3 {{definition_root}}/lookup.py <name-or-path> --db <tracker>`; the tracker is the workspace `data.db`, else the system `data.db`.
Read `object_types` for module, container, lens, database type, and storage name.
Read `fields` for field meaning, `pick_values`, and `pick_source`; `v_dictionary` joins both.
A definition lookup cannot prove live installation, ownership, or freshness; check [[{{workspace}}/index]].

## Where things go
Fill each destination from installed module definitions; leave unknown homes as “not set yet.”
| What it is | Authoritative home |
|---|---|
| Local record / outside fact | {{local_table}} / {{source_system}} with {{mirror_name}} as its dated copy |
| Business words and approved tags | [[{{workspace}}/GLOSSARY]] |
| Rules and shapes | [[{{workspace}}/AGENTS]] |
| Build specification | [[{{workspace}}/specs]] |
| Living note / compiled knowledge | [[{{workspace}}/notes]] / [[{{workspace}}/wiki]] |
| Original evidence | [[{{workspace}}/raw]] |
| Work history | {{event_writer}} appends to [[{{workspace}}/history/LOG]] |

## Who writes what
Assign one writer to each field; a second system can propose a change, but cannot silently take ownership.
| Fields | Writer | Rule |
|---|---|---|
| {{local_fields}} | {{module_command}} | Record source evidence and the accepted change. |
| {{mirror_fields}} | {{source_feeder}} | Outside-owned; mirrors are never edited locally. |
| {{trend_fields}} | {{observation_writer}} | Append dated observations; preserve earlier rows. |
| Generated pages | {{page_generator}} | Read source rows; fix the source and regenerate. |

## When two sources disagree
Keep both claims with their source and time; record the disputed field and block dependent action.
A newer copy does not outrank its owner. An approval applies only to its exact version.
Use current ruled decisions for adopted definitions; open and soft decisions remain unsettled.
Before adoption, preserve the current owner and require a reviewed migration.

## Pointers
Read [[{{definition_root}}/README]], [[{{definition_root}}/README-workspace-pages]], and [[{{workspace}}/index]] for the definitions and installed map.

## Backlinks
List contracts that point here: [[{{workspace}}/AGENTS]] and [[{{workspace}}/CLAUDE]].
