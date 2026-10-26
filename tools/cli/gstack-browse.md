---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "gstack-browse"
what: "Add-on: fast headless browser (gstack)"
kind: "cli"
use: "browser control"
status: "chosen"
command: "browse"
---
# gstack-browse

In plain words: it is a fast browser with no window that an agent drives to test a site and take screenshots.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents test a site, read a page, and take screenshots with it.
- Site checks and design reviews use it to test a web app in a real browser.
- It comes packaged inside the gstack `browse` skill.

**Install:** [gstack](https://github.com/garrytan/gstack) · `git clone https://github.com/garrytan/gstack ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup`

| Field | Value |
|---|---|
| Use | browser control · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. gstack puts the `browse` binary inside its own folder. |
| His yes | Installing it needs your yes. A form you submit with it needs your yes. |
| Source | The tool: `https://github.com/garrytan/gstack`. Foxrun's use: the `browse` skill. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Get Bun | `brew install oven-sh/bun/bun` | — |
| Install | `git clone https://github.com/garrytan/gstack ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup` | setup steps |
| Check | `ls ~/.claude/skills/gstack/browse` | the browse folder |

## Use

| To | Run |
|---|---|
| Open a page | `$B goto <url>` |
| Screenshot | `$B screenshot` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Binary | Inside the gstack folder; the `browse` skill names it as `$B`. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `gstack-browse.local.md` beside this page; that page never ships.
