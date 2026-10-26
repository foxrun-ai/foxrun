---
type: doc
workspace: system
timestamp: 2026-10-22T11:48:23-04:00
---
# Agents

Claude and Codex on day one.
Agent definitions live in this folder.
`scout.md` defines the Scout seat, which brings outside material into raw/. The first workspace agent lives in generated/.
The installer creates its Claude and Codex files in the workspace team folder.

Put a personal seat in `profile/agents/<seat>.md` under the system home.
This file wins over `agents/<seat>.md`; otherwise, the shipped seat loads.
Workspace team seats keep their current priority. Starts name the file they load.
Installs and updates never replace personal seats. Build runtime files again after a seat change.

From the system folder, inspect the agent command:

```sh
python3 agents/tools/agent_new.py --help
```

Create a Cedar Shop agent without starting a runtime:

```sh
python3 agents/tools/agent_new.py create cedar-helper --role 'Checks deliveries' --summary 'Checks Cedar Shop deliveries.' --tier work --skills '' --tools '' --client cedar-shop --runtimes claude,codex --dry-run
```

Remove `--dry-run` to write its identity and runtime files.
The command refuses excluded runtime requests before creating files.
Read [the system guide](../GUIDE.md) and [the global contract](../profile/AGENTS.md).

| `.git/` | This folder's own Git history. |
