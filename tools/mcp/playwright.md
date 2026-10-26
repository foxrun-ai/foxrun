---
type: "tool"
workspace: "system"
timestamp: "2026-10-20T00:37:50-04:00"
name: "playwright"
what: "Add-on: browser automation server"
kind: "mcp"
use: "browser control"
status: "chosen"
command: "playwright"
---
# playwright

playwright is "A Model Context Protocol (MCP) server that provides browser automation capabilities using Playwright" (its makers' words). In plain words: it lets an agent open web pages, click, type, and fill forms in a real browser.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents open a page, read its structure, then click and type to finish a task in the browser.
- gstack browse is built on Playwright. Its own setup installs Playwright's browser, so it does not need this server.
- It loads many tools into the agent's context, so turn it on only for browser work.

**Install:** [Playwright MCP](https://github.com/microsoft/playwright-mcp) · `claude mcp add playwright npx @playwright/mcp@latest`

| Field | Value |
|---|---|
| Use | browser control · [all tools, by use](../CAPABILITIES.md) |
| Kind | mcp |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you add it. `npx` fetches the server each time a runtime starts it. |
| His yes | Adding the server needs your yes. A form you submit with it needs your yes. |
| Source | The tool: `https://github.com/microsoft/playwright-mcp`. Foxrun's use: browser tasks; gstack's `BROWSER.md` and `setup`. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Get Node.js | `brew install node` (version 18 or newer) | — |
| Install | `claude mcp add playwright npx @playwright/mcp@latest` (Codex: `codex mcp add playwright npx "@playwright/mcp@latest"`) | — |
| Check | `claude mcp list` | a `playwright` line |

## Use

| To | Run |
|---|---|
| Open a page | `browser_navigate` with the address |
| Read the page | `browser_snapshot` |
| Click | `browser_click` |
| Type | `browser_type` |
| Take a screenshot | `browser_take_screenshot` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Server entry | Each runtime's MCP settings; Codex keeps it in `~/.codex/config.toml`. |
| Browser profile | `~/Library/Caches/ms-playwright/mcp-<channel>-<hash>`; `--user-data-dir` moves it. |
| Options | `--headless`, `--isolated`, or `--config <path>` after the server command. |

## Notes

- Sign-ins you make in its browser stay in its profile on this computer. `--isolated` keeps nothing.
- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `playwright.local.md` beside this page; that page never ships.
