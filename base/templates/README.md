---
type: doc
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
---

# Contract templates — Second pass
Nine blank templates and nine Cedar Shop examples, shaped for Person to read himself.

## The nine files
Each template shows the full page. Its example fills known facts and leaves unknowns visible.
| Template | What it is for | Cedar Shop example |
|---|---|---|
| [AGENTS](AGENTS.md) | Workspace rules, team, routing, gates, and work receipts. | [AGENTS](examples/sample-shop/AGENTS.md) |
| [CLAUDE](CLAUDE.md) | Claude imports the workspace contract; only local differences go here. | [CLAUDE](examples/sample-shop/CLAUDE.md) |
| [RESOLVER](RESOLVER.md) | Find the source, allowed writer, and treatment of conflicting facts. | [RESOLVER](examples/sample-shop/RESOLVER.md) |
| [SCHEMA](SCHEMA.md) | Read module shapes, names, frontmatter, and sourced status lists. | [SCHEMA](examples/sample-shop/SCHEMA.md) |
| [GLOSSARY-context](GLOSSARY-context.md) | Use business words and approved tags; retire older terms carefully. | [GLOSSARY-context](examples/sample-shop/GLOSSARY-context.md) |
| [CAPABILITIES](CAPABILITIES.md) | See workflows, agents, reports, and supporting tools by function. | [CAPABILITIES](examples/sample-shop/CAPABILITIES.md) |
| [index](index.md) | See files, database objects, source age, and module installation evidence. | [index](examples/sample-shop/index.md) |
| [[{{workspace}}]] | See decisions, this week's work, goals, measures, and projects. | cedar-shop (not included) |
| [[{{function}}]] | See the seat, owner, goals, workflows, collections, and exceptions. | [ugc](examples/sample-shop/ugc.md) |
The home template installs under the workspace's name. The function template uses the function's name.
The Cedar Shop function example is UGC.

## What changed
The first pass remains in templates (not included). This pass adds readable structure and complete page shapes.
| First pass | Second pass |
|---|---|
| Filler boxes before the useful text | Direct opening lines and tables that carry actual information |
| Missing sections and weak navigation | Full contract headers, wikilinks, and Backlinks on every file |
| Generic routing | Named lookup skill, dictionary fields, source owners, and conflict handling |
| Empty generated stubs | Complete capability and index layouts, with unknowns and missing builds shown |
| No home or function template | Both reports show their full sections and row sources |
| Only blank contracts | A source-backed Cedar Shop example beside every template |

## How to use these drafts
Read the example, then fill the blank template from approved source facts.
All package files carry `workspace: foxrun`; this run requires that metadata even for examples.
At an approved installation, stamp the target workspace, timestamp, and approved tags. Resolve all placeholders.
Keep draft publication status separate from business state. A generated page does not approve or complete work.
The examples are written samples of generated pages. Their generators did not run, and no live contract changed.
The existing install mapping still names the first pass. This task supplies a reviewable second pass only.
Example links point to these example contracts where possible; current-source links retain their real names.

## Source choices
The vault [[AGENTS]] supplies the voice and section pattern; [[CLAUDE]] supplies the mechanical shim.
Current context comes from AGENTS (not included), RESOLVER (not included), [[SCHEMA]], and [[index]].
Business evidence comes from 2026-09-17-creator-desk (not included) and cedar-shop-data-inventory-v2 (not included).
Package evidence comes from the nine manifests listed in [[examples/cedar-shop/index#Modules installed]].
The definition lives in workspace-spec (not included), schema (not included), and glossary (not included).
The requested shelf-name check used `ls ~/.foxrun/skillwright/skills | grep -i -E 'Owner|amazon|creator|shopify|shipbob'`.
Only names were read. gbrain-skill-creator matched the text filter; no creator-business assignment was inferred.
Role definitions were read from the agent-team source files linked in [[examples/cedar-shop/CAPABILITIES#Agents]].

## Soft calls
Two choices were recorded through `work comment source-note`.
| Choice | Treatment |
|---|---|
| Draft packages do not prove live installation | Examples separate targets from dated evidence; unverified facts say “not set yet.” |
| Lookup is assigned to source-note and was absent at the source check | Name `lookup` and its dictionary interface; mark its implementation “not built.” |
The common brief's package metadata applies to both templates and examples.
An existing target receives a `.new` suffix before its extension; no first-pass file is replaced.

## Receipts
This README, every template, and every example in the nine-file table are source-note's 19 receipt files.
The work command receives each path with its own `--receipt` argument.
Its activity receipt retains all paths; task links can collapse matching template and example basenames.

## Backlinks
[CAPABILITIES](examples/sample-shop/CAPABILITIES.md) points here for the visible template list. No source contract was changed to add a backlink.
