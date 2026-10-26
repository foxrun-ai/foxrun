---
type: tool
workspace: system
timestamp: 2026-10-26T03:17:34-04:00
name: agent-secret-read
what: "Ships: read one approved secret reference for a child process"
kind: cli
use: secrets
status: chosen
command: agent-secret-read
---
# agent-secret-read

In plain words: This command supplies one saved secret to a program.

**Ships.** Foxrun owns this interface. This page ships with Foxrun.

The secret reader supplies one stored secret to a process that needs it.
Keep secret values out of pages, logs, tool output, and replies.

## Install

This page documents Foxrun's own secret-reader interface.
The current product manifest does not include the executable; setup remains subject to the privacy and security review.
Use `command -v agent-secret-read` to check availability without reading a secret.
A missing command is a setup gap. Do not replace it with a raw secret-store read.

## Use

The interface accepts one reference: `agent-secret-read 'op://<vault>/<item>/<field>'`.
Pass its output directly to the authorized child process. Never print the output for inspection.
Use your own secret store and access configuration.

| Field | Value |
|---|---|
| Use | secrets · [all tools](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · availability is checked separately |
| Where | On your command path after setup; see Install. |
| His yes | Account setup, money, sends, and production changes need approval. |
| Source | existing secret-reader documentation; executable shipment is unverified |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | Foxrun command |

## Skills that need it

See the generated capability guide for declared skill dependencies.

## Settings

| What | Where |
|---|---|
| Setup | Follow Install above; keep account credentials in your secret store. |
