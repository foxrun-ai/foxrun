---
type: tool
workspace: system
timestamp: 2026-10-24T16:10:09-04:00
name: instaloader
what: "Add-on: Instagram post reader"
kind: cli
use: creator & content
status: candidate
command: instaloader
---
# instaloader

instaloader downloads "pictures (or videos) along with their captions and other metadata from Instagram" (its makers' words). In plain words: it reads a public Instagram post's caption and media.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- The capture `instagram` reader uses it to read a public post and its media.
- Without it, an Instagram link gives the error `Missing free tool: instaloader.` Other readers still work.

**Install:** [instaloader install](https://instaloader.github.io/installation.html) · `uv tool install instaloader`

| Field | Value |
|---|---|
| Use | creator & content · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ⬜ candidate · Foxrun does not install it |
| Where | Not on disk until you install it. `uv` puts the command on your path. |
| His yes | Installing it needs your yes. Signing in to Instagram needs your yes. |
| Source | The tool: its site at `https://instaloader.github.io/`. Foxrun's use: `capture/install.json` `needs`, `capture/readers/instagram.py`. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | dependency · the capture `instagram` reader needs it. |

## Install

| Step | Command | It prints |
|---|---|---|
| Install | `uv tool install instaloader` | — |
| Check | `instaloader --version` | the version number |

## Use

| To | Run |
|---|---|
| Read command help | `instaloader --help` |
| Read one public post through capture | `capture/capture-read <instagram post url>` |

## Skills that need it

These skills name this tool. They do not work when it is not set up.

| Skill | What it does |
|---|---|
| [`capture`](../../skillwright/skills/capture/SKILL.md) | Capture one link into raw: read the URL with the capture tool and save it as a raw file and a row in the workspace named … |

## Settings

| What | Where |
|---|---|
| Tool command | Where `uv tool install` puts it; `command -v instaloader` shows it. |
| Sign-in | (not on disk); the capture reader uses no login. |

## Notes

- The capture reader waits between requests and stops after repeated failures.
- `uv` must be on your Mac first.
- This page is a product page. To change it, copy it under a new name; the copy is yours.
