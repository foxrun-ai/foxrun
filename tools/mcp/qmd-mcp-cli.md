---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "qmd-mcp-cli"
what: "Add-on: On-device note search engine"
kind: "mcp"
use: "vault & search"
status: "chosen"
command: "qmd"
---
# qmd-mcp-cli

qmd-mcp-cli is "An on-device search engine for everything you need to remember." (its makers' words). In plain words: it searches your saved notes on this computer.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents search your notes by words or by meaning before they browse folders.
- Recall work uses it to find past talks, people, decisions, and topic history.
- After files move, agents run `qmd update` so search stays current.
- The first search after a rest can stall; agents wait about 5 seconds and retry once.

**Install:** [qmd](https://github.com/tobi/qmd) · `npm install -g @tobilu/qmd`

| Field | Value |
|---|---|
| Use | vault & search · [all tools, by use](../CAPABILITIES.md) |
| Kind | mcp |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. npm puts the command on your path; its index stays on this computer. |
| His yes | Installing it needs your yes. |
| Source | The tool: `https://github.com/tobi/qmd`. Foxrun's use: the note search tool choice. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `npm install -g @tobilu/qmd` | — |
| Add notes | `qmd collection add <folder> --name <name>` | the collection |
| Check | `qmd status` | collections and document counts |

## Use

| To | Run |
|---|---|
| Find matching words | `qmd search "project timeline"` |
| Find matching meaning | `qmd query "quarterly planning process"` |
| Read a saved note | `qmd get "<path>.md"` |
| Serve agent tools | `qmd mcp` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Tool command | `command -v qmd` shows it. |
| Index | qmd keeps it in its own cache folder. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `qmd-mcp-cli.local.md` beside this page; that page never ships.
