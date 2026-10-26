---
type: module
workspace: system
name: capture
tier: base
built_by: ours
version: 0.1.0
requires: [wiki]
timestamp: 2026-10-18T22:44:28-04:00
status: active
tags: [capture]
---

# Capture

Capture reads source material and saves it as raw files, with one row for each file.
Reader adapters live in readers/. The table is in `blueprint.sql`.
`capture-read` reads one link and prints one JSON object.
Ordinary web links use the built-in HTML text reader when defuddle is absent.
Install optional defuddle for cleaner article extraction.
The optional `ig-read` and `browser-humanize.js` scripts are not required for ordinary links.
`capture-recover` finds an archived copy of a blocked page for `/read`. It never saves a capture.
`capture-write` saves that result: the raw file first, then the row, then one receipt.
It copies media only from the directory `capture-read` made for that result. It refuses links and outside paths.
`capture-read` refuses private and local network addresses. Its JSON never holds a URL credential.
`capture-check` checks every row against its raw file. The file wins.

Read [the system guide](../GUIDE.md) and [the global contract](../profile/AGENTS.md).
