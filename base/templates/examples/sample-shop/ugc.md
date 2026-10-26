---
type: home
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
example_for: sample-shop
generated: true
generated_by: not set yet
generation_status: example only
---

# UGC — Cedar Shop
This example shows the function report. Live row values, source coverage, and observation time are not set yet.

## The seat
UGC handles creator relationships, commitments, content delivery, and usage-rights evidence.
It continues after the Creator desk build ends. Function row and parent binding: not set yet.
Definitions: [[foxrun/notes/data-model-definition/glossary#Function]] and [[foxrun/modules/ugc/module]].

## Owner
lead is accountable; ugc-producer prepares creator work and returns its evidence to lead.
The module establishes that responsibility. The installed function-row binding is not set yet.
See [[examples/sample-shop/tools/CAPABILITIES]] and [[sample-shop/specs/2026-09-17-creator-desk]].

## Goals and measures
Targets and observed results remain not set yet. Queue names do not create approved measures.
| Goal / horizon | Measure | Actual / target | Owner / source / age |
|---|---|---|---|
| not set yet | not set yet | not set yet | not set yet |
Goal definitions belong to work rows. Dated observations belong in measure_history.

## Workflows
The Creator desk spec describes the morning workflow; its live integration is not built in these packages.
| Workflow | Owner / schedule | Source | State |
|---|---|---|---|
| Creator morning: orient, prepare, draft, present, finish | lead / not set yet | [[sample-shop/specs/2026-09-17-creator-desk]] | Integration not built here |
| Reconcile dated payment obligations | Reconciler owner not set yet / daily requirement | [[foxrun/modules/ugc/module]] | Reconciler not built |
Nothing sends, orders, or pays without the required exact approval.

## Collections
The seat uses shared collections from several modules; it does not own a separate copy of their state.
| Collection | Module / database type | Read through | Writer |
|---|---|---|---|
| Creator cycles and deliverables | ugc / table | v_missing_content | lead accepts ugc-producer proposals |
| Content permissions | ugc / table | v_rights_expiring | lead records checked evidence |
| File requests | ugc / table | v_missing_content | Approved file-request adapter |
| Media files | ugc / mirror | v_missing_content | UGC media-index feeder; not built |
| Payment observations | ugc / trend | v_payments_owed | Reconciler; not built |
| People, opportunities, agreements | people / table | v_pipeline_board; other bindings not set yet | Authorized local writer |
| Threads and messages | people / table and mirror | v_open_threads → v_reply_queue | Local thread writer; small-talk writes the message mirror |
| Content | design / table | Exact acceptance view binding not set yet | Authorized design writer |
Sources: [[foxrun/modules/ugc/module]], [[foxrun/modules/people/module]], and [[foxrun/modules/design/module]].
Payment-request and payment-proof records in the spec exceed this UGC package's scope. The integration must supply them.

## What needs attention
Current replies, debt, missing content, and rights exceptions are not set yet.
Absent payment observations do not mean zero owed. Closed relationships can retain obligations.
File availability does not prove permission; a shipment status does not prove delivery.
Home: [[examples/sample-shop/sample-shop]]. Writers and disputed evidence: [[examples/sample-shop/RESOLVER]].
Correct source rows, then regenerate this report.

## Backlinks
[[examples/sample-shop/AGENTS]] points here.
