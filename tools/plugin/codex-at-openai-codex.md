---
type: tool
workspace: system
timestamp: 2026-10-26T03:17:34-04:00
name: codex-at-openai-codex
what: "Add-on: Codex reviews and tasks from Claude Code"
kind: plugin
use: dev & repos
status: chosen
command: codex:review
---
# codex-at-openai-codex

In plain words: This plugin asks Codex to review code or complete a task.

**Add-on.** You install this tool. Foxrun ships this page, not the tool.

The Codex plugin lets Claude Code request a Codex review or assign a task.

## Install

Follow the [OpenAI plugin guide](https://github.com/openai/codex-plugin-cc).
In Claude Code, run `/plugin marketplace add openai/codex-plugin-cc`, then `/plugin install codex@openai-codex`.
Run `/reload-plugins`, then `/codex:setup` to check the setup.
Use your own Codex access. Usage follows your account limits or API charges.

## Use

`/codex:review` requests a code review.
`/codex:rescue <task>` assigns work to Codex.

| Field | Value |
|---|---|
| Use | dev & repos · [all tools](../CAPABILITIES.md) |
| Kind | plugin |
| Status | ☑️ chosen · availability is checked separately |
| Where | On your command path after setup; see Install. |
| His yes | Account setup, money, sends, and production changes need approval. |
| Source | https://github.com/openai/codex-plugin-cc |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | optional add-on |

## Skills that need it

See the generated capability guide for declared skill dependencies.

## Settings

| What | Where |
|---|---|
| Setup | Follow Install above; keep account credentials in your secret store. |
