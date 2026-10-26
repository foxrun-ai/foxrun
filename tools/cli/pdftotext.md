---
type: tool
workspace: system
timestamp: 2026-10-24T16:10:09-04:00
name: pdftotext
what: "Add-on: PDF text reader from poppler"
kind: cli
use: data & docs
status: candidate
command: pdftotext
---
# pdftotext

pdftotext comes with poppler, a "PDF rendering library (based on the xpdf-3.0 code base)" (its makers' words). In plain words: it reads the text out of a PDF file.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- The capture `pdf` reader downloads a public PDF, then uses it to read the text.
- PDF work uses it to pull plain text, with `-layout` to keep columns.
- No Python PDF package is needed.

**Install:** [poppler](https://poppler.freedesktop.org/) · `brew install poppler`

| Field | Value |
|---|---|
| Use | data & docs · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ⬜ candidate · Foxrun does not install it |
| Where | Not on disk until you install poppler. Homebrew puts the command on your path. |
| His yes | Installing it needs your yes. |
| Source | The tool: the poppler site at `https://poppler.freedesktop.org/`. Foxrun's use: `capture/install.json` `needs`, `capture/readers/pdf.py`. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | dependency · the capture `pdf` reader needs it. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `brew install poppler` | — |
| Check | `pdftotext -v` | `pdftotext version` and the number |

## Use

| To | Run |
|---|---|
| Read command help | `pdftotext -h` |
| Print a PDF's text, keeping the layout | `pdftotext -layout <file.pdf> -` |
| Read one PDF link through capture | `capture/capture-read <pdf url>` |

## Skills that need it

These skills name this tool. They do not work when it is not set up.

| Skill | What it does |
|---|---|
| [`capture`](../../skillwright/skills/capture/SKILL.md) | Capture one link into raw: read the URL with the capture tool and save it as a raw file and a row in the workspace named … |

## Settings

| What | Where |
|---|---|
| Tool command | Where Homebrew puts it; `command -v pdftotext` shows it. |
| Saved settings | (not on disk) |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
