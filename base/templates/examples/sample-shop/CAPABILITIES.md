---
type: capabilities
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
example_for: sample-shop
generated: true
generated_by: agent-team
generation_status: example only
---

# CAPABILITIES.md — Cedar Shop
This example shows the full generated page. Sources establish package scope and role definitions; workspace activation is not set yet.

## Workflows
Creator desk defines the five morning steps below. Its live integration is not built in these module packages.
| Function | Workflow / step | Agent | Input → output → return | Skill / state | Source |
|---|---|---|---|---|---|
| ugc | Creator morning / 1. Orient | lead | Source age and work → blockers → ugc-producer | creator-collabs; integration not built | [[sample-shop/specs/2026-09-17-creator-desk]] |
| ugc | Creator morning / 2. Prepare | ugc-producer | Reply, payment, content, rights queues → proposals → lead | creator-collabs, sample-shop-payment; integration not built | [[sample-shop/specs/2026-09-17-creator-desk]] |
| ugc | Creator morning / 3. Draft | small-talk; lead checks | Scoped evidence → exact reply versions → lead | creator-comms through small-talk; integration not built | [[sample-shop/specs/2026-09-17-creator-desk]] |
| ugc | Creator morning / 4. Present | lead | Checked drafts → full approval cards → Person | Card adapter; not built here | [[sample-shop/specs/2026-09-17-creator-desk]] |
| ugc | Creator morning / 5. Finish | lead; authorized executor | Exact approval → action receipt → source rows and Person | Approval and execution adapters; not built here | [[sample-shop/specs/2026-09-17-creator-desk]] |
| amazon | Listing preparation | amazon-operator | Listing evidence → correction package → Person through lead | shopify-to-amazon, amazon-image-classifier; workflow definition not set yet | [[sample-shop/AGENTS]] |
| tiktok-shop | Operations loop | not set yet | Source orders → report → not set yet | not built | [[foxrun/modules/tiktok-shop/module]] |
The morning time and channel remain not set yet. The spec's 8 a.m. Eastern proposal is not an active schedule.

## Agents
Role definitions exist. This example does not attest generated workspace assignments.
| Function | Agent | Owns / returns to | Assignment | Source |
|---|---|---|---|---|
| Across functions | lead | Coordinates work, checks evidence, presents decisions / Person | not set yet | [[~/.foxrun/agents/agents/lead]] |
| ugc | ugc-producer | Creator research, terms, shot lists, delivery follow-up / lead | not set yet | [[~/.foxrun/agents/agents/ugc-producer]] |
| amazon | amazon-operator | Listing audits, correction packages, support drafts / coordinated review | not set yet | [[~/.foxrun/agents/agents/amazon-operator]] |
ugc-producer never sends, orders, or pays. amazon-operator never submits changes or contacts support.

## Reports
Reports present saved views. Rendering a page never gives it ownership of business state.
| Function | Report / reader | Views | Output | Generator / state |
|---|---|---|---|---|
| Workspace | Home / Person | needs_me, this_week; goal and project view bindings not set yet | [[examples/sample-shop/sample-shop]] | Report integration not built here |
| ugc | Creator morning / Person | Proposed creator-desk-card; package views v_reply_queue, v_payments_owed, v_missing_content, v_rights_expiring | [[examples/sample-shop/ugc]] | Creator desk integration not built here |
| amazon | Exceptions / Person | v_suppressed_listings, v_open_compliance_cases | [[foxrun/modules/modules/amazon/templates/amazon]] | Page renderer not built |
| tiktok-shop | Orders and age / Person | not built | [[foxrun/modules/modules/tiktok-shop/templates/tiktok-shop]] | tiktok-operations-report; not built |
Sources: [[sample-shop/specs/2026-09-17-creator-desk]], [[foxrun/modules/work/module]], [[foxrun/modules/ugc/module]], [[foxrun/modules/amazon/module]], and [[foxrun/modules/tiktok-shop/module]].
The Creator desk view names and package view names differ; their integration remains an explicit build gap.

## Skills
These are exact names from module lists and the requested shelf-name check. No matching skill contents were opened.
| Function | Skill names | Module / state | Source / visible templates |
|---|---|---|---|
| ugc | creator-collabs, creator-comms, sample-shop-payment, sample-shop-outreach | ugc; names found, database adaptation not built here | [[foxrun/modules/ugc/module]] |
| ugc | create-creator-page, find-creator-email, dropbox-creator-file-request | ugc; names found, adaptation not built here | [[foxrun/modules/ugc/module]]; [[foxrun/modules/people/module]] |
| amazon | amazon-image-classifier, shopify-to-amazon | amazon; names found, package absorption only | [[foxrun/modules/amazon/module]] |
| Across commerce functions | sample-shop-shopify-data, shipbob-order | commerce; names found | [[foxrun/modules/commerce/module]] |
| Across commerce functions | read-shopify-data, manage-fulfillment-orders | Proposed job names; not built | [[foxrun/modules/commerce/module]] |
| Across functions | sample-shop, sample-shop-email | Names found; module binding not set yet | [[sample-shop/AGENTS]] |
| Across functions | maintain-people, find-contact | people; proposed job names, not built | [[foxrun/modules/people/module]] |
| Across functions | work | work; command exists for Foxrun; Cedar Shop binding not set yet | [[foxrun/modules/work/module]] |
| Across functions | lookup | base; not built at source check | [[foxrun/modules/base/skills/lookup/SKILL]] |
| Across functions | fx-log, fx-hygiene-inbox, fx-hygiene-today | base; named absorption candidates | [[foxrun/modules/base/module]]; [[README]] lists visible contract templates |
| Across functions | design-consultation, frontend-design, design-shotgun, imagegen | design; named absorption candidates | [[foxrun/modules/design/module]]; [[foxrun/modules/design/templates/DESIGN]], [[foxrun/modules/design/templates/BRAND]] |
| Across functions | deck, slides, design-review, qa-only | design; named absorption candidates | [[foxrun/modules/design/module]] |
| Across functions | llm-wiki, wiki-upkeep, research, last30days, deep-research, capability | wiki; named kit associations | [[foxrun/modules/wiki/module]] |
| tiktok-shop | tiktok-source-feeder, tiktok-operations-report | Proposed; not built | [[foxrun/modules/tiktok-shop/module]] |
| not set yet | gbrain-skill-creator | Name matched “creator”; business assignment not set yet | Shelf-name check only |
The generic gbrain-skill-creator match does not establish a creator-business capability.
Module lists propose packaging; they do not prove a skill was installed or renamed.

## Schedules
Timing requirements stay separate from evidence that a schedule runs.
| Function | Schedule / timing | Owner / workflow | Latest receipt | State |
|---|---|---|---|---|
| ugc | Creator morning / not set yet | lead / Creator morning | not set yet | Live integration not built here |
| ugc | Payment observations / daily requirement | Reconciler / payments_owed_daily | not set yet | Reconciler not built |
| Across commerce functions | Orders, shipments, stock / daily requirement; catalog / weekly requirement | Source feeders | not set yet | Feeders not built |
| amazon | Health history / not set yet | Health schedule | not set yet | not built |
Sources: [[sample-shop/specs/2026-09-17-creator-desk]], [[foxrun/modules/ugc/module]], [[foxrun/modules/commerce/module]], and [[foxrun/modules/amazon/module]].

## MCPs
Agent definitions name connections; active accounts and workspace configuration are not set yet.
| Function | Connection | Job / state | Source |
|---|---|---|---|
| Across functions | qmd | Retrieval; live binding not set yet | [[sample-shop/AGENTS]] |
| amazon, ugc | shipbob | Fulfillment evidence; live binding not set yet | [[~/.foxrun/agents/agents/amazon-operator]]; [[~/.foxrun/agents/agents/ugc-producer]] |

## CLIs
Check the command's target before using it. The current work command points at Foxrun.
| Function | Command | Target / scope | State / source |
|---|---|---|---|
| Across functions | work claim, comment, done, block, show | Foxrun tasks; receipt submission flags review | Exists / [[foxrun/modules/work/module]] |
| Across functions | lookup.py | Dictionary definitions; workspace selection through --db | not built / [[foxrun/modules/base/skills/lookup/SKILL]] |
| Across commerce functions | Source feeder commands | Cedar Shop mirrors | not built / [[foxrun/modules/commerce/module]] |

## Hooks
Workspace-specific hooks are not set yet in the supplied module manifests.
| Function | Hook / trigger | Effect / owner | State / source |
|---|---|---|---|
| Across functions | not set yet | not set yet | not set yet; no installation claim |

## Plugins
The wiki is a kit. Its package description does not prove a new installation.
| Function | Plugin or kit | Job / state | Source |
|---|---|---|---|
| Across functions | wiki kit | Compiled knowledge and raw evidence; native wiki exists, package installation receipt not set yet | [[foxrun/modules/wiki/module]]; [[sample-shop/RESOLVER]] |
| Across functions | Other plugins | not set yet | not set yet |

## Backlinks
[[examples/sample-shop/AGENTS]] and [[examples/sample-shop/CLAUDE]] point here.
