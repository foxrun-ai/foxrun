---
type: "tool"
workspace: "system"
timestamp: "2026-10-26T13:30:00-04:00"
name: "remindctl"
what: "Add-on: Apple Reminders from the terminal"
kind: "cli"
use: "computer use"
status: "chosen"
command: "remindctl"
---
# remindctl

remindctl is a "Fast CLI for Apple Reminders" (its makers' words). In plain words: it lets you read, add, and finish reminders by typing commands. It runs on a Mac only.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents show today's or overdue reminders, then add or complete one you asked for.
- A delete needs your yes to the exact reminder.

**Install:** [remindctl](https://github.com/openclaw/remindctl) · `brew install steipete/tap/remindctl`

| Field | Value |
|---|---|
| Use | computer use · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. Homebrew puts the command on your path. Mac only. |
| His yes | Installing it and granting Reminders access need your yes. A delete needs your yes to the exact reminder. |
| Source | The tool: `https://github.com/openclaw/remindctl` (MIT). Foxrun's use: ruling g-mac-app-skills-ship-cli-addon. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | Add-on · the reminders skill ships; you install its command. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `brew install steipete/tap/remindctl` | — |
| Grant access | `remindctl authorize`, then allow Reminders access | — |
| Check | `remindctl status` | the Reminders access status |

## Use

| To | Run |
|---|---|
| Show today's reminders | `remindctl show today` |
| List your lists | `remindctl list` |
| Search reminders | `remindctl search <words>` |
| Add a reminder | `remindctl add "<title>" --list <list> --due <date>` |
| Complete a reminder | `remindctl complete <id>` |
| Read output as JSON | add `--json` |

## Skills that need it

No shipped skill names this tool yet. The `reminders` skill will (ruling g-mac-app-skills-ship-cli-addon).

## Settings

| What | Where |
|---|---|
| Tool command | `command -v remindctl` shows it. |
| Access | System Settings, Privacy & Security: Reminders. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `remindctl.local.md` beside this page; that page never ships.
