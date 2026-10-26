---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "ig-read"
what: "Add-on: Instagram reader via ScrapeCreators"
kind: "cli"
use: "creator & content"
status: "chosen"
command: "ig-read"
---
# ig-read

ig-read is "Read Instagram post/reel/profile data via ScrapeCreators." (its makers' words). In plain words: it reads a public Instagram post, its comments, a profile, or a reel transcript.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Creator work uses it to read a profile, a post or reel, its comments, and a reel transcript.
- A search for a creator's public contact email starts with `ig-read profile`.
- It only reads public data.

**Install:** [Optional script setup](../../OPTIONAL-ADDONS.md#install-the-optional-scripts) · `ln -s ~/.foxrun/tools/bin/ig-read ~/bin/ig-read`

| Field | Value |
|---|---|
| Use | creator & content · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Optional script; you bring the key |
| Where | Copy `tools/bin/ig-read` from the Foxrun source folder into your system home. The default install excludes it. |
| His yes | The ScrapeCreators account and paid credit need your yes. |
| Source | The tool: the script's own usage line. Foxrun's use: creator reads. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

Set `FOXRUN_SOURCE` and `FOXRUN_HOME` as shown in [optional script setup](../../OPTIONAL-ADDONS.md#install-the-optional-scripts).

| Step | Command | It prints |
|---|---|---|
| Provider | Install the ScrapeCreators CLI at a version you checked, e.g. `npm install -g @scrapecreators/cli@<version>`. ig-read never downloads it. | — |
| Account | Make a ScrapeCreators account and get an API key | — |
| Key | Set `SCRAPECREATORS_API_KEY`, or set `SCRAPECREATORS_API_KEY_REF` to a secret-store reference and `AGENT_SECRET_READ` to the command that reads it | — |
| Copy | `install -m 755 "$FOXRUN_SOURCE/tools/bin/ig-read" "$FOXRUN_HOME/tools/bin/ig-read"` | — |
| Install | `ln -s ~/.foxrun/tools/bin/ig-read ~/bin/ig-read` (any folder on your path) | — |
| Check | `ig-read --help` | its usage line |

## Use

| To | Run |
|---|---|
| Read a post | `ig-read post <url>` |
| Read comments | `ig-read comments <url>` |
| Read a profile | `ig-read profile <handle>` |
| Read a reel transcript | `ig-read transcript <url>` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Key | Your secret store; never copy it to a page. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `ig-read.local.md` beside this page; that page never ships.
