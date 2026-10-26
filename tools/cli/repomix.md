---
type: tool
workspace: system
timestamp: 2026-10-26T03:17:34-04:00
name: repomix
what: "Add-on: pack repository files for an agent to read"
kind: cli
use: dev & repos
status: chosen
command: repomix
---
# repomix

In plain words: This tool puts code files into one document.

**Add-on.** You install this tool. Foxrun ships this page, not the tool.

Repomix packs repository contents into one text document.
Use it to inspect a repository before adopting its code.

## Install

Follow the [Repomix installation guide](https://repomix.com/guide/installation).
With Node.js and npm available, run `npm install -g repomix`.
Check with `repomix --version`.

## Use

Read a repository with `repomix --remote <repo-url> --stdout`.
A bare `repomix` command packs the current folder and writes a file.

| Field | Value |
|---|---|
| Use | dev & repos · [all tools](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · availability is checked separately |
| Where | On your command path after setup; see Install. |
| His yes | Account setup, money, sends, and production changes need approval. |
| Source | https://repomix.com/guide/installation; existing command page |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | optional add-on |

## Skills that need it

See the generated capability guide for declared skill dependencies.

## Settings

| What | Where |
|---|---|
| Setup | Follow Install above; keep account credentials in your secret store. |
