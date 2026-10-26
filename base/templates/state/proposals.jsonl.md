---
type: template
workspace: foxrun-dev
timestamp: 2026-10-24T16:19:19-04:00
status: draft
tags: [base, state, proposals]
---
# Proposal inbox

## At a glance

```text
┌─────────────┐   append   ┌─────────────────┐
│ Cloud agent │ ────────> │ proposals.jsonl │
└─────────────┘           └────────┬────────┘
                                  │ request
                         ┌────────▼──────────┐
                         │ Local work writer │
                         └────────┬──────────┘
                                  │ approved change
                         ┌────────▼────────┐
                         │ Database +      │
                         │ activity row    │
                         └─────────────────┘
```

| Item | Rule |
|---|---|
| Inbox | `foxrun/state/proposals.jsonl` |
| Cloud agent | Appends requests to this one file. |
| Local work writer | Applies approved proposals. |
| Initial content | Empty file; no example rows. |

## Row shape

Append one complete JSON object per line, followed by a newline. All eight fields are required.

| Field | Value |
|---|---|
| `id` | Unique proposal identifier; nonempty string. |
| `at` | Creation time; ISO 8601 string with a timezone offset. |
| `by` | Proposing agent identifier; nonempty string. |
| `subject_type` | Target object type understood by the local work writer; string. |
| `subject_id` | Existing target object's identifier; string. |
| `field` | One target field name; string. |
| `proposed_value` | Proposed value in its native JSON type, including `null` when allowed. |
| `reason` | Explanation and supporting evidence references; nonempty string. |

Example only; do not seed the inbox with this row:
```json
{"id":"proposal-example-001","at":"2026-09-18T17:56:42-04:00","by":"cloud-agent-example","subject_type":"task","subject_id":"TASK-EXAMPLE","field":"title","proposed_value":"Check stock levels","reason":"Use a clear action title."}
```

## Who applies a proposal

Cloud agents only append requests here. They never edit existing lines, database rows, or exported state to apply changes.
Only the local work writer applies a proposal after Person approves it and field rules permit it.
The writer checks the target, field, value, and evidence. Every accepted work change leaves an `activity` row.
A proposal is not approval or proof of application. Status `done` requires evidence against `done_check`.
Definition: How state travels, in the workspace spec. Field rules: Work sync principles. Both pages stay in Foxrun HQ and do not ship.
