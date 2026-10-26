---
type: doc
workspace: system
timestamp: 2026-10-24T16:10:09-04:00
---
# Tools

One page for each tool: what it does, how to install it, and how to check it.
Pages listed in the product manifest, `../base/product-manifest.tsv`, ship with Foxrun. All other pages here are local to this home and never ship.
A `<name>.local.md` page holds this person's own notes for the shipped page `<name>.md`.

| Item | Purpose |
|---|---|
| `bin/` | Holds optional commands in the source folder; the default install excludes them: `browser-humanize.js`, `ig-read`, and `tweet-read`. Each command's page is in `cli/`. |
| `mcp/notion-mcp-source/` | Keeps the dated history of the local page `mcp/notion-mcp-source.md`. Local; never ships. |
| `mcp/tldraw-mcp/` | Keeps the dated history of the local page `mcp/tldraw-mcp.md`. Local; never ships. |
| `service/hermes-webui-service/` | Keeps the dated history of the local page `service/hermes-webui-service.md`. Local; never ships. |
| `<kind>/<page>/history/` | Each folder named like a page keeps that page's dated history. Local; never ships. |
| `cli/bin-inventory.md` | Lists local command names and their workspace use. Local; never ships. |
| `cli/index.md` | Lists the local command pages. Local; never ships. |
| `cli/instacart-pp-cli.md` | Documents the local Instacart command. Local; never ships. |
| `cli/tabladb-pp-cli.md` | Documents the local TablaDB command. Local; never ships. |
| `service/relay-bot.md` | Documents the local relay bot service. Local; never ships. |

## Optional source scripts

| File | Purpose |
|---|---|
| `bin/browser-humanize.js` | Supplies timing and movement helpers for browser automation. |
| `bin/ig-read` | Reads Instagram posts, comments, profiles, and transcripts through ScrapeCreators. |
| `bin/tweet-read` | Reads one tweet through the X API. |

## Tool pages

| Page | Purpose |
|---|---|
| `cli/bm-render.md` | Mermaid diagrams as SVG or terminal text. |
| `cli/ffmpeg.md` | Convert and inspect audio and video. |
| `cli/repomix.md` | Pack repository files for an agent to read. |
| `cli/remindctl.md` | Apple Reminders from the terminal. Mac only. |
| `cli/summarize.md` | Summarize a web page, video, audio, or file. |
| `plugin/codex-at-openai-codex.md` | Codex reviews and tasks from Claude Code. |
| `cli/runtime-session-search.md` | Find past agent sessions by words or native ID. |
| `cli/agent-secret-read.md` | Read one approved secret reference for a child process. |

## Guide selection

`config/tools.yaml` selects global, workspace, and off rows with `applies_to`.
Use `guide_only: true` for a global tool that belongs only in the system guide.
An off row leaves its historical page on disk. The guides do not change runtime access.
