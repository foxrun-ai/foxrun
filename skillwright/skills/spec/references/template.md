---
type: doc
workspace: system
---
# Spec template

Read this page at step 4 of the spec skill. Copy the sections. Drop an optional section when it does not apply.

```markdown
---
type: spec
workspace: <ws>
timestamp: <ISO time with offset>
status: draft
task: <task id>
---
# <task id> · <what this builds, and for what>

## Problem
What breaks today, the cause, and the evidence.

## Goal
What this solves.

## Non-goals
What this does not solve.

## Use cases
Before and after, as a table. Optional.

## Design
The parts that change, their interfaces, the data shape, and the decisions made. Cite rulings by id.

## Success criteria
| ID | Criterion | How it is measured |
|---|---|---|
| Q-1 | A number a program checks | The command |
| B-1 | A behavior a person checks | The steps |

## Testing plan
The seams, in order: structure, then behavior, then a live check. Name prior tests to copy.

## Rollback
How to undo it. Required for a data move, a delete, or a change on an outside platform.

## Risks
| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|

## Out of scope
Work that someone may expect here, but that is not part of it.

## Updates
- <date>: <what changed>
```
