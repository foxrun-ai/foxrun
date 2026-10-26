---
type: index
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
example_for: sample-shop
generated: true
generated_by: keeper
generation_status: example only
---

# index.md — Cedar Shop
This example separates target package shapes from dated disk evidence. A live index generation time is not set yet.

## Files by root group
This is the proposed stamp's root order. It does not claim these targets are installed.
| Group | Files or collections |
|---|---|
| contracts | [[examples/sample-shop/AGENTS]], [[examples/sample-shop/CLAUDE]], [[examples/sample-shop/RESOLVER]], [[examples/sample-shop/SCHEMA]], [[examples/sample-shop/GLOSSARY-context]]; [[foxrun/modules/design/templates/DESIGN]] and [[foxrun/modules/design/templates/BRAND]] |
| team | [[examples/sample-shop/tools/CAPABILITIES]], [[examples/sample-shop/index]]; generated team assignments and workspace skill installation: not set yet |
| business | [[examples/sample-shop/sample-shop]], [[examples/sample-shop/ugc]], Amazon and TikTok Shop function templates; target [[sample-shop/data.db]] |
| knowledge | [[sample-shop/wiki]], [[sample-shop/notes]], [[sample-shop/design]], [[sample-shop/notes]], [[sample-shop/snapshots]], [[sample-shop/handoffs]], [[sample-shop/outputs]] |
| history | Target [[sample-shop/history/log.jsonl]] and [[sample-shop/archive]] |
Current owners and old paths remain in [[sample-shop/RESOLVER]] until approved adoption.

## Database
The following objects come from package blueprints, including the base dictionary's separate blueprint.
Their live installation, row counts, and newest ages are not set yet. An unqueried count is never zero.
| Type | Name | Module | Owner / outside source | Rows | Newest age | Age field |
|---|---|---|---|---|---|---|
| table | functions | work | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | goals | work | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | measures | work | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | projects | work | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | tasks | work | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | task_links | work | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | activity | work | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | comments | work | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | attachments | work | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | decisions | work | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | approvals | work | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | persons | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | organizations | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | organization_memberships | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | handles | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | threads | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | participants | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | pipelines | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | pipeline_stages | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | opportunities | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | interactions | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | meetings | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | agreements | people | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | content | design | Authorized local writer | not set yet | not set yet | Change timestamp binding not set yet |
| table | object_types | base | Dictionary installer | not set yet | not set yet | Change timestamp binding not set yet |
| table | fields | base | Dictionary installer | not set yet | not set yet | Change timestamp binding not set yet |
| mirror | messages | people | small-talk | not set yet | not set yet | pulled_at |
| trend | measure_history | work | Observation writer; activation not set yet | not set yet | not set yet | as_of |
| view | open_decisions | work | Source rows; no separate writer | not set yet | not set yet | Input timestamps; binding not set yet |
| view | open_tasks | work | Source rows; no separate writer | not set yet | not set yet | Input timestamps; binding not set yet |
| view | needs_me | work | Source rows; no separate writer | not set yet | not set yet | Input timestamps; binding not set yet |
| view | this_week | work | Source rows; no separate writer | not set yet | not set yet | Input timestamps; binding not set yet |
| view | next_step | work | Source rows; no separate writer | not set yet | not set yet | Input timestamps; binding not set yet |
| view | eisenhower | work | Source rows; no separate writer | not set yet | not set yet | Input timestamps; binding not set yet |
| view | v_open_threads | people | Source rows; no separate writer | not set yet | not set yet | Input timestamps; binding not set yet |
| view | v_pipeline_board | people | Source rows; no separate writer | not set yet | not set yet | Input timestamps; binding not set yet |
| view | v_people_without_handles | people | Source rows; no separate writer | not set yet | not set yet | Input timestamps; binding not set yet |
| view | v_dictionary | base | Source rows; no separate writer | not set yet | not set yet | Input timestamps; binding not set yet |
The base dictionary definition is [[foxrun/modules/base/dictionary.sql]]; other definitions follow the manifests below.
Views inherit input age. Query time does not refresh their sources, and newest age does not prove complete coverage.
The UGC reply view requires an interface check against people before installation; see [[foxrun/modules/ugc/module#Views]].

**Made-up product examples:** Cedar Shop uses Garden trowel and Seed tray.
No inventory observation or outside account is included.
The default install excludes business packs according to their manifest marks.

## Modules installed
Installation receipts are not set yet. These are available package definitions, each at version 0.1.0.
| Module | Tier | Version | Installation receipt / state | Manifest |
|---|---|---|---|---|
| base | base | 0.1.0 | not set yet / draft package | [[foxrun/modules/base/module]] |
| work | base | 0.1.0 | not set yet / draft package | [[foxrun/modules/work/module]] |
| people | base | 0.1.0 | not set yet / draft package | [[foxrun/modules/people/module]] |
| design | base | 0.1.0 | not set yet / draft package | [[foxrun/modules/design/module]] |
| wiki | base | 0.1.0 | not set yet / draft package | [[foxrun/modules/wiki/module]] |
| commerce | workspace-type:ecom | 0.1.0 | not set yet / draft package | [[foxrun/modules/commerce/module]] |
| amazon | add-on | 0.1.0 | not set yet / draft package | [[foxrun/modules/amazon/module]] |
| ugc | add-on | 0.1.0 | not set yet / draft package | [[foxrun/modules/ugc/module]] |
| tiktok-shop | add-on | 0.1.0 | not set yet / deferred package | [[foxrun/modules/tiktok-shop/module]] |
The root order comes from [[{{definition_root}}/README-workspace-pages]]. This example installs nothing.

## Backlinks
[[examples/sample-shop/AGENTS]], [[examples/sample-shop/RESOLVER]], and [[examples/sample-shop/SCHEMA]] point here.
