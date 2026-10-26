---
type: doc
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
example_for: sample-shop
---

# RESOLVER.md — Cedar Shop
Read the owner of a fact before changing it. A report tells you where to look.

## Look it up
The `lookup` skill answers what a name or path is and where it belongs.
Planned skill: [[foxrun/modules/base/skills/lookup/SKILL]]. Implementation: not built at this draft's source check.
Command contract: `lookup.py <name-or-path> --db <workspace.sqlite>`.
It reads `object_types` for `module`, `container`, `lens`, `database_type`, `storage_name`, and definition sources.
It reads `fields` for names, meanings, `pick_values`, and `pick_source`; `v_dictionary` joins both.
Dictionary fallback describes the model; it does not prove an installed Cedar Shop table.
Dictionary blueprint: [[foxrun/modules/base/dictionary.sql]]. Observed map: [[examples/sample-shop/index]].

## Where things go
The proposed stamp follows module ownership. Current files remain authoritative until an approved adoption changes their owners.
| What it is | Current owner → target |
|---|---|
| Product identity and catalog state | [[sample-shop/catalog]] and approved connected systems → commerce source mirrors and owned identity records |
| Amazon work | [[sample-shop/amazon/listings]], [[sample-shop/amazon/compliance]], [[sample-shop/amazon/restock]], [[sample-shop/amazon/expansion]] → owning module rows |
| Creator relationship | [[sample-shop/content/deals]] and creator records → people, UGC, and design rows |
| TikTok Shop state | [[sample-shop/tiktok/shop]] and [[sample-shop/tiktok/content-engine]] → deferred TikTok Shop module |
| Work and business words | Work rows; [[examples/sample-shop/GLOSSARY-context]] holds the proposed vocabulary |
| Explanations and original evidence | [[sample-shop/notes]], [[sample-shop/wiki]], and dated evidence collections |
| Activity history | Current [[sample-shop/log]] → target [[sample-shop/history/log.jsonl]] through `fx-log` |

## Who writes what
Keep one writer per field. A mirror is never a second place to edit the source.
| Fields | Writer | Boundary |
|---|---|---|
| Creator terms and accepted progress | lead through authorized module commands | ugc-producer proposes changes; it does not commit deal state independently. |
| Products, shipments, and stock | Shopify or ShipBob; designated feeder writes the copy | Put local notes in owned rows linked to the source identity. |
| Listing facts | Amazon; listing feeder writes the copy | Proposed changes and submitted versions stay separate from the mirror. |
| Message facts | small-talk feeder | Scope by thread; a person's identity does not authorize every conversation. |
| Media metadata | UGC media-index feeder | File availability and usage rights remain separate facts. |
| Dated obligations | Reconciler appends observations | Missing evidence never becomes zero owed. |
| Generated pages | agent-team, keeper, or report generator | Correct sources, then regenerate. |

## When two sources disagree
Retain both claims, their source, and their time. Record the disputed field and stop dependent actions.
Do not turn ShipBob “Completed” into delivery or a payment claim into confirmed receipt.
Use verified receipts or Person's direct confirmation for payment proof; unresolved disputes stay visible.
That rule comes from [[foxrun/modules/ugc/module#Payment proof]], which records its precedence over the older proof rule.
Use ruled definitions for adoption. Open and soft choices stay open; an inventory proposal cannot change an approval.
The current owner remains in [[sample-shop/RESOLVER]] until an approved migration runs.

## Pointers
[[examples/sample-shop/AGENTS]], [[examples/sample-shop/SCHEMA]], [[{{definition_root}}/README]], and [[sample-shop/specs/2026-09-17-creator-desk]] define the rules and target shapes.

## Backlinks
[[examples/sample-shop/AGENTS]], [[examples/sample-shop/CLAUDE]], and [[examples/sample-shop/SCHEMA]] point here.
