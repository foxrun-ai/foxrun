---
type: tool
workspace: system
timestamp: 2026-10-24T16:10:09-04:00
name: gh
what: "Add-on: GitHub command-line tool"
kind: cli
use: dev & repos
status: candidate
command: gh
---
# gh

gh is "GitHub command-line tool" (its makers' words). In plain words: it lets you read and manage GitHub projects by typing commands.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- The capture `github` reader uses `gh api` to read a public project's README, details, and files.
- Tool checks use it to read a project's live details before a pick.
- Ship and review flows use it to open, read, and merge pull requests.
- The reader needs one sign-in with `gh auth login`. It only reads.

**Install:** [gh install](https://cli.github.com/manual/installation) · `brew install gh`

| Field | Value |
|---|---|
| Use | dev & repos · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ⬜ candidate · Foxrun does not install it |
| Where | Not on disk until you install it. Homebrew puts the command on your path. |
| His yes | Installing it and signing in need your yes. Any write to GitHub needs your yes. |
| Source | The tool: its manual at `https://cli.github.com/manual`. Foxrun's use: `capture/install.json` `needs`, `capture/readers/github.py`. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | dependency · the capture `github` reader needs it. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `brew install gh` | — |
| Sign in | `gh auth login` | the account you signed in with |
| Check | `gh --version` | `gh version` and the number |

## Use

| To | Run |
|---|---|
| Read command help | `gh --help` |
| Check your sign-in | `gh auth status` |
| Read one project through capture | `capture/capture-read <github url>` |

## Skills that need it

These skills name this tool. They do not work when it is not set up.

| Skill | What it does |
|---|---|
| [`capture`](../../skillwright/skills/capture/SKILL.md) | Capture one link into raw: read the URL with the capture tool and save it as a raw file and a row in the workspace named … |

## Settings

| What | Where |
|---|---|
| Tool command | Where Homebrew puts it; `command -v gh` shows it. |
| Sign-in | gh keeps it in its own config folder; never copy it to a page. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
