---
type: doc
workspace: system-workspace
timestamp: 2026-09-18T21:29:09-04:00
tags: [contracts, commands]
---

# Proposal Rules

A proposal field always needs an accepted proposal. A gated transition needs one only when a field moves into a listed value. An approval lock names routine fields that cannot change directly after the row has an accepted proposal. A proposal can include those fields and required evidence with the controlled change. Every other change is routine. The source is the four version 0.1.0 module blueprints.

## Machine block

```proposal-fields
people.opportunities: outcome, value, currency, offer_summary
people.agreements: type, status, counterparty_person_id, counterparty_organization_id, start, end, value, currency, file_hash, signed_at, supersedes_id, rights_summary
```

```gated-transitions

```

```approval-locks
people.opportunities: person_id, organization_id, primary_handle_id, pipeline, evidence_refs
people.agreements: agreement_family_id, version, opportunity_id, file_path, evidence_refs
```

```approved-rows
people.opportunities: outcome=won|lost|abandoned
people.agreements: status=signed
```

Tables with no proposal field: `persons`, `organizations`, `organization_memberships`, `handles`, `threads`, `participants`, `pipelines`, `pipeline_stages`, `interactions`, `meetings`, `support_cases`, `accounts`, `compliance_cases`.

## Why, per field

| Table | Field | Why |
|---|---|---|
| people.opportunities | outcome | Marks deal won or lost |
| people.opportunities | value | Deal money amount |
| people.opportunities | currency | Changes the money amount |
| people.opportunities | offer_summary | What we offered them |
| people.agreements | type | Changes the contract kind |
| people.agreements | status | Marks sent, signed, expired |
| people.agreements | counterparty_person_id | Who holds the promise |
| people.agreements | counterparty_organization_id | Who holds the promise |
| people.agreements | start | Contract term start |
| people.agreements | end | Contract term end |
| people.agreements | value | Contract money amount |
| people.agreements | currency | Changes the money amount |
| people.agreements | file_hash | Which document is the contract |
| people.agreements | signed_at | Marks the contract signed |
| people.agreements | supersedes_id | Replaces a prior contract |
| people.agreements | rights_summary | Content rights we hold |
| ugc.creator_cycles | agreement_id | Which contract governs cycle |
| ugc.creator_cycles | agreed_amount | Money owed to creator |
| ugc.creator_cycles | currency | Changes the money amount |
| ugc.creator_cycles | closed_at | Marks cycle delivered, done |
| ugc.creator_cycles | closed_with_exceptions | Accepts a short delivery |
| ugc.deliverables | agreement_id | Which contract governs promise |
| ugc.deliverables | format | What creator must make |
| ugc.deliverables | platform | Where creator must post |
| ugc.deliverables | quantity | How many pieces promised |
| ugc.deliverables | due_date | Deadline promised to creator |
| ugc.deliverables | required_shots | Shots creator must deliver |
| ugc.deliverables | acceptance_criteria | Bar for accepting work |
| ugc.deliverables | published_required | Posting duty on creator |
| ugc.deliverables | status | Marks promise agreed or waived |
| ugc.deliverables | waiver_ref | Releases creator from promise |
| ugc.content_permissions | agreement_id | Contract behind the right |
| ugc.content_permissions | content_id | Which content right covers |
| ugc.content_permissions | creator_id | Whose content right covers |
| ugc.content_permissions | platform | Where we can use it |
| ugc.content_permissions | usage | Organic, paid, editing scope |
| ugc.content_permissions | territory | Countries right covers |
| ugc.content_permissions | valid_from | Right start date |
| ugc.content_permissions | valid_until | Right end date |
| ugc.content_permissions | status | Grants or revokes rights |
| ugc.file_reqs | status | Marks the outbound send transition |
| ugc.file_reqs | approval_ref | Agents cannot self-approve |
| commerce.restocks | approved_quantity | Commits money to stock |
| commerce.restocks | status | Marks approved, ordered, received |
| commerce.receivings | status | Marks stock count confirmed |

## Unsure

Each line gives the field, the argument, and the call.

1. `people.opportunities.outcome` — `lost` and `abandoned` are internal, but `won` marks a closed deal. Call: **proposal**.
2. `people.opportunities.stage` — a late stage can imply a deal. The ruling names internal stage as routine. Call: **routine**.
3. `people.agreements.type`, `counterparty_person_id`, `counterparty_organization_id` — set one time at draft creation, rarely changed after. A change moves the promise to a different party. Call: **proposal**.
4. `people.agreements.file_path` — a moved file is housekeeping. `file_hash` already guards which document is the contract. Call: **routine**.
5. `people.agreements.version`, `agreement_family_id` — identity keys, not terms. Call: **routine**.
6. `ugc.creator_cycles.period_start`, `period_end`, `cycle_type` — they frame what the amount pays for. The binding terms live on the agreement and the deliverables. Call: **routine**.
7. `ugc.creator_cycles.amount_unknown_reason` — it lets a cycle exist with no amount. It commits nothing. Call: **routine**.
8. `ugc.creator_cycles.closure_evidence_ref`, `ugc.content_permissions.evidence_ref`, `commerce.receivings.evidence_ref` — the database requires them with a proposal status. They are evidence pointers, not decisions. Call: **routine**. The proposal must carry them in the same write.
9. `ugc.creator_cycles.shipment_ids` — links a product shipment (real cost) to a cycle. It records a fact from the ShipBob mirror. Call: **routine**.
10. `ugc.deliverables.quantity_unknown_reason` — same logic as item 7. Call: **routine**.
11. `ugc.file_reqs.status` — `sent` is the only gated transition. Receipt-backed `received` and other internal values are routine. Call: **gated transition**.
12. `ugc.file_reqs.expires_at`, `url`, `link_state` — link housekeeping. Call: **routine**.
13. `commerce.restocks.requested_quantity`, `due_on` — a request is a draft ask. `approved_quantity` and `status` carry the money decision. Call: **routine**.
14. `commerce.receivings.quantity` — the count affects stock truth. A count is an observation, and corrections go through `supersedes_id`. `status = confirmed` is the gate. Call: **routine**.
15. `commerce.support_cases.status` — `resolved` can follow a refund promise, but the table holds no money or promise column. Call: **routine**.
16. `amazon.accounts.status`, `legal_entity` — a local label only. It does not pause the real Amazon account. Call: **routine**.
17. `amazon.compliance_cases.status` — tracks our internal work. Amazon's words stay in `source_status`. Call: **routine**.
