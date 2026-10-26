---
type: doc
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
example_for: sample-shop
---

# GLOSSARY-context.md — Cedar Shop
Keep the business words precise. Shared model words live in the glossary.

Cedar Shop sells made-up garden tools: Garden trowel and Seed tray.

## Business words
These meanings come from the workspace contract, Creator desk spec, and module definitions.
| Word | What it means here | Source |
|---|---|---|
| Creator cycle | One set of creator commitments; renewals can overlap earlier obligations. | [[sample-shop/specs/2026-09-17-creator-desk]] |
| Deliverable | A promised output with its own quantity, due date, and acceptance evidence. | [[sample-shop/specs/2026-09-17-creator-desk]] |
| Usage rights | Evidence that permits a specific use, platform, territory, and time period. | [[sample-shop/specs/2026-09-17-creator-desk]] |
| Payment proof | A verified receipt or Person's direct confirmation; a dispute remains visible. | [[foxrun/modules/ugc/module#Payment proof]] |
| ShipBob Completed | Handoff to the carrier; delivery needs separate confirmation. | [[sample-shop/AGENTS]] |
| Catalog | Product facts used by live commerce operations; changes need production approval. | [[sample-shop/AGENTS]] |

## Approved tags
Approved tags belong in rows, with one list for Cedar Shop. This example does not verify an installed store or reader.
Source and reader: not verified. Do not maintain a second approved list in this file.
The Creator desk spec uses `ugc`; that occurrence does not establish the approved list.
Use the nearest approved parent only when its approval exists. Otherwise keep tagging pending and record a proposal.
The Keeper approves proposed tags; a proposal is not an approval.
Source: [[foxrun/outputs/2026-09-20-foundation-tag-authority.json]], ruling `approved-tags-keeper`.

## Retired words
Use the replacement for new work. Preserve the wording in historical evidence.
| Older term | Use now | Source |
|---|---|---|
| creators as the add-on name | ugc; individual creator-* names remain valid | [[foxrun/notes/data-model-definition/glossary#Retired terms and replacements]] |
| snapshot as a database type | trend; exact file captures remain snapshots | [[foxrun/notes/data-model-definition/glossary#Trend]] |
| review-event | approval for Person's response to an exact version | [[foxrun/notes/data-model-definition/glossary#Approval]] |
| HOME.md | sample-shop.md, generated from views | [[{{definition_root}}/README-workspace-pages#The home page and its sources]] |

## Pointers up to the glossary
[[foxrun/notes/data-model-definition/glossary]] defines shared words. [[examples/sample-shop/SCHEMA]] connects them to stored fields.
The current vocabulary contract remains [[sample-shop/GLOSSARY-context]] until adoption.

## Backlinks
[[examples/sample-shop/AGENTS]], [[examples/sample-shop/RESOLVER]], and [[examples/sample-shop/SCHEMA]] point here.
