---
type: tool
workspace: system
timestamp: 2026-10-24T16:10:09-04:00
name: yt-dlp
what: "Add-on: command-line audio/video downloader"
kind: cli
use: creator & content
status: candidate
command: yt-dlp
---
# yt-dlp

yt-dlp is a "Feature-rich command-line audio/video downloader" (its makers' words). In plain words: it reads a video's details and captions from YouTube and many other sites.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- The capture `youtube` reader uses it to read a video's details and its transcript.
- More than 300 saved video pages came from it.
- The reader never downloads the video, and it uses no login and no browser cookies.

**Install:** [yt-dlp install](https://github.com/yt-dlp/yt-dlp#installation) · `brew install yt-dlp`

| Field | Value |
|---|---|
| Use | creator & content · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ⬜ candidate · Foxrun does not install it |
| Where | Not on disk until you install it. Homebrew puts the command on your path. |
| His yes | Installing it needs your yes. |
| Source | The tool: its README at `https://github.com/yt-dlp/yt-dlp`. Foxrun's use: `capture/install.json` `needs`, `capture/readers/youtube.py`. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | dependency · the capture `youtube` reader needs it. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `brew install yt-dlp` | — |
| Check | `yt-dlp --version` | the version, as a date |

## Use

| To | Run |
|---|---|
| Read command help | `yt-dlp --help` |
| Read a video's details without download | `yt-dlp --ignore-config --skip-download --dump-json <url>` |
| Read one video through capture | `capture/capture-read <youtube url>` |

## Skills that need it

These skills name this tool. They do not work when it is not set up.

| Skill | What it does |
|---|---|
| [`capture`](../../skillwright/skills/capture/SKILL.md) | Capture one link into raw: read the URL with the capture tool and save it as a raw file and a row in the workspace named … |

## Settings

| What | Where |
|---|---|
| Tool command | Where Homebrew puts it; `command -v yt-dlp` shows it. |
| Saved settings | The capture reader runs it with `--ignore-config`, so no saved settings apply. |

## Notes

- yt-dlp can also read TikTok links. No capture reader uses it for TikTok yet.
- This page is a product page. To change it, copy it under a new name; the copy is yours.
