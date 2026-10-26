---
type: doc
workspace: system
---
# Thread product source

This folder holds the source of the `thread` skill.

| File | Purpose |
|---|---|
| `README.md` | Lists the thread source files and their purposes. |
| `SKILL.md` | Defines the steps to list, plan, make, and record agent threads. |
| `bin/thread` | Lists agents and threads, plans a title and boot prompt, and makes or records a thread. |
| `replays/plan-agent-codex.json` | Checks an agent's Codex plan: title, model tier, and boot command. |
| `replays/plan-lead-claude-cli.json` | Checks a workspace lead's terminal plan with `claude --bg`. |
| `replays/refuse-agent-without-workspace.json` | Checks that an agent thread needs a workspace answer. |
| `tests/__init__.py` | Marks the thread test package. |
| `tests/test_thread.py` | Checks listing, planning, refusals, dry runs, both made routes against stub apps, and a workspace agent made by `agent_new`. |
