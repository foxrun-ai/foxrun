---
type: doc
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
example_for: sample-shop
---

# SCHEMA.md — Cedar Shop
These are draft package shapes. Installation and migration receipts are not set yet.

## Shapes in this workspace
Modules define the target shapes; the inventory records older disk evidence.
| Module | Shapes | Field definition |
|---|---|---|
| base | Contracts, generated maps, document and history collections; dictionary in a separate blueprint | [[foxrun/modules/base/module]] |
| work | Functions, goals, measures, projects, tasks, decisions, approvals, activity; one trend and six views | [[foxrun/modules/work/module]] |
| people | People, organizations, threads, opportunities, agreements; message mirror and three views | [[foxrun/modules/people/module]] |
| design | Content table; design and brand contracts; design files | [[foxrun/modules/design/module]] |
| wiki | Compiled pages, raw sources, research answers; native kit format | [[foxrun/modules/wiki/module]] |
| commerce | Six mirrors, three local tables, stock trend, four views | [[foxrun/modules/commerce/module]] |
| amazon | Accounts, compliance cases, two mirrors, health trend, two views | [[foxrun/modules/amazon/module]] |
| ugc | Four local tables, media mirror, payment trend, four views | [[foxrun/modules/ugc/module]] |
| tiktok-shop | Order mirror and function page; deferred | [[foxrun/modules/tiktok-shop/module]] |
The broader Creator desk spec includes payment and proof records beyond the current UGC package.
Those records remain a build gap; see [[sample-shop/specs/2026-09-17-creator-desk]].

## Names and frontmatter
Use short kebab names and reserved contract names. Frozen artifacts use dated names; the wiki keeps its native format.
```yaml
type: spec
workspace: sample-shop
timestamp: 2026-09-17T17:48:25-04:00
status: draft
tags: [ugc]
```
This is source metadata from [[sample-shop/specs/2026-09-17-creator-desk]]. It does not establish an approved workspace tag list.
Tags require the list in [[examples/sample-shop/GLOSSARY-context]]; current business status belongs in rows.

## Status lists and where they came from
The work blueprint supplies these exact lists; preserve spelling and do not reuse them for unrelated records.
| Field | Allowed values | Source |
|---|---|---|
| tasks.status | backlog, todo, in-progress, blocked, done, canceled | [[foxrun/modules/work/module#tasks]] |
| projects.status | backlog, todo, in-progress, done, canceled | [[foxrun/modules/work/module#projects]] |
| decisions.status | open, soft, ruled, deferred, withdrawn, superseded | [[foxrun/modules/work/module#decisions]] |
| approvals.call | approve, discuss, wrong, edit | [[foxrun/modules/work/module#approvals]] |
Other choices come from `fields.pick_values` and `fields.pick_source`; use `lookup`.
Keep outside statuses in source fields. Unknown values remain unknown.

## Pointers up to the definition
Shared fields: [[{{definition_root}}/README]]. Homes: [[{{definition_root}}/README-workspace-pages]].
Writers: [[examples/sample-shop/RESOLVER]]. Observed counts: [[examples/sample-shop/index]].

## Backlinks
[[examples/sample-shop/AGENTS]], [[examples/sample-shop/RESOLVER]], and [[examples/sample-shop/GLOSSARY-context]] point here.
