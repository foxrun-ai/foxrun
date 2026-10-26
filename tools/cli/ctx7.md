---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "ctx7"
what: "Add-on: Context7 docs lookup command"
kind: "cli"
use: "dev & repos"
status: "chosen"
command: "ctx7"
---
# ctx7

ctx7 is "Context7 CLI - Fetch documentation context and configure Context7" (its makers' words). In plain words: it fetches current library docs so an agent does not guess an API.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents look up a library's current docs with `ctx7 library` and `ctx7 docs` before they write code.
- Tool checks read `ctx7 docs` for the interfaces in play, beside a full read of the source.
- Agents run the installed command, never a bare `npx` download.

**Install:** [Context7](https://github.com/upstash/context7) · `npm install -g ctx7`

| Field | Value |
|---|---|
| Use | dev & repos · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. npm puts the command on your path. |
| His yes | Installing it and signing in need your yes. |
| Source | The tool: `https://github.com/upstash/context7`. Foxrun's use: the docs lookup tool choice. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `npm install -g ctx7` | — |
| Check | `ctx7 --version` | the version number |

## Use

| To | Run |
|---|---|
| Find a library ID | `ctx7 library "<name>" "<question>"` |
| Read its docs | `ctx7 docs <libraryId> "<question>"` |
| Show the sign-in | `ctx7 whoami` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Tool command | `command -v ctx7` shows it. |
| Sign-in | ctx7 keeps it in its own config folder; never copy it to a page. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `ctx7.local.md` beside this page; that page never ships.
