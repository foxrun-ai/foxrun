---
type: doc
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
---

# GLOSSARY-context.md — {{workspace}}
Keep the business words Person uses; link shared definitions instead of copying them.

## Business words
Define {{business_term}} in one plain sentence and link the source that supports it.
| Word | What it means here | Source |
|---|---|---|
| {{business_term}} | {{meaning}} | [[{{definition_source}}]] |

## Approved tags
Point to the workspace's approved tag rows; do not maintain a second list in this file.
Source and reader: {{verified_tag_store_and_reader}}. Leave unavailable storage explicitly unresolved.
The Keeper approves additions. Agents propose tags; they never invent approved tags.
If no tag fits, use the nearest approved parent and record a proposal.
If no parent is approved, keep the item pending and propose a tag to the Keeper.
Source: [[foxrun/outputs/2026-09-20-foundation-tag-authority.json]], ruling `approved-tags-keeper`.

## Retired words
Name older terms and their replacements without changing historical source wording.
| Older term | Use now | Source |
|---|---|---|
| {{retired_term}} | {{replacement}} | [[{{decision_source}}]] |

## Pointers up to the glossary
Use [[foxrun/notes/data-model-definition/glossary]] for shared words and [[{{workspace}}/SCHEMA]] for their stored fields.

## Backlinks
List contracts that point here: [[{{workspace}}/AGENTS]], [[{{workspace}}/RESOLVER]], and [[{{workspace}}/SCHEMA]].
