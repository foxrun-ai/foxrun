---
type: home
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
generated: true
generated_by: "{{home_generator}}"
generation_status: template only
---

# {{workspace}} — What needs attention
Generate this home page from views; show {{observed_at}} and {{coverage}} before anyone acts.

## What needs me
Show exact decisions, replies, and approvals with their source row and next action.
| Item / source row | Decision needed | Exact draft / evidence | Owner |
|---|---|---|---|
| {{item}} / {{row_id}} | {{decision}} | [[{{evidence}}]] | {{owner}} |

## This week
Read the work queue; show dates and blockers without copying editable state into this page.
| Task / row | Planned / due | Owner | Blocker / source view |
|---|---|---|---|
| {{task}} / {{row_id}} | {{planned}} / {{due}} | {{owner}} | {{blocker}} / {{view}} |

## Goals and measures
Show each goal, measure, current value, target, owner, and source age; missing values stay “not set yet.”
| Goal / horizon | Measure | Actual / target | Owner / source / age |
|---|---|---|---|
| {{goal}} / {{horizon}} | {{measure}} | {{actual}} / {{target}} | {{owner}} / {{view}} / {{age}} |

## Projects
Show finite outcomes from rows; link each project's explanation and next task.
| Project / row | Outcome | Next task / owner | Explanation |
|---|---|---|---|
| {{project}} / {{row_id}} | {{outcome}} | {{next_task}} / {{owner}} | [[{{project_page}}]] |

## Functions
Give each function one line, in its approved order, with its owner and report.
| Function | Owner | Needs attention | Report |
|---|---|---|---|
| {{function}} | {{owner}} | {{exception}} | [[{{workspace}}/{{function}}]] |

## Data age and handoff
Name stale or missing sources, the last successful refresh, and the latest verified handoff.
{{source_warnings}} · [[{{latest_handoff}}]] · [[{{workspace}}/index]].
Correct source rows, then regenerate this page.

## Backlinks
List contracts that point here: [[{{workspace}}/AGENTS]].
