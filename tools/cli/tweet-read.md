---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "tweet-read"
what: "Add-on: tweet reader by URL"
kind: "cli"
use: "creator & content"
status: "chosen"
command: "tweet-read"
---
# tweet-read

tweet-read is "Read a tweet by URL using X API v2" (its makers' words). In plain words: it reads one public post and shows its author, text, date, and response counts.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents read one public X post from its link, for example to save it.
- For a long post, agents check the full note text; `tweet-read` can show only the lead.
- It only reads.

**Install:** [Optional script setup](../../OPTIONAL-ADDONS.md#install-the-optional-scripts) · `ln -s ~/.foxrun/tools/bin/tweet-read ~/bin/tweet-read`

| Field | Value |
|---|---|
| Use | creator & content · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Optional script; you bring the token |
| Where | Copy `tools/bin/tweet-read` from the Foxrun source folder into your system home. The default install excludes it. |
| His yes | The X developer account and any paid plan need your yes. |
| Source | The tool: the script's own usage line. Foxrun's use: post reads. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

Set `FOXRUN_SOURCE` and `FOXRUN_HOME` as shown in [optional script setup](../../OPTIONAL-ADDONS.md#install-the-optional-scripts).

| Step | Command | It prints |
|---|---|---|
| Runtime | Bash, curl, and Python 3 | — |
| Account | Make an X developer app and get a bearer token | — |
| Key | Set `X_BEARER_TOKEN`, or set `X_BEARER_TOKEN_REF` to a secret-store reference and `AGENT_SECRET_READ` to the command that reads it | — |
| Copy | `install -m 755 "$FOXRUN_SOURCE/tools/bin/tweet-read" "$FOXRUN_HOME/tools/bin/tweet-read"` | — |
| Install | `ln -s ~/.foxrun/tools/bin/tweet-read ~/bin/tweet-read` (any folder on your path) | — |
| Check | `tweet-read <tweet_url>` | the post's author and text |

## Use

| To | Run |
|---|---|
| Read one public post | `tweet-read <tweet_url>` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Token | Your secret store; never copy it to a page. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `tweet-read.local.md` beside this page; that page never ships.
