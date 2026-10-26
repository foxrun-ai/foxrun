---
type: agents
workspace: <ws>
timestamp: <timestamp>
tags: [contracts]
---

Start: `python3 <home>/foxrun.py start --workspace <ws>`

# <Workspace Name>

## What This Workspace Is For

<One line of purpose.>

1. Read the overview first: [<ws>.md](<ws>.md).

## Where Things Live Here

<List only places that exist in this workspace.>

- **State:** <the tracker: its own `data.db` if it has one, else `~/.foxrun/data.db`>. Its tables are named in [RESOLVER.md](RESOLVER.md).
- **Semantic:** <wiki/ and the key pages that hold what is true here>
- **Procedural:** <skills/>. <For each function, in rank order: "When you work on <function>, read <page>.">
- **Episodic:** [history/](history/)
- **Code:** <src/ and its repos, if any>
- **In the system home:** `~/.foxrun/workspaces/<ws>/` (its skills, team, and tools lists) and `~/.foxrun/archive/<ws>/`

## When To Ask Here

<Gates added to the global ones only. Leave this section out if there are none.>

## How Things Work Here

<Local facts that stop a wrong claim. Leave this section out if there are none.>
