---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "clipy"
what: "Add-on: screen recordings for agents"
kind: "mcp"
use: "computer use"
status: "chosen"
command: "clipy"
---
# clipy

clipy is "Model Context Protocol (MCP) server for Clipy" (its makers' words). In plain words: it gives an agent your screen recordings, transcripts, and selected images.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- You share a recording link to explain a task; the agent reads its transcript and images.
- An agent can find your newest recording or search recordings by topic.
- A live read returned the transcript and the screenshots.
- The server package stays pinned; agents do not upgrade it on their own.

**Install:** [Clipy MCP](https://clipy.online/mcp) · `npx @clipy/cli@latest login`

| Field | Value |
|---|---|
| Use | computer use · [all tools, by use](../CAPABILITIES.md) |
| Kind | mcp |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. `npx` fetches the server when a runtime starts it. |
| His yes | Signing in needs your yes. Starting or uploading a recording needs your yes. |
| Source | The tool: its setup page at `https://clipy.online/mcp`. Foxrun's use: the screen-recording tool choice. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Sign in | `npx @clipy/cli@latest login`; approve in the browser | — |
| Register | `claude mcp add clipy -- npx -y @clipy/mcp` (Codex: `codex mcp add clipy -- npx -y @clipy/mcp`) | — |
| Check | `claude mcp list` | a `clipy` line |

## Use

| To | Run |
|---|---|
| Find recordings | `search_recordings` |
| Read the transcript | `get_transcript` |
| Read selected images and text | `get_agent_context` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Sign-in | Clipy keeps it in `~/.config/clipy/config.json`; never copy it to a page. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `clipy.local.md` beside this page; that page never ships.
