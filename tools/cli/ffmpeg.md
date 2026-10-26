---
type: tool
workspace: system
timestamp: 2026-10-26T03:17:34-04:00
name: ffmpeg
what: "Add-on: convert and inspect audio and video"
kind: cli
use: creator & content
status: chosen
command: ffmpeg
---
# ffmpeg

In plain words: This tool converts audio and video files.

**Add-on.** You install this tool. Foxrun ships this page, not the tool.

FFmpeg converts audio and video files. Its companion ffprobe reports file details.

## Install

Use the [FFmpeg download guide](https://ffmpeg.org/download.html) for your platform.
On a Mac with Homebrew, run `brew install ffmpeg`.
Check with `ffmpeg -version` and `ffprobe -version`.

## Use

Convert a file with `ffmpeg -i in.mov out.mp4`.
Read file details with `ffprobe in.mov`.

| Field | Value |
|---|---|
| Use | creator & content · [all tools](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · availability is checked separately |
| Where | On your command path after setup; see Install. |
| His yes | Account setup, money, sends, and production changes need approval. |
| Source | existing FFmpeg tool page; the public download page could not be fetched |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | optional add-on |

## Skills that need it

See the generated capability guide for declared skill dependencies.

## Settings

| What | Where |
|---|---|
| Setup | Follow Install above; keep account credentials in your secret store. |
