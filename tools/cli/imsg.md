---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "imsg"
what: "Add-on: iMessage / SMS from the terminal"
kind: "cli"
use: "comms"
status: "chosen"
command: "imsg"
---
# imsg

imsg is "Send and read iMessage / SMS from the terminal" (its makers' words). In plain words: it lets you read or send text messages by typing commands.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents list chats, then read one thread with its history and attachments before they draft a reply.
- Each send needs your yes to the exact text and destination.

**Install:** [imsg](https://github.com/openclaw/imsg) · `brew install steipete/tap/imsg`

| Field | Value |
|---|---|
| Use | comms · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. Homebrew puts the command on your path. |
| His yes | Installing it and granting Full Disk Access need your yes. Each send needs your yes to the exact text and destination. |
| Source | The tool: `https://github.com/openclaw/imsg`. Foxrun's use: the `imessage` skill. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `brew install steipete/tap/imsg` | — |
| Grant access | Give your terminal Full Disk Access in System Settings, Privacy & Security | — |
| Check | `imsg --version` | the version number |

## Use

| To | Run |
|---|---|
| List chats | `imsg chats` |
| Read a chat | `imsg history` |
| Watch new messages | `imsg watch` |
| Send an approved message | `imsg send` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Tool command | `command -v imsg` shows it. |
| Access | System Settings, Privacy & Security: Full Disk Access. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `imsg.local.md` beside this page; that page never ships.
