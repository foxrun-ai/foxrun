---
type: tool
workspace: system
timestamp: 2026-10-26T03:17:34-04:00
name: bm-render
what: "Add-on: Mermaid diagrams as SVG or terminal text"
kind: cli
use: data & docs
status: chosen
command: bm-render
---
# bm-render

In plain words: This command turns diagram text into a picture.

**Add-on.** You install this tool. Foxrun ships this page, not the tool.

bm-render is a command wrapper for the beautiful-mermaid library.
The public library has setup instructions; a public installer for this exact wrapper is not established.

## Install

Install the library with `npm install beautiful-mermaid` in a folder you choose.
This installs the library, not the `bm-render` command. Obtain and review a compatible wrapper separately.
Check an existing wrapper with `bm-render --help`.

## Use

`bm-render --format svg --input diagram.mmd` writes SVG to standard output.
`bm-render --format unicode --input diagram.mmd` writes terminal text.

## Notes

[beautiful-mermaid](https://github.com/lukilabs/beautiful-mermaid) documents the library and its API.
The command examples describe the existing wrapper; they do not promise an upstream CLI.

| Field | Value |
|---|---|
| Use | data & docs · [all tools](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · availability is checked separately |
| Where | On your command path after setup; see Install. |
| His yes | Account setup, money, sends, and production changes need approval. |
| Source | https://github.com/lukilabs/beautiful-mermaid; existing command help |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | optional add-on |

## Skills that need it

See the generated capability guide for declared skill dependencies.

## Settings

| What | Where |
|---|---|
| Setup | Follow Install above; keep account credentials in your secret store. |
