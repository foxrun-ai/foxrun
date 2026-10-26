---
type: resolver
workspace: system
timestamp: 2026-10-19T20:25:11-04:00
---
# RESOLVER.md

## What It Settles

Choose the source, home, and writer before changing a fact.
System rules live in this system home. Business facts belong to their named workspace.
Read the workspace's Who Owns What section for local tables, files, and writers.
The global contract, system-home contract, and workspace AGENTS.md take precedence over this resolver.

## One Writer

Each fact has one writer. Use its module command or named file author.
A mirror is a dated copy. Change the outside source through its authorized writer.
Change rows before rebuilding a generated page. Never edit a generated page by hand.
Read config/gates.md before a gated change. Approval stays tied to its exact version.
The outside system wins over its mirror. A source row wins over a page that repeats it.
An empty table does not replace a file that still owns the fact.
A contract wins over memory. Keep disputed claims with their source and time.
Stop actions that depend on a disputed fact. New evidence does not expand an approval.

## Look It Up

Run the workspace start command. Read its AGENTS.md and local RESOLVER.md.
Use foxrun.py where and foxrun.py glossary for a named thing or word.
Check the database table and module command before changing a fact.
An absent table is not permission to create it. Report an unknown owner and continue independent work.

### Where Things Live

Paths below start in the system home or the portfolio, as the Home column says.

| Thing | Home | Path | Writer or owner |
|---|---|---|---|
| Shared rules | System | `profile/AGENTS.md` | Approved contract author |
| Table definitions | System | `SCHEMA.md` | Database builder |
| Setup words | System | `GLOSSARY.md` | Source rows |
| Shared settings | System | `config/` | Architect |
| Local facts and tasks | System | `data.db` | Owning module |
| Shared agent definitions | System | `agents/` | Chief of Staff |
| Generated first agent | System | `agents/generated/` | Chief of Staff |
| Skills in day one | System | `skillwright/skills/` | Skillwright |
| Run trails | System | `runs/` | Chief of Staff |
| Heavy outside material | System | `raw/` | Capture |
| Backups | System | `backups/` | Keeper |
| Workspaces | Portfolio | `<workspace>/` | Local contract |
| Workspace agent files | Portfolio | `<workspace>/team/` | Local assignment |
| Workspace words | Portfolio | `<workspace>/GLOSSARY.md` | Local source rows |
| Workspace settings | Portfolio | `<workspace>/config/` | Local contract |
| Live business pages | Portfolio | `<workspace>/ops/` | Source rows and page builder |
| Workspace code | Portfolio | `<workspace>/src/` | Local assignment |
| Living notes | Portfolio | `<workspace>/notes/` | Note author |
| Build specs | Portfolio | `<workspace>/specs/` | Spec author |
| Outside material | Portfolio | `<workspace>/raw/` | Capture |
| Compiled knowledge | Portfolio | `<workspace>/wiki/` | Keeper |
| Run reports | Portfolio | `<workspace>/history/runs/` | Run author |
| Finished work | Portfolio | `<workspace>/history/outputs/` | Work author |
| Default capture and library | Portfolio | `atlas/` | Capture and Keeper |
| Workspace list | Portfolio | `index.md` | Installer template |
| Library list | Portfolio | `atlas/LIBRARY.md` | Wiki topic lists |

### Writer restrictions

A lead captures the person's exact words in a ruling row. A worker never does.
Unsolicited row changes are exact proposals. Requested changes need no extra proposal.
A defined skill does its authorized job. None of these rules expands an approval.


### Which source wins

| These two differ | This one wins |
|---|---|
| An outside system and its mirror | The outside system |
| A row and a file that repeats it | The row |
| Two pages that repeat a fact from a row | The row |
| An empty table and a file that holds the fact | The file |
| A wiki page and the row or file that owns the fact | The owner of the fact |
| A contract and your memory | The contract |

- Then correct the source that lost, through its writer above.
- If you cannot correct it, report the conflict on the task.
- A ruling against an older page: the precedence list in `~/.foxrun/profile/AGENTS.md` decides.
- No line decides it: write both sources on the task, and ask the person one question.
- New evidence never changes an approval. When to ask again: `~/.foxrun/profile/AGENTS.md`, section `When To Act, When To Ask`.


### No line for it

- For the lookup steps, follow `~/.foxrun/profile/AGENTS.md`, section `Memory`.
- A fact that every workspace shares: open `~/.foxrun/RESOLVER.md`.
- Still no line: the thing has no home yet. `~/.foxrun/profile/AGENTS.md`, section `Where Things Go`, has the line for it.
- A table named here is not in the database: say so, and do not make it.
- Never guess a place. Say which fact has no line, then continue with the rest of the ask.
- For the fields of one table, run `python3 ~/.foxrun/foxrun.py where <thing>`.


### File behavior

- `<workspace>/notes/`: edit living notes in place.
- `<workspace>/specs/`: edit build requirements until the work is accepted.
- `<workspace>/history/`: add dated receipts and preserve completed records.
- `<workspace>/raw/`: preserve captured source bytes; never rewrite them or load them on wake.
- Lessons: write lesson rows with the owning module command.

[Resolver definition](base/README.md) defines this contract.
[Workspace definition](base/README-workspace-pages.md) defines source boundaries and generated copies.

## Who Owns What

Generated from `owns:` in `agents/*.md`.

| Part | Owner |
|---|---|
| `.gitignore` | architect |
| `AGENTS.md` | architect |
| `CHANGELOG.md` | architect |
| `CLAUDE.md` | architect |
| `DOCUMENTATION.md` | architect |
| `GLOSSARY.md` | keeper |
| `GUIDE.md` | architect |
| `INSTALL.md` | architect |
| `OPTIONAL-ADDONS.md` | architect |
| `README.md` | architect |
| `RESOLVER.md` | architect |
| `SCHEMA.md` | keeper |
| `STATE.md` | keeper |
| `VERSION` | architect |
| `agents/` | chief-of-staff |
| `apps/` | toolsmith |
| `archive/` | keeper |
| `backups/` | keeper |
| `base/` | architect |
| `base/README-contract-lint.md` | keeper |
| `base/contract-lint-rules.json` | keeper |
| `base/contract_lint.py` | keeper |
| `base/lint.py` | keeper |
| `capture/` | capture |
| `config/` | architect |
| `cron/` | toolsmith |
| `data.db` | architect |
| `decisions/` | architect |
| `evals/` | skillwright |
| `events/` | keeper |
| `foxrun.py` | architect |
| `health.json` | keeper |
| `hooks/` | toolsmith |
| `install.py` | architect |
| `made-at-install.tsv` | architect |
| `memory/` | keeper |
| `modules/` | toolsmith |
| `product-manifest.tsv` | architect |
| `profile/` | architect |
| `raw/` | capture |
| `runs/` | chief-of-staff |
| `skills/` | skillwright |
| `skillwright/` | skillwright |
| `state/` | keeper |
| `tests/` | architect |
| `tools/` | toolsmith |
| `wiki/` | keeper |
| `work/` | chief-of-staff |
| `workspaces/` | keeper |
