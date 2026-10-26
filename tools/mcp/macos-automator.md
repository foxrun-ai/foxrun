---
type: "tool"
workspace: "system"
timestamp: "2026-10-20T00:37:50-04:00"
name: "macos-automator"
what: "Add-on: AppleScript and JXA server"
kind: "mcp"
use: "computer use"
status: "chosen"
command: "macos_automator"
---
# macos-automator

macos-automator is "MCP Server to execute AppleScript and JXA on macOS." (its makers' words). In plain words: it lets an agent run small scripts that control Mac apps such as Notes, Finder, and Safari.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents create, search, and read Apple Notes, with formatting and real checklists.
- Agents move, make, and find files in Finder, and drive other Mac apps by script.
- It reaches Mac apps that have no command of their own.
- A long note body goes in one single-line string; the line break mark `¬` makes long scripts time out.

**Install:** [macos-automator-mcp](https://github.com/steipete/macos-automator-mcp) · `claude mcp add macos_automator -- npx -y @steipete/macos-automator-mcp@latest`

| Field | Value |
|---|---|
| Use | computer use · [all tools, by use](../CAPABILITIES.md) |
| Kind | mcp |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you add it. `npx` fetches the server each time a runtime starts it. |
| His yes | Adding the server and each Mac permission need your yes. A script that sends, deletes, or changes settings needs your yes. |
| Source | The tool: `https://github.com/steipete/macos-automator-mcp`, its README and `package.json`. Foxrun's use: Apple Notes and Finder work. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Get Node.js | `brew install node` (version 18 or newer) | — |
| Install | `claude mcp add macos_automator -- npx -y @steipete/macos-automator-mcp@latest` (Codex: add the same command to your Codex MCP settings) | — |
| Allow apps | System Settings, Privacy & Security, Automation: tick each app it may control | — |
| Allow clicks | System Settings, Privacy & Security, Accessibility: add the app that runs the server | — |
| Check | `claude mcp list` | a `macos_automator` line |

## Use

| To | Run |
|---|---|
| Run a script | `execute_script` with `script_content` |
| Run a ready recipe | `execute_script` with `kb_script_id` |
| Find a recipe | `get_scripting_tips` with `search_term` |
| Read an app's buttons | `accessibility_query` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Server entry | Each runtime's MCP settings, under the name `macos_automator`. |
| Log detail | `LOG_LEVEL` in the server entry. |
| Mac access | System Settings, Privacy & Security: Automation and Accessibility. |

## Notes

- The server cannot grant its own permissions. The first use of a new app can show a Mac prompt.
- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `macos-automator.local.md` beside this page; that page never ships.
