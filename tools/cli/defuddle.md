---
type: tool
workspace: system
timestamp: 2026-10-24T16:10:09-04:00
name: defuddle
what: "Add-on: web page to article text"
kind: cli
use: data & docs
status: candidate
command: defuddle
---
# defuddle

defuddle gets "the main content of any page as Markdown" (its makers' words). In plain words: it takes a saved web page and keeps only the article, with no menus or ads.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- The capture `web` reader uses it to turn a saved web page into clean article text.
- Without it, ordinary web links use the built-in HTML text reader. Install defuddle for cleaner article extraction.

**Install:** [defuddle install](https://github.com/kepano/defuddle#cli) · `npm install -g defuddle`

| Field | Value |
|---|---|
| Use | data & docs · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ⬜ candidate · Foxrun does not install it |
| Where | Not on disk until you install it. `npm` puts the command on your path. |
| His yes | Installing it needs your yes. |
| Source | The tool: its README at `https://github.com/kepano/defuddle`. Foxrun's use: `capture/install.json` `needs`. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | optional add-on · improves article extraction for the capture `web` reader. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `npm install -g defuddle` | — |
| Check | `command -v defuddle` | the path of the command |

## Use

| To | Run |
|---|---|
| Turn saved HTML into Markdown and details | `defuddle parse --markdown --json < page.html` |
| Read one web link through capture | `capture/capture-read <url>` |

## Skills that need it

Capture can use this tool. Ordinary web capture also works without it.

| Skill | What it does |
|---|---|
| [`capture`](../../skillwright/skills/capture/SKILL.md) | Capture one link into raw: read the URL with the capture tool and save it as a raw file and a row in the workspace named … |

## Settings

| What | Where |
|---|---|
| Tool command | Where `npm install -g` puts it; `command -v defuddle` shows it. |
| Saved settings | (not on disk); the capture reader passes all options on the command line. |

## Notes

- Node.js and `npm` must be on your Mac first.
- This page is a product page. To change it, copy it under a new name; the copy is yours.
