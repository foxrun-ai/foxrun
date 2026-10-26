---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "gogcli"
what: "Add-on: Google Workspace from the terminal"
kind: "cli"
use: "gmail"
status: "chosen"
command: "gog"
---
# gogcli

gogcli is "Google Workspace from the terminal" (its makers' words). In plain words: it lets a person search mail, read a calendar, and work with documents using typed commands.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents use it as their main email and calendar tool.
- Agents always name the account and use bounded read-only commands.
- A calendar invite goes out once, after a dry run and your exact yes, then a read-back.
- You sign in yourself; agents stop when the account does not match.

**Install:** [gogcli](https://gogcli.sh) · `brew install openclaw/tap/gogcli`

| Field | Value |
|---|---|
| Use | gmail · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. Homebrew puts the command on your path. |
| His yes | Signing in needs your yes. Every change needs your yes; a send needs your yes to the exact account, recipients, text, and attachments. |
| Source | The tool: `https://gogcli.sh`. Foxrun's use: the email tool choice. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `brew install openclaw/tap/gogcli` | — |
| Sign in | `gog auth add <your-email>` | the account you signed in with |
| Check | `gog --version` | the version number |

## Use

| To | Run |
|---|---|
| Show commands | `gog --help` |
| Find recent unread mail | `gog --account <your-email> --readonly gmail search 'is:unread newer_than:7d' --max 10` |
| See today's calendar | `gog --account <your-email> --readonly calendar events --today` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Tool command | `command -v gog` shows it. |
| Sign-in | gogcli keeps it in its own config folder; never copy it to a page. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `gogcli.local.md` beside this page; that page never ships.
