---
type: note
workspace: system
timestamp: 2026-10-26T14:30:00-04:00
name: workspace
description: "Make a new workspace or check one in the Portfolio: plan the create-only install, apply it on a yes, and run the read-only structure check. Use for /workspace new, /workspace check, or when someone says set up a workspace, add a workspace, or is this workspace healthy."
kind: knowledge
argument-hint: "new <name> [personal | ecom] | check <name>"
---

# workspace

A workspace is one folder in the Portfolio, `~/foxrun/<ws>/`, with its own `AGENTS.md`.
`new` plans first and writes only on the person's yes, because a new workspace is hard to take back.
`check` only reads. It never edits the workspace.

## Steps

1. **New: check the name.** Use lowercase kebab case. Run `ls ~/foxrun/` and `cat ~/foxrun/AGENTS.md`. If the name is taken, or another workspace already owns the subject, stop and say so. Done when the name is free and no workspace owns the subject.
2. **New: plan.** Run `python3 ~/.foxrun/base/install_workspace.py --target-workspace <ws> --workspace-type <personal|ecom> --by <you> --plan-out <scratch>/workspace-plan.json`. Run it with `--help` for the module options. Show the person the folders and files the plan makes. Done when the person said yes to that plan.
3. **New: apply.** Run `python3 ~/.foxrun/base/install_workspace.py --apply <scratch>/workspace-plan.json`. Done when `~/foxrun/<ws>/AGENTS.md` exists.
4. **Check.** Run `python3 ~/.foxrun/base/check_workspace.py <ws>` for JSON, or add `--output-prefix <outside folder>/<name>` to keep a report. Exit 0 is clean, 1 is findings, 2 is a run error. Done when you have the exit code and the findings.
5. **Report.** For each finding, give the path and the fix, or say why it stays. A finding is not a go: file a fix as a task with the `task` skill. Done when each finding has a fix, a task, or a reason.

## Gotchas

- Read the new workspace's `AGENTS.md` before you work in it.
- The plan is create-only. It never changes a file that already exists.
- Keep a check report outside the workspace it checks.
