---
type: home
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
generated: true
generated_by: "{{function_generator}}"
generation_status: template only
---

# {{function}} — {{workspace}}
Generate this page from the function's rows and views; show {{observed_at}} and {{coverage}}.

## The seat
Name the continuing responsibility, its boundaries, and its row; a function has no project end date.
{{function_purpose}} · Function row: {{function_id}} · Parent: {{parent_function}}.

## Owner
Read the accountable owner from the function row and show who prepares work for that owner.
{{owner}} is accountable. {{supporting_agents}} return {{handoff}} through [[{{workspace}}/tools/CAPABILITIES]].

## Goals and measures
Read this function's goals, measures, and dated observations; preserve unknown values.
| Goal / horizon | Measure | Actual / target | Owner / source / age |
|---|---|---|---|
| {{goal}} / {{horizon}} | {{measure}} | {{actual}} / {{target}} | {{owner}} / {{view}} / {{age}} |

## Workflows
Show the recurring work, its schedule, responsible agent, source procedure, and missing steps.
| Workflow | Owner / schedule | Source | State |
|---|---|---|---|
| {{workflow}} | {{owner}} / {{schedule}} | [[{{workflow_source}}]] | not built |

## Collections
List collections this seat uses, with their owning modules, types, and named views.
| Collection | Module / database type | Read through | Writer |
|---|---|---|---|
| {{collection}} | {{module}} / {{database_type}} | {{view}} | {{writer}} |
Modules own collections; the function filters work through fields.

## What needs attention
Show approvals, blockers, residual obligations, and source gaps from the function's views.
{{attention_rows}} · [[{{workspace}}/{{workspace}}]] · [[{{workspace}}/RESOLVER]].
Correct source rows, then regenerate this page.

## Backlinks
List contracts that point here: [[{{workspace}}/AGENTS]].
