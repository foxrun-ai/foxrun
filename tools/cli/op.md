---
type: "tool"
workspace: "system"
timestamp: "2026-10-20T00:37:50-04:00"
name: "op"
what: "Add-on: 1Password command line"
kind: "cli"
use: "secrets"
status: "chosen"
command: "op"
---
# op

op is "1Password CLI brings 1Password to your terminal." (its makers' words). In plain words: it reads passwords and keys from your 1Password account when a script needs one.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents read one secret at a time through a secret reader command. That reader calls `op`.
- Startup paths, scripts, and runs with no one watching never call `op read` themselves.
- Scripts such as ig-read and tweet-read take a secret's address and the reader command, never the secret.
- Pages and replies never show a secret. They name only where it lives.

**Install:** [1Password CLI](https://developer.1password.com/docs/cli/get-started/) · `brew install --cask 1password-cli`

| Field | Value |
|---|---|
| Use | secrets · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. Homebrew puts the command on your path. |
| His yes | Installing it and linking it to the 1Password app need your yes. A change to an item needs your yes. |
| Source | The tool: `op --help` and `https://developer.1password.com/docs/cli`. Foxrun's use: the secret reader, ig-read, and tweet-read. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `brew install --cask 1password-cli` | — |
| Link the app | 1Password app, Settings, Developer: turn on the CLI link | — |
| Check | `op --version` | the version number |

## Use

| To | Run |
|---|---|
| Sign in | `op signin` |
| See who is signed in | `op whoami` |
| Read one secret | `op read "op://<vault>/<item>/<field>"` |
| Run a command with secrets | `op run --env-file=<file> -- <command>` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Tool command | `command -v op` shows it. |
| Tool settings | `~/.config/op/` |
| Secrets | Your 1Password account. A page names a secret's place, never its value. |

## Notes

- `op item get --format json` prints hidden fields. Foxrun never uses it.
- 1Password needs a paid plan. The CLI itself costs nothing more.
- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `op.local.md` beside this page; that page never ships.
