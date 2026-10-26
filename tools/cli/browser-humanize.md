---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "browser-humanize"
what: "Add-on: human-like timing for browser automation"
kind: "cli"
use: "browser control"
status: "chosen"
command: "browser-humanize.js"
---
# browser-humanize

browser-humanize is "Anti-detection behavioral helpers for browser automation." (its makers' words). In plain words: it adds human-like pauses, typing speed, window sizes, and mouse paths, so a site does not block an automated browser.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Any scraping or automation flow that must look like a person loads it first.
- It adds random pauses, window size changes, and natural mouse paths to a browser flow.
- In a shopping cart flow it stops before an order, a payment, or an address change.

**Install:** [Optional script setup](../../OPTIONAL-ADDONS.md#install-the-optional-scripts) · `brew install node`

| Field | Value |
|---|---|
| Use | browser control · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Optional script; you add Node.js |
| Where | Copy `tools/bin/browser-humanize.js` from the Foxrun source folder into your system home. The default install excludes it. |
| His yes | Installing it needs your yes. An order, a payment, or an address change needs your yes. |
| Source | The tool: the script's own header and `--test` self-test. Foxrun's use: the browser automation tool choice. |
| Owner | product · Foxrun ships this page. You install this optional copy. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

Set `FOXRUN_SOURCE` and `FOXRUN_HOME` as shown in [optional script setup](../../OPTIONAL-ADDONS.md#install-the-optional-scripts).

| Step | Command | It prints |
|---|---|---|
| Get Node.js | `brew install node` | — |
| Install | `install -m 644 "$FOXRUN_SOURCE/tools/bin/browser-humanize.js" "$FOXRUN_HOME/tools/bin/browser-humanize.js"` | — |
| Check | `node ~/.foxrun/tools/bin/browser-humanize.js --test` | its self-test |

## Use

| To | Run |
|---|---|
| Load it in a script | `const h = require(process.env.HOME + '/.foxrun/tools/bin/browser-humanize.js')` |
| Pause like a person | `await h.humanDelay()` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Script | `tools/bin/browser-humanize.js` in the system home. You install this optional copy. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `browser-humanize.local.md` beside this page; that page never ships.
