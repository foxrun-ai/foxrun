---
type: "tool"
workspace: "system"
timestamp: 2026-10-24T16:10:09-04:00
name: "herdr"
what: "Add-on: terminal multiplexer for AI agents"
kind: "cli"
use: "sessions"
status: "chosen"
command: "herdr"
---
# herdr

herdr is "agent multiplexer that lives in your terminal" (its makers' words). In plain words: it splits a terminal window into panes and keeps each agent running after you leave.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents start, steer, find, resume, and close hosted agent sessions with it.
- Long back-and-forth work between two agents runs in a pane it hosts.
- A close shows a preview first, then needs your numbered pick and `y`.

**Install:** [herdr](https://herdr.dev) · `brew install herdr`

| Field | Value |
|---|---|
| Use | sessions · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. Homebrew puts the command on your path. |
| His yes | Installing it needs your yes. Closing a session needs your numbered pick and `y`. |
| Source | The tool: `https://herdr.dev`. Foxrun's use: the `herdr` skill. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `brew install herdr` | — |
| Check | `herdr --version` | the version number |

## Use

| To | Run |
|---|---|
| Start or attach | `herdr` |
| See status | `herdr status` |
| Attach from another computer | `herdr --remote <ssh-target>` |

## Skills that need it

These skills name this tool. They do not work when it is not set up.

| Skill | What it does |
|---|---|
| [`orchestrate`](../../skillwright/skills/orchestrate/SKILL.md) | Route work between Claude, Codex, and Hermes: say where you are, what you want (quick hit, second opinion, review, fix, … |
| [`runtime-session-search`](../../skills/runtime-session-search/SKILL.md) | Find a past agent session by words or id in Claude, Codex, or Hermes (every profile), read its final reply, and return t … |

## Settings

| What | Where |
|---|---|
| Tool command | `command -v herdr` shows it. |
| Tool settings | `~/.config/herdr/config.toml` |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `herdr.local.md` beside this page; that page never ships.
