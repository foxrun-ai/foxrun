---
type: "tool"
workspace: "system"
timestamp: "2026-10-19T21:57:49-04:00"
name: "deepwiki-mcp"
what: "Add-on: questions about a GitHub project"
kind: "mcp"
use: "dev & repos"
status: "chosen"
command: "(MCP at https://mcp.deepwiki.com/mcp)"
---
# deepwiki-mcp

In plain words: DeepWiki makes documentation for public GitHub projects. Its MCP server lets an agent read that documentation and ask questions about a project's code.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Tool checks ask it how a public project works, beside a full read of the source.
- Before agents build a tool for a service, they read its wiki on sign-in, data, and structure.
- Help answers cite its pages as the source on how a project works.

**Install:** [DeepWiki](https://deepwiki.com) · `claude mcp add -s user -t http deepwiki https://mcp.deepwiki.com/mcp`

| Field | Value |
|---|---|
| Use | dev & repos · [all tools, by use](../CAPABILITIES.md) |
| Kind | mcp |
| Status | ☑️ chosen · Foxrun does not install it; you install it |
| Where | A hosted server at `https://mcp.deepwiki.com/mcp`. Nothing is on disk. |
| His yes | Adding the server needs your yes. |
| Source | The tool: `https://deepwiki.com`. Foxrun's use: the code question tool choice. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | installed · it is on Foxrun's list of installed tools. |

## Install

| Step | Command | It prints |
|---|---|---|
| Register | `claude mcp add -s user -t http deepwiki https://mcp.deepwiki.com/mcp` (Codex: add it to your Codex MCP settings) | — |
| Check | `claude mcp list` | a `deepwiki` line |

## Use

| To | Run |
|---|---|
| List a project's topics | `read_wiki_structure` with `owner/repo` |
| Read its docs | `read_wiki_contents` with `owner/repo` |
| Ask a question | `ask_wiki_question` with `owner/repo` and the question |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Server address | `https://mcp.deepwiki.com/mcp`, in each runtime's MCP settings. |

## Notes

- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `deepwiki-mcp.local.md` beside this page; that page never ships.
