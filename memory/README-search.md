---
type: doc
workspace: system
timestamp: 2026-10-24T16:10:09-04:00
---
# Search

The Keeper uses search tools. Search has no new folder or copy of its data.

| Question | Command | Definition |
|---|---|---|
| What does a word mean? | `python3 foxrun.py glossary <word>` | Dictionary rows and GLOSSARY.md |
| Where does a thing belong? | `python3 foxrun.py where <thing>` | Dictionary rows and RESOLVER.md |
| Where are matching notes? | `qmd search "words"` | [QMD tool](../tools/mcp/qmd-mcp-cli.md) |
| What shared knowledge matches? | `gbrain search "words"` | GBrain tool; no page ships |

The reviewed tool list is `config/tools.yaml`.
QMD and GBrain stay external tools under `tools/mcp/`.
QMD owns its index and models in `~/.cache/qmd/`.
GBrain owns its local home in `~/.gbrain/`.
Their schedules and services have tool pages under `tools/schedule/` and `tools/service/`.
This placement follows the owner decision: search is a tool the Keeper uses.
The proposal checks page and catalog links on a copy. It does not rebuild an index or test a connection.
Index migration and service activation need a separate switch plan.
