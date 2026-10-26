---
type: agents
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
example_for: sample-shop
---

# AGENTS.md — Cedar Shop
Draft workspace contract for Cedar Shop garden tools: Garden trowel and Seed tray. This example does not activate the proposed stamp.

## Who this serves
Person runs the business from his phone. Give him clear decisions, complete drafts, and evidence he can check.
lead coordinates the work. The workspace owner decides brand calls, payments, and agent approvals.

## The map
Read the root in five groups. These are display groups, not new folders.
| Group | What belongs here |
|---|---|
| contracts | [AGENTS](sample-shop-AGENTS.md), [CLAUDE](../templates/CLAUDE.md), [RESOLVER](../templates/RESOLVER.md), [SCHEMA](../templates/SCHEMA.md), `CONCEPTS`; design adds `DESIGN` and `BRAND` |
| team | [CAPABILITIES](../templates/CAPABILITIES.md), [index](index-definition.md), generated team files and installed skills |
| business | `sample-shop`, flat function reports such as `ugc`, and the target `data.db` |
| knowledge | `wiki`, `docs`, `design`, `notes`, `snapshots`, `handoffs`, `outputs` |
| history | Target `log.jsonl` and `archive` |

## Doors and load order
Read [AGENTS](sample-shop-AGENTS.md), this contract, [RESOLVER](../templates/RESOLVER.md), then the task and its evidence.
Use [index](index-definition.md) and [CAPABILITIES](../templates/CAPABILITIES.md) as maps. Query the owning source for current state.

## The team
This sample uses the named roles; generated workspace assignments are not set yet.
<!-- BEGIN GENERATED TEAM: agent-team -->
| Agent | Responsibility | Returns to |
|---|---|---|
| lead | Coordinates creator, catalog, shipment, and listing work; checks evidence | Person |
| ugc-producer | Prepares creator terms, shot lists, and delivery follow-up | lead |
| amazon-operator | Audits listings and prepares corrections, upload packages, and support drafts | lead coordinates; Person reviews |
<!-- END GENERATED TEAM: agent-team -->

## Routing table
The proposed stamp puts state in rows. Until adoption, [RESOLVER](../templates/RESOLVER.md) keeps its current owners.
| It is a… | Target home |
|---|---|
| Task, project, decision, or approval | Work module rows |
| Person, agreement, or opportunity | People module rows |
| Creator cycle, promise, or permission | UGC module rows; design owns content |
| Product, shipment, stock, or restock | Commerce rows; outside facts stay in mirrors |
| Listing or compliance case | Amazon mirror or local case table |
| Explanation, knowledge, or evidence | `docs`, `wiki`, or the matching dated collection |

## Approval gates
Show Person the exact action, recipient, account, version, attachments, and evidence before any external action.
Money, sends, orders, purchases, deletes, catalog changes, and account changes need his explicit yes.
ShipBob products fulfill live orders. For approved merges, preserve the existing product and verify its identifiers afterward.
ShipBob “Completed” means carrier handoff. Delivery needs carrier or creator confirmation.
Approved copy is not permission to send. A received file does not prove advertising rights.

## Work pattern
Use `work claim`, `work comment`, `work done --receipt … --proof …`, and `work block`; every write names `--by`.
Claim before work. Record soft calls and blockers. Submit every output with a receipt and one clear proof line.
The current `work` command targets Foxrun and flags review; a Cedar Shop command binding is not set yet.
Do not run that command against Cedar Shop work until its target is verified. See [module](../../work/install.json).

## No-touch surfaces
Apply [AGENTS](sample-shop-AGENTS.md) to runtime settings, secrets, indexes, shared skills, and other agents' work.
Acceptance drills only read and draft; their own handoff and receipt are the permitted writes.
Use the approved secret reader. Never print a secret.

## Pointers
Sources: [AGENTS](sample-shop-AGENTS.md), `2026-09-17-creator-desk`, `workspace-spec`, [SCHEMA](../templates/SCHEMA.md), and `CONCEPTS`.

## Backlinks
[CLAUDE](../templates/CLAUDE.md) and [RESOLVER](../templates/RESOLVER.md) point here.
