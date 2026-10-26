---
type: capabilities
workspace: foxrun-dev
timestamp: 2026-09-18T18:11:02-04:00
status: draft
tags: [object-model, data-model-definition]
generated: true
generated_by: agent-team
generation_status: template only
---

# CAPABILITIES.md — {{workspace}}
Generate from source definitions; group each section by function and keep missing work visible.

## Workflows
List each workflow's ordered steps, responsible agent, input, output, return, skill, and build state.
| Function | Workflow / step | Agent | Input → output → return | Skill / state | Source |
|---|---|---|---|---|---|
| {{function}} | {{workflow}} / {{step}} | {{agent}} | {{input}} → {{output}} → {{recipient}} | {{skill}} / not built | [[{{workflow_source}}]] |

## Agents
List approved responsibility and handoff boundaries; distinguish role definitions from verified workspace assignments.
| Function | Agent | Owns / returns to | Assignment | Source |
|---|---|---|---|---|
| {{function}} | {{agent}} | {{responsibility}} / {{recipient}} | {{assignment_state}} | [[{{agent_source}}]] |

## Reports
Name the reader, source views, output, and generator; do not duplicate report data here.
| Function | Report / reader | Views | Output | Generator / state |
|---|---|---|---|---|
| {{function}} | {{report}} / {{reader}} | {{views}} | [[{{report_path}}]] | {{generator}} / not built |

## Skills
List current names, module, implementation evidence, and any visible templates under the skill.
| Function | Skill | Module / state | Source / templates |
|---|---|---|---|
| {{function}} | {{skill}} | {{module}} / {{build_state}} | [[{{skill_source}}]]; [[{{visible_template}}]] |

## Schedules
List timing, owner, workflow, latest receipt, and activation; missing timing is “not set yet.”
| Function | Schedule / timing | Owner / workflow | Latest receipt | State |
|---|---|---|---|---|
| {{function}} | {{schedule}} / {{timing}} | {{owner}} / {{workflow}} | [[{{receipt}}]] | not built |

## MCPs
Name each service connection, its job, and its verified state without exposing credentials.
| Function | Connection | Job / state | Source |
|---|---|---|---|
| {{function}} | {{mcp}} | {{job}} / {{verified_state}} | [[{{connection_guide}}]] |

## CLIs
Name each command's target and scope; a command's existence does not prove workspace readiness.
| Function | Command | Target / scope | State / source |
|---|---|---|---|
| {{function}} | {{command}} | {{target}} / {{scope}} | {{build_state}} / [[{{command_guide}}]] |

## Hooks
List each trigger, effect, owner, and verified installation; keep unknowns visible.
| Function | Hook / trigger | Effect / owner | State / source |
|---|---|---|---|
| {{function}} | {{hook}} / {{trigger}} | {{effect}} / {{owner}} | {{build_state}} / [[{{hook_guide}}]] |

## Plugins
List installed plugins or kits, their function, and source evidence; planned items remain “not built.”
| Function | Plugin or kit | Job / state | Source |
|---|---|---|---|
| {{function}} | {{plugin}} | {{job}} / {{build_state}} | [[{{plugin_source}}]] |

## Backlinks
List contracts that point here: [[{{workspace}}/AGENTS]] and [[{{workspace}}/CLAUDE]].
