---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "cua-driver"
what: "Add-on: computer-use driver (Cua)"
kind: "cli"
use: "computer use"
status: "chosen"
command: "cua-driver"
---
# cua-driver

cua-driver is "cross-platform computer-use automation driver" (its makers' words). In plain words: it lets an agent see the screen and click and type in Mac apps.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- It is the pick for computer use: to see a window and click or type in an app.
- Agents use it for an app that has no command or MCP server.
- It can serve its tools to an agent as an MCP server with `cua-driver mcp`.

**Install:** [Cua](https://github.com/trycua/cua) · `cua-driver permissions grant`

| Field | Value |
|---|---|
| Use | computer use · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. The app puts the `cua-driver` command on your path. |
| His yes | Installing it and granting screen access need your yes. A click that sends, buys, or deletes needs your yes. |
| Source | The tool: its source page at `https://github.com/trycua/cua`. Foxrun's use: the computer-use tool choice. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | Install CuaDriver.app from its source page | — |
| Grant access | `cua-driver permissions grant` | macOS asks for Accessibility and Screen Recording |
| Check | `cua-driver permissions status` | Accessibility and Screen Recording state |

## Use

| To | Run |
|---|---|
| List its tools | `cua-driver list-tools` |
| Serve tools to an agent | `cua-driver mcp` |
| Check for an update | `cua-driver check-update` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Tool command | `command -v cua-driver` shows it. |
| Screen access | System Settings, Privacy & Security: Accessibility and Screen Recording. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `cua-driver.local.md` beside this page; that page never ships.
