---
type: doc
workspace: system
timestamp: 2026-10-23T20:04:42-04:00
---
# Your first ten minutes with Foxrun

Foxrun keeps your work and gives an agent the right starting information.
It keeps the program in `~/.foxrun` and your work in `~/foxrun`.
Start with [INSTALL.md](INSTALL.md) if you have not installed it.
This guide uses the example name `avery` and workspace `cedar-shop`.

## Your two folders

The system folder holds shared rules, commands, and settings.
The portfolio folder holds workspaces and Atlas, your shared library.
A workspace holds one business or body of work.
The table shows selected places from the current install rows.
Replace `<workspace>` with your workspace name.
Your install can use different folders.

| Installed place | What it holds |
|---|---|
| `~/.foxrun/GLOSSARY.md` | Words generated from rows. |
| `~/.foxrun/STATE.md` | The page an agent reads at the start. |
| `~/.foxrun/data.db` | Records stored as database rows. |
| `~/.foxrun/raw` | Outside source material. |
| `~/.foxrun/wiki` | Knowledge pages. |
| `~/foxrun/atlas/AGENTS.md` | Rules for agents. |
| `~/foxrun/atlas/GLOSSARY.md` | Words generated from rows. |
| `~/foxrun/atlas/comparisons` | Knowledge pages. |
| `~/foxrun/atlas/concepts` | Knowledge pages. |
| `~/foxrun/atlas/entities` | Knowledge pages. |
| `~/foxrun/atlas/history` | Kept work and handoffs. |
| `~/foxrun/atlas/queries` | Knowledge pages. |
| `~/foxrun/atlas/raw` | Outside source material. |
| `~/foxrun/<workspace>/AGENTS.md` | Rules for agents. |
| `~/foxrun/<workspace>/GLOSSARY.md` | Words generated from rows. |
| `~/foxrun/<workspace>/STATE.md` | The page an agent reads at the start. |
| `~/foxrun/<workspace>/history` | Kept work and handoffs. |
| `~/foxrun/<workspace>/notes` | Living pages for your work. |
| `~/foxrun/<workspace>/raw` | Outside source material. |
| `~/foxrun/<workspace>/wiki` | Knowledge pages. |

## Records and pages

Records hold facts, such as a task and its status.
A database stores records as rows.
Pages explain the work and show useful information from those rows.
These memory words come from the installed dictionary.
`STATE.md` names the start page. Its name does not name a memory type.

| Memory word | What it means |
|---|---|
| Knowledge | Explains a subject. |
| Playbooks | Explains how work runs. |
| Records | Holds facts that authorized writers can change. |
| History | Keeps work from a past moment. |

| Record | What it holds |
|---|---|
| `comments` | One comments definition in the work module. |
| `decisions` | One decisions definition in the work module. |
| `tasks` | One tasks definition in the work module. |

## Make your first task

Open Terminal on macOS or Linux, or PowerShell on Windows.
Print your start page:

```sh
python3 "$HOME/.foxrun/foxrun.py" start --workspace cedar-shop
```

On Windows PowerShell, use:

```powershell
py -3 "$HOME/.foxrun/foxrun.py" start --workspace cedar-shop
```

The page names your person, workspace, open tasks, and files to read.
Create one task:

```sh
python3 "$HOME/.foxrun/work/work.py" --workspace cedar-shop --receipt-root "$HOME/foxrun/cedar-shop" create --title "Check the first delivery" --by avery \
  --problem "The first delivery is not checked" --job-when "When the first delivery arrives" \
  --job-want "I want to check each item" --job-so "So I can trust the shop" --body "Check each item in the first delivery" \
  --acceptance "Each item is checked" --context "The first task in this shop" --where STATE.md
python3 "$HOME/.foxrun/foxrun.py" start --workspace cedar-shop
```

On Windows PowerShell, keep the task command on one line:

```powershell
py -3 "$HOME/.foxrun/work/work.py" --workspace cedar-shop --receipt-root "$HOME/foxrun/cedar-shop" create --title "Check the first delivery" --by avery --problem "The first delivery is not checked" --job-when "When the first delivery arrives" --job-want "I want to check each item" --job-so "So I can trust the shop" --body "Check each item in the first delivery" --acceptance "Each item is checked" --context "The first task in this shop" --where STATE.md
py -3 "$HOME/.foxrun/foxrun.py" start --workspace cedar-shop
```

Every task carries six fields: the problem, the job story, what it does, acceptance, context, and where.
The job story has three parts: when, I want, and so I can. Where names a file in the workspace.
The task command prints a task ID. The start page shows its title and status.
`todo` means the task is open. Your task ID can differ from the example.
`--receipt-root` names the workspace folder where the command saves its change record.
The command uses the workspace database when that database exists.
Otherwise, it uses the system database.

## Give your agent its starting information

An agent with a seat starts with its seat:

```sh
python3 "$HOME/.foxrun/foxrun.py" start --workspace cedar-shop --seat <seat>
```

On Windows PowerShell, replace `seat-name` with your seat:

```powershell
py -3 "$HOME/.foxrun/foxrun.py" start --workspace cedar-shop --seat seat-name
py -3 "$HOME/.foxrun/foxrun.py" rulings delivery
```

The start page then shows the seat's summary and its Judgment from `agents/<seat>.md` or `team/<seat>.md`.
To answer what you ruled about a subject, the agent runs `python3 "$HOME/.foxrun/foxrun.py" rulings <words>`.
Read the files under `Read first:` on the start page.
`profile/AGENTS.md` gives shared rules. The workspace’s `AGENTS.md` adds local rules.
`RESOLVER.md` names the source and writer for each fact.
The start page gives current work. The glossary gives each word one meaning.
Ask for explicit approval before money, sends, or production changes.
Do not ask about a delete. Back the thing up, check the backup, then delete. A delete that no backup holds does not happen.
This guide serves people. Agents load rules and the start page separately.

## Connect Claude Code or Codex

A runtime is the app that runs your agent.
A hook is a command that the app runs at a named event.
Install prints the exact hook entries and settings paths.
Merge those entries into the named settings file. Keep its other settings.
For Claude Code, the normal file is `~/.claude/settings.json`.
For Codex, it is `~/.codex/hooks.json`.

Open a new session in `~/foxrun/cedar-shop`.
Check that the start page names your person and workspace.
It should also show your task and the files to read.
If it does not appear, run the start command yourself.
Check the settings path and the hook entries.
Settings files alone do not prove the runtime loads them.

Install can write hook entries when you add `--hookup`.
On an existing install, `python3 "$HOME/.foxrun/foxrun.py" hookup --runtime both` connects them. [INSTALL.md](INSTALL.md#connect-hooks) explains it.
Use `--runtime-home` for separate settings during a trial install.
With `--runtime both`, that folder gets `claude` and `codex` subfolders.
The apps must use those separate settings for the hooks to work.

## When something looks wrong

Run the install check:

```sh
python3 "$HOME/.foxrun/foxrun.py" doctor
```

On Windows PowerShell, use:

```powershell
py -3 "$HOME/.foxrun/foxrun.py" doctor
```

Success ends with `Doctor: 0 failed`.
A `FAIL` line names a failed check. Keep that output for the repair trail.
Save your work before you replace files.
To get a newer version, run `foxrun.py update`. [Update](INSTALL.md#update) gives the command for each install.
The product has no remove command.

## What this install provides

Foxrun prints starting information and saves tasks.
The agent still does the work through its runtime and tools.
The product supports Claude Code and Codex.
It ships 11 skills and the skill release tool.
The skills are `ask`, `capability`, `capture`, `flow`, `handoff`, `log`, `orchestrate`, `runtime-session-search`, `setup`, `thread`, and `to-tickets`.
It does not connect your business accounts or provide business packs.
On macOS, it turns on one nightly job at 02:30 that checks pages and memory.
The installer skips scheduling on Linux and Windows. Install with `--no-schedule` to leave it off.

## Where things live

Each thing has one home. Its owner decides the home.
Ask these questions in order. Stop at the first yes.

```text
Is it the source of a tool?           -> the tool's own repo
Is it an installed copy of a tool?    -> ~/.foxrun (never edit it there)
Is it your own work, kept as rows?    -> ~/.foxrun/data.db
Is it your own work, kept as files?   -> ~/foxrun (a workspace or a repo)
```

| Thing | Home | Example |
|---|---|---|
| The product's source | The Foxrun product folder, its own repo | `work/work.py` in that folder |
| An add-on's source | Its own repo in `~/foxrun` | `~/foxrun/<add-on>/` |
| An installed copy | `~/.foxrun` | `~/.foxrun/work/work.py` |
| Your rows | `~/.foxrun/data.db` | A task or a decision |
| Your files | A workspace or its own repo in `~/foxrun` | `~/foxrun/<workspace>/notes/` |

Nobody edits an installed copy. An update replaces it, so an edit there is lost.
To change a tool, change its source, not the copy.

### Where skills live

A skill has one owner: the product or you.
Product skills come with Foxrun. Today there are 11:
`ask`, `capability`, `capture`, `flow`, `handoff`, `log`, `orchestrate`, `runtime-session-search`, `setup`, `thread`, and `to-tickets`.
Their source is in the product folder, in `skillwright/skills/`.
Install puts their copy in `~/.foxrun/skillwright/skills/`.
Your skills are your own work.
Keep a skill for every workspace in `~/foxrun/skillwright/skills/`.
Keep a skill for one workspace in `~/foxrun/<workspace>/skills/`.
The release tool, `skillwright/tools/skill_ship.py`, puts each released skill in two places:

| Place | What it holds |
|---|---|
| `~/.foxrun/skills` | The released shelf. It keeps each release, so you can go back. |
| `~/.agents/skills` | The skills that Claude Code and Codex read. |

Each released skill records its owner: the product or you.
An update replaces only product skills. It does not touch your skills.
Do not edit a product skill.
To change one, copy it under a new name into your own skills folder.
The copy is then your skill, and an update leaves it alone.
Other runtimes keep their own skill folders.
Hermes keeps its own skills in `~/.hermes/hermes-agent/skills`.
It keeps the skills in use in `~/.hermes/skills`.

This section gives the rule. Two parts are not built yet.
The release tool does not yet read `~/foxrun/skillwright/skills/` by default.
It does not yet record the owner of each skill.

## Words to keep clear

| Word | Meaning |
|---|---|
| Orchestration | Directing work across agents and runtimes, retrieving results, and managing the lifecycle of delegated work. Native runtime paths and Herdr are possible adapters; neither defines the whole capability. |
| Multi-Agent Run | One lead runs several agents from one brief, then reviews and closes their work. |
| Agent | One identity on one runtime: a Hermes profile, a Claude subagent (`.claude/agents/*.md`), or a Codex custom agent (`.codex/agents/*.toml`). The same persona on two runtimes (e.g. the Keeper) is two agents that share a name. |
| Agent Definition | Its own object, seven dimensions from the Anatomy of an Agent: model, contract, capabilities, stores, anchor, triggers, guardrails. Links to many Capability Records. ADR 0005. |
| Capability | One usable thing in eight categories: Skill, CLI, MCP, Plugin, Service, Connection, Hook, Script. |
| Capability Record | One object for everything an agent can use: type is skill, cli, mcp, plugin, or automation; trigger is on demand, event, or schedule; connection is a field naming the outside account. Service, hook, and script are all automation. ADR 0005. |
| Scope | Where an agent or capability belongs: Global (home-directory dotdirs) or one workspace. For Claude/Codex, scope is the literal location of the definition file; for Hermes, scope is the lane the profile's working directory points at. |
| Applies To | The affected boundary on a decision, task link, or external system record. |

Use [GLOSSARY.md](GLOSSARY.md) for the shared words.
Each workspace keeps only its own words in its glossary.

## Optional add-ons

Read [Optional add-ons](OPTIONAL-ADDONS.md) for requirements, costs, licenses, and setup links.
Run `python3 "$HOME/.foxrun/foxrun.py" addons` to show the installer-readable list.
Run `python3 install.py --list-addons` from the source folder before installation.
On Windows PowerShell, use:

```powershell
py -3 "$HOME/.foxrun/foxrun.py" addons
py -3 install.py --list-addons
```

The installer shows the list and installs none of these tools.
Unverified licenses mean install-yourself. Jev and unnamed tools remain unavailable.
Foxrun has not checked these licenses online. Check a license yourself before you install the tool.
