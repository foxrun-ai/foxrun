---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "paper"
what: "Paper design app server"
kind: "mcp"
use: "creator & content"
status: "chosen"
command: "(MCP at 127.0.0.1:29979)"
---
# paper

In plain words: Paper is a design canvas app. Its MCP server lets an agent read and edit designs while the app is open.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents read and edit designs through its MCP server.
- Agents move a Paper design into Figma as a paste-ready vector, one frame at a time.
- The server runs only while Paper.app is open; a closed app refuses the connection.

**Install:** [Paper](https://paper.design) · `claude mcp add -s user -t http paper http://127.0.0.1:29979/mcp`

| Field | Value |
|---|---|
| Use | creator & content · [all tools, by use](../CAPABILITIES.md) |
| Kind | mcp |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. While the app is open, its local server listens on `127.0.0.1:29979`, on this computer only. |
| His yes | Installing it needs your yes. A design you publish or share needs your yes. |
| Source | The tool: `https://paper.design`. Foxrun's use: the design tool choice. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | Download Paper.app from paper.design | — |
| Register | Add an MCP server named `paper` at `http://127.0.0.1:29979/mcp` in each runtime | — |
| Check | `lsof -nP -iTCP:29979 -sTCP:LISTEN` | a Paper line while the app is open |

## Use

| To | Run |
|---|---|
| Read or edit a design | Open Paper.app, then ask the agent; its tools are `mcp__paper__*` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Server address | `http://127.0.0.1:29979`, in each runtime's MCP settings. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `paper.local.md` beside this page; that page never ships.
