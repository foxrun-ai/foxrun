---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "firecrawl"
what: "Add-on: web page and site reader"
kind: "cli"
use: "data & docs"
status: "chosen"
command: "firecrawl"
---
# firecrawl

firecrawl is "Command-line interface for Firecrawl. Scrape, crawl, and extract data from any website" (its makers' words). In plain words: it turns a web page or a whole site into clean text an agent can read.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents use it to pull docs and changelog pages when they check a tool.
- Free reads go first (plain `curl`, `r.jina.ai`); Firecrawl runs only when they fail, because credits are limited.
- Its key goes in an environment variable only, never in command text or output.

**Install:** [Firecrawl CLI](https://github.com/firecrawl/cli) · `npm install -g firecrawl-cli`

| Field | Value |
|---|---|
| Use | data & docs · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. npm puts the command on your path. |
| His yes | Installing it and adding an API key need your yes. Paid credits need your yes. |
| Source | The tool: `https://github.com/firecrawl/cli`. Foxrun's use: the web reader tool choice. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `npm install -g firecrawl-cli` | — |
| Sign in | `firecrawl login` | the account you signed in with |
| Check | `firecrawl --version` | the version number |

## Use

| To | Run |
|---|---|
| Read one page | `firecrawl scrape <url>` |
| Crawl a site | `firecrawl crawl <url>` |
| List a site's pages | `firecrawl map <url>` |
| Search the web | `firecrawl search "<query>"` |
| Show credits left | `firecrawl --status` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Tool command | `command -v firecrawl` shows it. |
| API key | Keep it in your secret store; never copy it to a page. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `firecrawl.local.md` beside this page; that page never ships.
