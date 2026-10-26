---
type: doc
workspace: system
---
# Foxrun skill map

Read this page when someone asks which skill fits. Pick one skill. Say why in one line.

## The session path

Most work runs along one path. Each step has one skill.

| When | Skill | First command |
|---|---|---|
| A session starts | `orient` | `/orient` |
| You save midway | `checkpoint` | `/checkpoint` |
| Something material happens | `log` | `/log` |
| The session ends | `handoff` | `/handoff` |

## Work objects

Each tracker object has one skill. The operation is the argument, such as `/task create`.

| Object | Skill | Use it to |
|---|---|---|
| Task | `task` | Create, show, claim, finish, or move one piece of work. |
| Work stream | `stream` | Create, show, or rename a work stream. |
| Bug | `bug` | Open, show, link, or close a defect. |
| Program | `program` | Create or show a program and its plan. |
| Goal | `goal` | Create a goal or tie a task to it. |
| Decision | `decision` | Record a ruling the person made. |
| Worker results | `queue` | Count and list results that wait for review. |

## Knowledge

| You have | Skill |
|---|---|
| A plan to build | `spec` |
| A working note | `note` |
| A page about a topic or a thing | `wiki` |
| A rule the agents learned | `lesson` |

## Code and system

| You need to | Skill |
|---|---|
| Commit, open a pull request, merge, clean branches, or use a worktree | `git` |
| Push work forward without waiting to be asked | `push` |
| Make or check a workspace | `workspace` |
| Run setup again | `foxrun-setup` |

## When nothing fits

Say no skill fits. Name the nearest one, and say what it does not cover.
Do not invent a skill name. Run `ls ~/.foxrun/skills/` to see what is installed.
