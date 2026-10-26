---
type: agents
workspace: foxrun-dev
timestamp: 2026-10-20T18:56:44-04:00
status: draft
tags: [object-model, data-model-definition]
---

# AGENTS.md — {{workspace}}
Name the business, who it serves, and the result agents must protect.

## Who this serves
Write one sentence about {{owner}}, {{audience}}, and {{purpose}}; keep replies short and business-plain.

## The map
Keep these five groups in order; groups organize the root display and do not create folders.
| Group | What belongs here |
|---|---|
| contracts | [[{{workspace}}/AGENTS]], [[{{workspace}}/CLAUDE]], [[{{workspace}}/RESOLVER]], [[{{workspace}}/GLOSSARY]] |
| team | [[{{workspace}}/tools/CAPABILITIES]], [[{{workspace}}/index]], generated team files and installed skills |
| business | The module rows in [[{{workspace}}/{{workspace}}.sqlite]] |
| knowledge | [[{{workspace}}/wiki]], [[{{workspace}}/specs]], [[{{workspace}}/notes]], [[{{workspace}}/config]], [[{{workspace}}/raw]] |
| history | [[{{workspace}}/history/LOG]], [[{{workspace}}/history]] |

## Doors and load order
Read `{{definition_root}}/../profile/AGENTS.md`, this contract, [[{{workspace}}/RESOLVER]], then the task; use [[{{workspace}}/index]] and [[{{workspace}}/tools/CAPABILITIES]] as maps.

## The team
Generate this block from approved assignments; name each agent's responsibility and handoff.
<!-- BEGIN GENERATED TEAM: agent-team -->
| Agent | Responsibility | Returns to |
|---|---|---|
| {{agent}} | {{responsibility}} | {{accountable_owner}} |
<!-- END GENERATED TEAM: agent-team -->

## Routing table
Route by what the thing is; use [[{{workspace}}/RESOLVER]] when the owner is unclear.
| It is a… | Home |
|---|---|
| Task, decision, or changing business fact | Owning module's rows in [[{{workspace}}/{{workspace}}.sqlite]] |
| Build specification | [[{{workspace}}/specs]] |
| Living note | [[{{workspace}}/notes]] |
| Compiled knowledge | [[{{workspace}}/wiki]] |
| Note, exact capture, handoff, or finished output | Matching dated collection in [[{{workspace}}/index]] |

## Approval gates
Keep Portfolio gates and add {{local_gates}}; bind approval to the exact action, recipient, account, version, and attachments.
Money, sends, purchases, production changes, and catalog changes need explicit approval.

## Work pattern
Verify {{work_command}} targets this workspace before using these actions; record soft calls instead of hiding them.
`work claim <TASK> --by <actor>` · `work comment <TASK> --by <actor> "reason"` · `work done <TASK> --by <actor> --receipt <path> --proof "result"` · `work block <TASK> --by <actor> "blocker"`
Repeat `--receipt` for every output. Submission for review does not prove acceptance; check the task's returned state.

## No-touch surfaces
Name {{protected_surfaces}} and their owners; apply `{{definition_root}}/../profile/AGENTS.md` before touching shared settings, secrets, indexes, or other agents' work. Use the approved secret reader. Never print a secret.

## Pointers
Keep deeper rules in [[{{workspace}}/GLOSSARY]] and [[{{definition_root}}/README-workspace-pages]].

## Backlinks
List contracts that point here: [[{{workspace}}/CLAUDE]] and [[{{workspace}}/RESOLVER]].
