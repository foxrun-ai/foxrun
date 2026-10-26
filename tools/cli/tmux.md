---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "tmux"
what: "Add-on: terminal multiplexer"
kind: "cli"
use: "sessions"
status: "chosen"
command: "tmux"
---
# tmux

In plain words: tmux keeps terminal sessions running after you disconnect, so you can come back to them from another computer or a phone.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Interactive commands that need a terminal run inside tmux.
- Remote shells use it to keep work alive when the connection drops.
- The remote access check confirms a tmux server is up before you leave the computer.
- A Keychain read inside tmux works only from a logged-in desktop session.

**Install:** [tmux](https://github.com/tmux/tmux) · `brew install tmux`

| Field | Value |
|---|---|
| Use | sessions · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. Homebrew puts the command on your path. |
| His yes | Installing it needs your yes. |
| Source | The tool: `https://github.com/tmux/tmux`. Foxrun's use: interactive and remote sessions. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `brew install tmux` | — |
| Check | `tmux -V` | the version number |

## Use

| To | Run |
|---|---|
| List sessions | `tmux ls` |
| Start a named one | `tmux new -s <name>` |
| Attach to one | `tmux attach -t <name>` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Tool command | `command -v tmux` shows it. |
| Tool settings | `~/.tmux.conf` |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `tmux.local.md` beside this page; that page never ships.
