---
type: "tool"
workspace: "system"
timestamp: "2026-10-26T13:30:00-04:00"
name: "summarize"
what: "Add-on: summarize a web page, video, audio, or file"
kind: "cli"
use: "data & docs"
status: "chosen"
command: "summarize"
---
# summarize

summarize is a "Multi-modal AI tool to extract and summarize content" (its makers' words). In plain words: give it a link, a YouTube video, a recording, or a file, and it returns a summary or the full text.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents summarize a page or a video before they read it in full.
- Agents pull a transcript or clean Markdown with `--extract`.
- It calls the model provider you set up. That provider's usage can cost money.

**Install:** [summarize](https://summarize.sh) · `brew install summarize`

| Field | Value |
|---|---|
| Use | data & docs · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. Homebrew puts the command on your path. |
| His yes | Installing it and setting up a model provider need your yes. |
| Source | The tool: `https://summarize.sh` (MIT). Foxrun's use: ruling g-mac-app-skills-ship-cli-addon. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | Add-on · the summarize skill ships; you install its command. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `brew install summarize` | — |
| Set up a model | `summarize --cli claude`, or set a provider key in your environment | — |
| Check | `summarize --version` | the version number |
| Check models | `summarize status` | the configured and usable model providers |

## Use

| To | Run |
|---|---|
| Summarize a page | `summarize "<url>"` |
| Get a page as Markdown | `summarize "<url>" --extract --format md` |
| Get a video transcript | `summarize "<youtube url>" --extract` |
| Summarize a local file | `summarize ./file.pdf` |
| Summarize the clipboard | `pbpaste \| summarize -` |
| Pick the length | add `--length short`, `medium`, or `long` |

## Skills that need it

No shipped skill names this tool yet. The `summarize` skill will (ruling g-mac-app-skills-ship-cli-addon).

## Settings

| What | Where |
|---|---|
| Tool command | `command -v summarize` shows it. |
| Model and speaker settings | `~/.summarize/config.json` |
| Provider keys | Environment variables such as `OPENAI_API_KEY`; read them through your secret reader, never by hand. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `summarize.local.md` beside this page; that page never ships.
