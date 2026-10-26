---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "jev"
what: "Add-on: TypeSafe Jev judgment model via OpenRouter"
kind: "service"
use: "data & docs"
status: "chosen"
command: "node scripts/jev.mjs (in the jev skill)"
---
# jev

In plain words: Jev is a hosted AI model from TypeSafe that answers a typed question (a choice, a score, yes or no) with probabilities, not prose. Calls go through OpenRouter.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- It runs only when you or another skill names Jev.
- Large jobs run as a batch with a progress file, and a stopped batch resumes.
- Run records go in `data.db` in the system home.
- Its key is read from your secret store, never typed into a page.

**Install:** [TypeSafe docs](https://docs.typesafe.ai/llms.txt) · `node scripts/jev.mjs request.json`

| Field | Value |
|---|---|
| Use | data & docs · [all tools, by use](../CAPABILITIES.md) |
| Kind | service |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | A hosted service. Nothing runs on this computer except the skill script. |
| His yes | The account and paid credit need your yes. Each run spends credit. |
| Source | The tool: `https://docs.typesafe.ai/llms.txt`. Foxrun's use: the `jev` skill. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Account | Make an OpenRouter account at `https://openrouter.ai` and add credit | — |
| Key | Store the OpenRouter key in your secret store | — |
| Check | In the `jev` skill folder: `node scripts/jev.mjs request.json` | one JSON judgment |

## Use

| To | Run |
|---|---|
| One judgment | `node scripts/jev.mjs request.json` |
| A batch | `node scripts/jev.mjs --progress <run>/progress.jsonl --concurrency 2 batch.json` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Key | Your secret store; never copy it to a page. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `jev.local.md` beside this page; that page never ships.
