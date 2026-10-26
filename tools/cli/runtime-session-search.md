---
type: tool
workspace: system
timestamp: 2026-10-26T03:17:34-04:00
name: runtime-session-search
what: "Ships: find past agent sessions by words or native ID"
kind: cli
use: sessions
status: chosen
command: runtime-session-search
---
# runtime-session-search

In plain words: This command finds a past agent conversation.

**Ships.** Foxrun owns this interface. This page ships with Foxrun.

This Foxrun command finds saved Claude, Codex, and Hermes conversations.
Search does not start, resume, or close a session.

## Install

Foxrun ships the command in `skills/runtime-session-search/bin/runtime-session-search` within the system home.
Use its full path if the command is absent from PATH.
Check that command with `--help`.

## Use

Run `runtime-session-search find "<words or id>"` to find a conversation.
Run `runtime-session-search read <exact-native-id>` to read its last reply.
Missing or ambiguous results stay explicit; never guess a session ID.

## Notes

See the [runtime-session-search skill](../../skills/runtime-session-search/SKILL.md) for options and supported stores.

| Field | Value |
|---|---|
| Use | sessions · [all tools](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · availability is checked separately |
| Where | The system home; see Install. |
| His yes | Account setup, money, sends, and production changes need approval. |
| Source | skills/runtime-session-search/bin/runtime-session-search and its skill page |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | Foxrun command |

## Skills that need it

See the generated capability guide for declared skill dependencies.

## Settings

| What | Where |
|---|---|
| Setup | Follow Install above; keep account credentials in your secret store. |
