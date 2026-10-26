---
type: doc
workspace: system
timestamp: 2026-10-22T11:48:23-04:00
---
# Documentation

One section for each folder. One row for each file or folder in it.

**How each description is written**

1. What it does. It starts with a verb.
2. Why you use it. It starts with "Use it to".
3. The trigger, in brackets: `user command` · `hook: <name>` · `cron <time>` · `script: <names>` · `read by <who>`.

`not in product` in the brackets means the file is yours and does not go to a person who installs Foxrun.

## ~/.foxrun

| File | Description |
|---|---|
| `.gitignore` | Tells Git to leave out caches, databases, `.env` files, and test journals. Use it to keep data and secrets out of a commit. (read by Git) |
| `AGENTS.md` | Sets ownership and write rules for work inside the system home. Shared rules live in `profile/AGENTS.md`. |
| `CLAUDE.md` | Imports the system-home contract with `@AGENTS.md`. Runtime startup reads the soul and global contract separately. |
| `CHANGELOG.md` | Lists what changed in each version. Use it to see what an update brings. (read by you) |
| `DOCUMENTATION.md` | Gives one line for each file and folder of the system folder. Use it to learn what a file does before you open it. (read by you and by agents) |
| `GLOSSARY.md` | Gives each word of the system one meaning. Use it to stop two names for one thing. (read by agents and by you; script: `base/published_pages.py`) |
| `GUIDE.md` | Walks a new person through the first hour. Use it to learn the daily commands. (read by you; script: `base/published_pages.py`) |
| `LICENSE` | States the terms for using and sharing Foxrun. Use it to know what you may do with the product. (read by you) |
| `INSTALL.md` | Gives the three install commands and what each prints. Use it to install or remove Foxrun. (read by you; script: `base/published_pages.py`) |
| `OPTIONAL-ADDONS.md` | Rolls up the tools Foxrun does not install: capture's programs and the recommended extras, each with a link to its tool page. Use it to decide what to add yourself. (read by you; `foxrun.py addons` prints the same list) |
| `README.md` | Says what Foxrun is and where to start. Use it to find `INSTALL.md` and `GUIDE.md`. (read by you) |
| `RESOLVER.md` | Says where each kind of work is saved, and which tool writes it. Use it to pick the right folder for a new file. (read by all agents) |
| `SCHEMA.md` | Gives the front matter and naming rules, then every table and field of `data.db`. Use it to look up a field before you query. (script: `install.py`, `base/generate_pages.py`) |
| `SECURITY.md` | Says how to report a security problem in private. Use it to report a vulnerability without a public issue. (read by you) |
| `STATE.md` | Holds the current state of the system folder in one page. Use it to see where work stands. (script: `memory/state.py`; read by `foxrun.py start`) |
| `VERSION` | Holds the version number. Use it to tell which Foxrun is installed. (script: `foxrun.py`) |
| `foxrun.py` | Prints the start page, checks the install, prints the version, and shows what the person ruled about some words (`rulings <words>`). `hookup` connects the session hooks to an existing install. Use it to start a session with `start --seat <seat>`, find a broken file, or answer from the decisions. (user command; hook: session-start, after-compact) |
| `update.py` | Refreshes product files and migrates an existing home with a backup and automatic rollback. Use it to keep personal state through an update. (user command: `foxrun update`) |
| `install.py` | Installs Foxrun into two empty folders, builds the database, and prints the hook entries. Use it to install Foxrun. (user command, run from the product folder) |
| `made-at-install.tsv` | Carries the list of what the install makes into the new home. The doctor reads the copy in `base/`. (script: `install.py`) |
| `product-manifest.tsv` | Lists every shipped file with its size and hash; the install copies only these files. The doctor reads the copy in `base/`. (script: `install.py`) |
| `data.db` | Stores the tasks, runs, comments, and decisions of the system. Use it to answer "what is open" from rows. (script: `work/work.py`, `work/program.py`, `foxrun.py`) |
| `health.json` | Records that the install finished and that schedules are off. Use it to check the install state by code. (script: `install.py`) |
| `tests/test_workspace_lead.py` | Checks generated lead boots, name collisions, workspace exclusions, and a staged first session. |
| `test_*.py` | Test the launcher, the installer, the day-one flow, and the workspace database. Use them to prove a change did not break them. (user command) |
| `agents/` | Holds the seat file of each agent and the scripts that build agents. Use it to add or change an agent. (see its section) |
| `archive/` | Keeps old files that are no longer in use. Use it to find something from before the move. (read by you · not in product) |
| `backups/` | Keeps copies of the database. Holds the one database that no tool reads yet. (script: `base/backups.py` · contents not in product) |
| `base/` | Holds the code every other folder uses: the database builder, the checks, the workspace installer. Use it to change shared behavior. (see its section) |
| `capture/` | Holds the code that saves a web page, a post, or a file as a source. Use it to add something to your library. (see its section) |
| `config/` | Holds the settings you choose: your name, the models, the tools, the page templates. Use it to change a setting in one place. (see its section) |
| `cron/` | Holds the schedule files of timed jobs. Use it to see what runs on its own, and when. (cron · empty on day one; contents not in product) |
| `decisions/` | Holds the code that records a ruling and an approval. Use it to write a decision as a row, not as a chat line. (see its section) |
| `design/` | Holds the brand and design rules and their page templates. Use it to keep one look across your work. (read by agents · an optional pack; the install leaves it out) |
| `evals/` | Holds the test sets: `memory/` ships and `agents/` is empty. Use it to score the system against fixed cases. (see its section) |
| `events/` | Holds the code that writes the log of what happened, and that logs each agent session. Use it to see who changed what, and when. (see its section) |
| `hooks/` | Holds the small commands Claude Code, Codex, and Hermes run at session start and around a compact. Use it to give an agent its start page. (see its section) |
| `memory/` | Holds the code that checks a handoff, builds `STATE.md`, and compiles what was learned. Use it to keep context across sessions. (see its section) |
| `modules/` | Holds local add-ons that are not part of the product. Use it to install a module of your own. (empty on day one; business packs never ship) |
| `profile/` | Holds `USER.md` and `VOICE.md`: who you are and how you write. Use it to make agents sound like you. (read by all agents · empty on day one; contents not in product) |
| `raw/` | Keeps sources as they arrived: saved repositories, articles, scrapes. Use it as the untouched original. (script: `capture/` · contents not in product) |
| `runs/` | Keeps the working files of each run of work, one folder for each run. Use it to see what a run read and wrote. (written by agents during a run; script: `foxrun.py start` · contents not in product) |
| `skills/` | Holds the released skills, product and yours: the released shelf. Use it to go back to an earlier release. Claude Code and Codex read the skills in `~/.agents/skills`. (script: `skillwright/tools/skill_ship.py` · two skills in product; see its section) |
| `skillwright/` | Holds the installed copy of the product skills and the tools that release skills. Use it to release a skill. Your own skill source lives in `~/foxrun/skillwright/skills/` or `~/foxrun/<workspace>/skills/`. (user command · see its section) |
| `small-talk/` | Holds the installed copy of the service that drafts a reply in your voice. Its source and its eval cases stay in the add-on's own source folder. Use it to answer a message without typing it yourself. (user command · not in product) |
| `state/` | Starts as an empty folder made by the installer. The local nightly job fills it with JSONL exports of `data.db`. Use it to read rows with no database tool. (script: `base/backup.py`, run by `memory/dream.py`; `base/state_jsonl.py` checks it) |
| `tools/` | Holds the tool shelf: one page for each tool. Product pages ship with Foxrun; your own pages sit beside them. Use it to see what agents can use. (read by agents · product pages ship; your pages are not in product) |
| `wiki/` | Holds compiled knowledge pages in `concepts/` and `entities/`. Use it to keep what was learned in one place. (empty on day one) |
| `work/` | Holds the task tool and the program view. Use it to create, claim, and close a task. (see its section) |
| `workspaces/` | Holds the team, skills, and tools pages of each workspace, one folder for each. Use it to see what each workspace can use. (script: `base/make_workspaces_view.py` (check) · not in product) |

## ~/.foxrun/agents

| File | Description |
|---|---|
| `.gitignore` | Tells Git to leave out caches, probe logs, and `.env` files in this folder. Use it to keep secrets out of a commit. (read by Git) |
| `soul.md` | States the base character every agent starts from. Use it to change how all agents talk and act. (read by all agents) |
| `adviser.md`, `architect.md`, `scout.md`, `chief-of-staff.md`, `keeper.md`, `skillwright.md`, `toolsmith.md` | Each states one seat: who the agent is and what it owns. Use one to change one agent. (read by that agent) |
| `mercer.md` | States your own seat for one business. Use it to change that agent. (read by that agent · not in product) |
| `README.md` | Explains the folder and the commands of `agent_new.py`. Use it to learn how an agent is made. (read by you) |
| `defaults.json` | Holds the default values for this folder's page templates. Empty today. (script: the workspace installer in `base/`) |
| `simple_yaml.py` | Reads YAML settings files for the Python scripts. Use it to run them with nothing extra installed. (script: `agent_new.py`, `eval_run.py`, `profile_check.py`, `render_capabilities.py`, `tool_probe.py`) |
| `tools/agent_new.py` | Builds the Claude and Codex files of an agent from one seat file (.md). Use it to add an agent or change one. (user command) |
| `tools/eval_run.py` | Asks each agent fixed questions and checks the answers against proof. Use it to confirm the team still behaves after a change. (user command) |
| `tools/profile_check.py` | Compares the files Claude and Codex load with each seat file, and checks that each agent's tools answer. Use it to catch a change nobody approved. (user command; no schedule ships for it yet) |
| `tools/render_capabilities.py` | Writes the page that lists the tools and skills of one workspace. Use it to tell an agent what it can use. (user command) |
| `tools/tool_probe.py` | Asks, read only, which tools and skills an agent has. Use it to prove a tool list is true. (script: `eval_run.py`, `profile_check.py`) |
| `tools/paths.py` | Names the system folder and the work folder of this Mac in one place. Use it to move a folder with one change. (script: `agent_new.py`, `eval_run.py`, `profile_check.py`, `render_capabilities.py`, `tool_probe.py`) |
| `execution/` | Holds the rules for handing work to an agent: the policy, the skill list, one binding file for each runtime. Use it to change what a seat may do. (script: `agent_new.py`, `eval_run.py`) |
| `generated/` | Holds the files made for Claude (`claude/`) and Codex (`codex/`) from the seat files. Do not edit them by hand. (script: `agent_new.py`) |
| `docs/` | Holds the longer notes on how agents are built: the seat file format and the capabilities page. (read by you) |
| `tests/` | Tests the scripts in this folder. Use them to prove a change did not break agent building. (user command) |
| `tools/` | Holds the scripts that build and check agents: `agent_new.py`, `eval_run.py`, `profile_check.py`, `render_capabilities.py`, `tool_probe.py`, `paths.py`. (user command) |

## ~/.foxrun/agents/execution

| File | Description |
|---|---|
| `policy.yaml` | Sets which model and effort each runtime uses, for judgment work and for plain work. Use it to change the model of all agents in one place. (script: `agent_new.py`, `render_capabilities.py`) |
| `skills.yaml` | Records which release of the skills the agents were built against. Use it to learn that the skills changed and the agents must be built again. No release is recorded in the product yet. (script: `eval_run.py`) |
| `assignment.schema.json` | Defines the form of a job handed to an agent: who, the task, the inputs, the limits. Use it to check a handoff before it is sent. (script: `agent_new.py`) |
| `result.schema.json` | Defines the form of what an agent hands back: the deliverable, the evidence, what is unresolved, the cost. Use it to check a result. (script: `agent_new.py`) |
| `bindings/claude.yaml`, `bindings/codex.yaml`, `bindings/hermes.yaml` | Each says how one runtime gets its model: defaults from `policy.yaml`, your overrides from `config/models.yaml`. Use one to change one runtime. (script: `agent_new.py` · Hermes is off on day one) |
| `teams/` | Holds the team file of one of your workspaces. Use it to name who works there. (check) (not in product) |

## ~/.foxrun/agents/generated

| File | Description |
|---|---|
| `claude/` | Holds the agent files Claude Code loads, one `.md` for each agent. Do not edit by hand; change the seat file and build again. (script: `agent_new.py`) |
| `codex/` | Holds the agent files Codex loads, one `.toml` for each agent. Do not edit by hand. (script: `agent_new.py`) |

## ~/.foxrun/archive

| File | Description |
|---|---|
| `README.md` | Lists the local archive folders and what each holds. Use it to find an archived file. (read by agents · not in product) |
| `<workspace>/` (8 folders) | Keeps the old files of one workspace that are no longer in use. Use it to find something from before the move. (read by you · not in product) |
| `portfolio/` | Keeps the dated root leftovers from the Portfolio move. Use it to trace files left at the old root. (read by agents · not in product) |
| `<date>-<name>/` (4 folders) | Keep what one dated move or task left behind, such as dropped apps and old worker runs. (read by you · not in product) |
| `vault/` | Keeps old files of the vault that belong to no workspace. (read by you · not in product) |
| `code/` | Keeps old code repositories that are no longer in use. (read by you · not in product) |
| `skill-releases/`, `skill-state/` | Keep past released versions of skills and the release tool's state. Use them to go back to an older skill. (read by you · not in product) |
| `one-time-scripts/` | Keeps scripts that were written for one job and are done. (read by you · not in product) |
| `staging/`, `agents-metadata/` | Keep leftover working files of older setups. (read by you · not in product) |
| `linear-rules/` | Keeps the old rules for the issue tracker and its labels. (read by you · not in product) |
| `r2b/` | Keeps a shaped copy of one workspace and its views from an earlier round. (check) (read by you · not in product) |

## ~/.foxrun/backups

| File | Description |
|---|---|
| `jsonl/` | Receives each workspace database that has its own `data.db` as text lines, in `jsonl/<workspace>/`, one file for each table. The system database goes to `state/`, not here. Use it to restore a workspace database. Empty until a workspace has its own database. (script: `base/backup.py`, run by the `backup` step of `memory/dream.py`) |
| `one-database/data.db` | Holds your data in the one-database shape of your design: 93 tables. No tool reads it yet. Use it as the proven source when the tools move to that shape. (not in product) |
| `hookup-<time>-<id>/` | Keeps the runtime settings files as they were before `foxrun.py hookup` changed them, with `sources.json` naming each original path. Use one to undo a hookup. (script: `base/hookup.py` · not in product) |
| `<date>-<task>` files and folders | Keep a copy of the database taken before one change. Use one to undo that change. (script: the change that made it · not in product) |

## ~/.foxrun/data.db

| File | Description |
|---|---|
| `data.db` | Stores your Foundation tasks, runs, comments, and decisions, in the table shape the tools read today (39 tables). Use it through `work/work.py`; do not edit it by hand. (script: `work/work.py`, `work/program.py`, `decisions/approve.py`, `foxrun.py`) |

The tables of your design, one group for each module, are in `backups/one-database/data.db`:

| Module | Tables | What the tables hold |
|---|---|---|
| `base` | 9 | The dictionary of the system: which modules are installed, every object type, every field and value, every capability. |
| `work` | 13 | Goals, programs, themes, work streams, tasks, bugs, incidents, measures. |
| `events` | 7 | What happened: changes, comments, runs, receipts, attachments. |
| `decisions` | 4 | Rulings, approvals, proposals, and the links between decisions. |
| `memory` | 4 | Lessons, and the sources, evidence, and rollups behind them. |
| `people` | 16 | Contacts, organizations, handles, messages, meetings, deals, drafts, draft facts. |
| `design` | 2 | Design briefs and design content. |
| `commerce` | 16 | Products, prices, stock, orders, shipments, restocks, reviews. |
| `amazon` | 8 | Amazon accounts, listings, listing changes, ads, compliance cases. |
| `tiktok-shop` | 1 | TikTok Shop orders. |
| `ugc` | 7 | Creator cycles, deliverables, media files, usage rights, payments owed. |
| `treasury` | 6 | Transactions, transfers, scheduled payments, budget snapshots. |

The seven tables that F15 to F19 in the review page named as missing are built now.

## ~/.foxrun/base


| File | Description |
|---|---|
| `secret_check.py` | Checks staged additions and bounded Git history without printing values. Use it to stop secret commits. (hook: pre-commit; user command) |
| `secret-patterns.json` | Defines token, key, cookie, bearer, and entropy patterns. Use it to keep both scans on one pattern list. (read by `base/secret_check.py`) |
| `LINT-GRAMMAR.md` | Lists each text form the contract lint checks, with one piece it flags and one it does not. Use it to see exactly what `contract_lint.py` flags. (read by you; `tests/test_contract_lint_grammar.py` holds the same forms) |
| `README-contract-lint.md` | Explains the contract lint: what it checks, its rules file, and its commands. Use it to run the lint on chosen contracts. (read by you) |
| `README-contract-test.md` | Explains the contract test: fifteen fixed questions to a model that reads only chosen contracts. Use it to check that the contracts alone answer the rules. (read by you) |
| `README-index.md` | Explains the index generator and its arguments. Use it to build an index preview from named sources. (read by you) |
| `README-install.md` | Explains the create-only workspace installer: plan first, then apply the saved plan. Use it to add a workspace by hand. (read by you) |
| `README-reader-check.md` | Explains the reader check and its plan file. Use it before a table, file, folder, or program moves or gets a new name. (read by you) |
| `README-recovery.md` | Explains the private recovery bundle: what it holds and how it restores into a new file. Use it to recover a module database. (read by you) |
| `README-state.md` | Explains the export of every table to JSONL and the rebuild from it. Use it to export or rebuild the database. (read by you) |
| `README-workspace-pages.md` | Explains the commands that build workspace indexes, wiki topic pages, and the library page. Use it to build or check those pages. (read by the Keeper and by you) |
| `README-workspace-schematic.md` | Explains the workspace schematic: one page that shows each workspace beside the model. Use it to run the schematic and read its red marks. (read by you) |
| `questions.tsv` | Holds 20 portable cases for the agent-rules grader. Use it to check the rubric on any machine. (script: `base/t97_grade.py --self-test`) |
| `t97_grade.py` | Grades saved agent-rules answers and checks its own rubric. Use it to confirm each required answer passes. (user command) |
| `README.md` | The front door of base: what it builds, a table that links every tool page, and the notes on the `data.db` commands. Use it to start reading `base/`. (read by you) |
| `agent_catalog.py` | Finds the shipped skills, the catalog routes, and the tool permissions of an agent. Use it to know which skills an agent may load. (script: `agents/tools/agent_new.py`, `make_workspaces_view.py`, `module_commands.py`) |
| `apply_dictionary.py` | Backs up the database, then installs, seeds, checks, and exports the data dictionary. Use it to update the dictionary safely. (script: `work/apply_incidents.py`, `work/apply_program_schema.py`) |
| `backup.py` | Exports a read-only snapshot of the database to JSONL files and replaces each file in one step. Use it to keep a text copy of every table. (script: `memory/dream.py`, `work/work.py`, `apply_dictionary.py`, `work/apply_*.py`, `skillwright/tools/skill_backup.py`) |
| `backups.py` | Makes a timestamped copy of the database, archives old copies, and restores one exactly. Use it before a change you may undo. (script: `apply_dictionary.py`, `work/apply_incidents.py`, `work/apply_program_schema.py`) |
| `blueprint/` | Holds the table definitions of the current blueprint: columns, targets, rules, and source hashes. Use it to see the shape the database must have. (script: `core.py`, `build_database.py`, `check_blueprints.py`) |
| `build_database.py` | Builds one SQLite database from the blueprints of the chosen modules. Use it to make a new database or add a module. (script: `install.py`, `install_workspace.py`, `memory/state.py`) |
| `catalog.py` | Applies one reviewed version of the skill catalog and tells Skillwright. Use it to change which skills publish. (user command; script: `agents/tools/agent_new.py`) |
| `check_blueprints.py` | Checks the SQL blueprints of all modules for tables or names that collide. Use it before you add a module. (script: `memory/dream.py`) |
| `check_workspace.py` | Checks one workspace against the workspace spec, read only, and can add lint findings. Use it to find a workspace that is off its shape. (user command; script: `distribution/build_release.py`, `distribution/check_clean_install.py`) |
| `commands/` | Holds one small command for each table; each passes its table name to `core.py`. Use them to write a row through its checks. (user command; script: agents) |
| `contract-lint-rules.json` | Lists the contract file names the lint knows and the rules for each. Use it to change a contract rule. (script: `contract_lint.py`, `decisions/approve.py`) |
| `contract-test-answers.json` | Holds the answer key of the contract test for the system workspace. Use it to score the test; the model never sees it. (script: `contract_test.py`) |
| `contract-test-questions.json` | Holds the fifteen fixed questions of the contract test for the system workspace. Use it to ask the same questions each time. (script: `contract_test.py`) |
| `contract-test-shop-answers.json` | Holds the answer key of the contract test for the sample shop. Use it to score the sample shop test. (script: `contract_test.py`) |
| `contract-test-shop-questions.json` | Holds the fixed questions of the contract test for the sample shop. Use it to test a business workspace. (script: `contract_test.py`) |
| `contract_judgment.py` | Asks Jev three judgment questions about each contract section and adds the answers to the lint report. Use it for a second pass after the exact checks. (script: `contract_lint.py --judgment`) |
| `contract_lint.py` | Checks chosen contracts, a workspace, or the whole portfolio, read only, and prints one line for each finding. Use it to find a broken rule or link in a contract. (user command; script: `check_workspace.py`, `decisions/approve.py`) |
| `contract_runtime_adapter.py` | Makes one read-only model call for the contract test. Use it to connect the test to a runtime. (script: `contract_test.py`) |
| `contract_test.py` | Asks a model command the fixed questions with only the chosen contracts as input, then scores the answers. Use it to prove the contracts alone answer the rules. (user command) |
| `core.py` | Builds the blueprint database and runs the checked table commands. Use it to write a row with its rules. (script: every file in `commands/`) |
| `defaults.json` | Holds the default value of each blank in the base page templates. Use it to fill a new page with known words. (script: `install_workspace.py`) |
| `dictionary-seed.sql` | Fills the dictionary tables with the object types, columns, and links of the product. Use it to give a new database its dictionary. (script: `build_database.py`, `core.py`, `apply_dictionary.py`, `regenerate.py`) |
| `dictionary.sql` | Defines the dictionary tables: object types, fields, and values. Use it to see how the dictionary is stored. (script: `build_database.py`, `apply_dictionary.py`, `generate_pages.py`, `lookup.py`) |
| `dictionary_v11.py` | Updates the dictionary to a new blueprint and can check, undo, or restore it. It writes no business table. Use it to move the dictionary to a new version. (user command; script: `core.py`, `regenerate.py`) |
| `distribution/` | Holds the tools that build, fetch, and test a release, and scan it for private text. Use it to make a release. (user command) |
| `fixtures/` | Holds sample pages the tests and evals compare against: an index definition and a sample shop `AGENTS.md`. (script: tests and `evals/memory/`) |
| `generate_index_v2.py` | Makes a workspace index from its files and its database, opened read only. Use it to build an index preview. (user command) |
| `generate_pages.py` | Builds `SCHEMA.md` and the glossary pages from the dictionary and the word rows. Use it to rebuild those pages after a change. (script: `published_pages.py`) |
| `generate_schema.py` | Makes JSON Schema files, a diagram of the tables, and a guide from the dictionary rows. Use it to share the table shapes. (user command) |
| `guards.sql` | Adds the triggers that refuse a write outside a table command and refuse each delete. Use it to protect every table. (script: `regenerate.py`; made by it, do not edit) |
| `install.json` | Lists the files this part writes into a new workspace, such as `AGENTS.md` and `STATE.md`. Use it to change what a new workspace gets. (script: `install_workspace.py`, `install.py`) |
| `install_lint_defaults.py` | Writes the lint list of one new install. Use it to give the lint the names of a fresh home. (script: `install.py`) |
| `install_system.py` | Copies the product settings into `config/` of a new home, and keeps the choices already there. Use it to set up settings once. (script: `install.py`) |
| `install_workspace.py` | Plans or applies a create-only workspace install from the module manifests. Use it to add a workspace without touching one that exists. (script: `install.py`; user command) |
| `lint.py` | Checks both homes against the rules in `config/lint/` and prints each finding. Use it to find a page or folder off its rules. (user command; cron 02:30 through `cron/nightly.py` on this Mac) |
| `tests/test_write_contract.py` | Proves write input safety, rule write behavior, speed, and automatic workspace registration on fake homes. |
| `lint_gate.py` | Checks proposed bytes, refuses bad input, and applies each rule's write setting. Use it before a managed file write. |
| `lint_render.py` | Shows a managed Markdown page in the Foxrun page style, offline. Use it to see a page as it should look. (script: `lint.py`, `lint_gate.py`) |
| `lint_rule.py` | Adds one lint rule of a known kind after a good and a bad sample prove it. Use it to grow the lint. (user command) |
| `list_legacy_approval_words.py` | Lists accepted approvals whose saved words equal the proposal reason. Opens the database read-only. (user command) |
| `load_capabilities.py` | Loads a reviewed capability map into the capability table; equal rows do not change. Use it to record what each agent can use. (user command) |
| `lookup.py` | Reads the dictionary and the path rules of the workspace spec, read only. Use it to answer where a thing lives. (user command) |
| `make_workspaces_view.py` | Builds the workspace view from the seat, skill, and tool pages. Its `TOOLS.md` also lists the shelf tools that `config/tools.yaml` pushes with `applies_to`. Use it to see what each workspace can use. (user command; script: `workspace_capabilities.py`) |
| `migrate_capabilities.py` | Loads capability rows into the one database after its move; it checks only unless you add `--write`. Use it once for that move. (user command) |
| `module_commands.py` | Finds the table commands of each installed module and writes their part of the capabilities page. Use it to list what a module lets you write. (script: `workspace_capabilities.py`) |
| `hookup.py` | Merges the Foxrun session hooks into Claude Code and Codex settings. It keeps other entries, removes only the exact start-rules entry older installs wrote, backs up each changed file under `backups/hookup-<time>-<id>/`, and writes nothing on a second run. Use it to connect hooks after an install. (script: `foxrun.py hookup`, `foxrun hookup`, `install.py --hookup`, the `setup` skill) |
| `optional_addons.py` | Prints the optional add-ons from `config/optional-addons.tsv`; it installs nothing. Use it to see what you may add. (script: `foxrun.py addons`, `install.py`) |
| `tests/test_words.py` | Checks sourced word adds, changes, and removals, identity refusal, TSV shape, rebuilt pages, and failed-write recovery. (test) |
| `words.py` | Adds, changes, or removes one sourced word row and rebuilds its glossary. Use `remove` with workspace, group, word, and a source reason. (user command; tests: `base/tests/test_words.py`) |
| `ownership.py` | Checks system-path ownership, logs denied writes through `work/work.py`, and verifies a cleared alarm for its writer and path. Use it before a system-file write. (user command; script: `work/work.py`, `agents/tools/agent_new.py`) |
| `pack_policy.py` | Reads each module's `install.json` to decide whether the pack ships. Use it as the one rule for what ships. (script: `install_workspace.py`, `distribution/build_release.py`) |
| `page_indexes.py` | Builds the file indexes of each workspace, the wiki topic pages, and the library page `atlas/LIBRARY.md`, for a date you give. Use it to rebuild those pages or check them. (user command; script: `install.py`, `memory/dream.py`; read by the Keeper) |
| `pages_common.py` | Holds the shared code that reads workspace sources and writes generated pages. Use it as the base of the page builders. (script: `memory/compile.py`) |
| `paths.py` | Resolves seats through workspace, personal, and shipped files. Names the system home, the portfolio, and the database, and checks each link. Use it to move a folder with one change. (script: most scripts, `foxrun.py`) |
| `person.py` | Reads the person who owns this install from `config/person.json`. Use it so no script names a person in its code. (script: most scripts) |
| `product-manifest.tsv` | Lists every shipped file with its hash. Use it to find a changed or missing file. (script: `foxrun.py doctor`) |
| `made-at-install.tsv` | Lists every file and folder the install makes. Use it to find a missing one. (script: `foxrun.py doctor`) |
| `proposal-rules.md` | States which fields need an accepted proposal and which changes need an approval first. Use it to change those rules. (script: `table.py`) |
| `prove_recovery_bundle.py` | Makes and keeps one full recovery proof from made-up data under `/tmp`. Use it to prove the recovery bundle works. (user command) |
| `published/` | Holds the rows the human pages are made from: the guide text and the shared words. Use it to change `GUIDE.md`, `INSTALL.md`, or `GLOSSARY.md`. (script: `published_pages.py`) |
| `published_pages.py` | Builds the human pages from the rows in `published/`, the install rows, and the dictionary. Use it after you change a row. (script: `install.py`; user command) |
| `reader_check.py` | Lists what still uses an old name and tests a rename in a copy. It never changes a source. Use it before a move or a rename. (user command) |
| `recovery_bundle.py` | Makes and restores one private recovery bundle of a module database, into a new file only. Use it to recover lost data. (user command; script: `prove_recovery_bundle.py`) |
| `recovery_values.py` | Reads the values in a recovery bundle strictly. Use it so a restore never guesses a value. (script: `recovery_bundle.py`) |
| `regenerate.py` | Builds `schema.sql`, `views.sql`, `guards.sql`, and the table commands again from the blueprint. Use it after a blueprint change. (user command) |
| `run_trails.py` | Plans the move of run folders to their ruled home; it moves only with `--move` and can undo. Use it once for that move. (user command) |
| `schema.sha256` | Holds the hash of `schema.sql`. Use it to tell that the schema changed. (script: `regenerate.py`) |
| `schema.sql` | Creates every table of the blueprint. Use it to see each column and check. (script: `regenerate.py`; made by it, do not edit) |
| `simple_yaml.py` | Reads a small part of YAML with no extra package. Use it to read settings files. (script: `agents/tools/*`, `agent_catalog.py`, `ownership.py`) |
| `state_jsonl.py` | Exports every table to one sorted JSONL file without changing the database. Use it to keep a text copy you can compare. (user command; script: `state_rebuild.py`) |
| `state_rebuild.py` | Builds a separate database from the blueprint and a full JSONL export, then compares them. Use it to prove an export is complete. (user command) |
| `table.py` | Checks module table writes. Proposal acceptance requires `--person-words` and saves the exact text. (script: add-on module commands) |
| `templates/` | Holds the blank pages a new workspace gets, its wiki starter in `wiki/`, and a filled sample shop for each. Use it to change what every new workspace starts with. (script: `install_workspace.py`, `install.py`) |
| `tests/` | Tests the scripts in this folder, with their fake rows (`fixtures.py`), fake model (`contract_test_stub.py`), and fake Jev (`contract_judgment_stub.py`). Use them to prove a change did not break the base. (user command) |
| `tests/test_tablecmd.py` | Checks proposal guards, exact approval words, and read-only legacy listing with fake rows. (test command) |
| `tracker.py` | Finds the task database to use without changing it. Use it so every script opens the same tracker. (script: `work/work.py`, `memory/state.py`, `hooks/write_handoff.py`, others) |
| `value_sets.py` | Adds each missing allowed value that the table guards read, one row at a time. Use it once on a new database before a guarded field is written. (user command) |
| `views.py` | Holds the saved queries of the blueprint as code. Use it to build the views. (script: `core.py`, `regenerate.py`) |
| `views.sql` | Creates the saved queries, such as open tasks and this week. Use it to read rows the same way each time. (script: `core.py`, `regenerate.py`; made by it, do not edit) |
| `workspace-schematic-page.html` | Draws the workspace schematic as one page. Use it to see each workspace beside the model. (script: `workspace_schematic.py`) |
| `workspace-schematic-rules.json` | Lists the folder model and the database checks the schematic uses, each with its decision. Use it to change a schematic rule. (script: `workspace_schematic.py`) |
| `workspace-schematic.schema.json` | Defines the form of the data the schematic writes. Use it to check that data before the page draws it. (script: `workspace_schematic.py`) |
| `workspace-spec.md` | Lists the folders of a workspace with the lens and module of each. Use it to see where a file belongs. (script: `check_workspace.py`, `lookup.py`) |
| `workspace_capabilities.py` | Writes the capabilities page of a workspace from its seat files and tool pages. Use it to list what a workspace can use. (script: `workspace_pages.py`) |
| `workspace_pages.py` | Builds `tools/CAPABILITIES.md` and `team/TEAM.md` of one workspace from the files on disk. Use it after you add a tool, skill, or seat. (user command) |
| `workspace_reports.py` | Builds the ops pages and the daily history of a workspace from its database, read only. Use it to see the business from rows. (user command) |
| `workspace_schematic.py` | Checks each workspace against the model and draws one page of the breaks. Use it to find a folder or table off the model. (user command) |

## ~/.foxrun/capture

| File | Description |
|---|---|
| `README.md` | Says what the capture part does and where its readers live. Use it to start reading `capture/`. (read by you) |
| `blueprint.sql` | Defines the captures table: one row for each saved web address. Use it to see what a capture records. (script: `base/build_database.py`, `lib/store.py`) |
| `capture-check` | Checks each capture row against its raw file; the file wins. Use it to find a row that drifted from its file. (user command) |
| `capture-read` | Reads one web address and prints one result as JSON; it saves media only under `--out`. Use it to see what a page holds before you save it. (user command) |
| `capture-write` | Saves a reader result: the raw file first, the row second, then one receipt. Use it to add a source to your library. (user command) |
| `capture.config.json` | Holds the two capture folders: `CAPTURE_ROOT` and `CAPTURE_STORE`. Empty on day one. Use it to set where captures go. (script: `lib/common.py`) |
| `defaults.json` | Holds the default values for this part's page templates. Empty today. (script: `base/install_workspace.py`) |
| `install.json` | Says that this part builds its table and copies no files. Its `needs` rows name each reader's outside program, why, and how to get it. Use it to change what the install does or lists for capture. (script: `base/install_workspace.py`, `base/published_pages.py`, `install.py`) |
| `lib/` | Holds the shared code for settings, hashes, raw files, and rows. Use it to change how a capture is stored. (script: `capture-check`, `capture-write`) |
| `readers/` | Holds one reader for each source: web, X, Instagram, YouTube, GitHub, Reddit, PDF. Use it to add a new source. (script: `capture-read`) |
| `tests/` | Tests the readers and the save steps with sample pages. Use them to prove a change did not break capture. (user command: `tests/run.sh`) |

## ~/.foxrun/config

| File | Description |
|---|---|
| `README.md` | Explains the settings in `config/`. Use it to find the local settings. (read by agents) |
| `orchestrate.local.json` | Names the Hermes profiles and portfolio paths this installation checks. Use it to add local checks without changing the product skill. (read by `skills/orchestrate/bin/orchestrate` · not in product) |
| `workspaces.local.json` | Lists your workspaces that keep their own layout, as `{"shape_exceptions": ["<workspace>"]}`. The shape check skips them; lint still runs there. With no file, only app folders are skipped. (script: `base/paths.py` · yours only; not in product) |
| `catalog.yaml` | Lists which skills publish and where each applies. Use it to give a skill to more workspaces. (script: `skillwright/tools/skill_catalog.py`, `agents/tools/agent_new.py`; copied from `templates/` at install) |
| `defaults.json` | Holds the default values for the config page templates. Empty today. (script: `base/install_workspace.py`) |
| `dream.json` | Sets the time of the memory job. Use it to change when it runs. (script: `memory/health.py`; copied from `templates/` at install) |
| `foxrun.code-workspace` | Your VS Code window: which folders open together and what stays hidden. Yours only; it never ships. (read by VS Code · not in product) |
| `gates.md` | The actions that wait for your yes: money, sends, outside changes, deploys. Agents read it before any of those. (read by agents before a gated action; made once at install, then yours) |
| `gates.local.md` | Your own gates, added to `gates.md`. (read by agents: `gates.md`; made once at install, then yours) |
| `git.md` | The rules for saving work in git: commit, push, merge, and what never to do. Agents read it before a git action. (read by agents; made once at install, then yours) |
| `git.local.md` | Your own git rules, added to `git.md`. (read by agents: `git.md`; made once at install, then yours) |
| `lint/` | Holds the lint rules and page specs: which pages each home needs, their form, and their allowed words. Use it to change a lint rule. (script: `base/lint.py`, `base/lint_gate.py`) |
| `models.yaml` | Names allowed and banned models per tier and runtime. Consumers read this file; squad roles own effort. (script: `base/agent_catalog.py`; copied at install) |
| `module-commands.json` | Which command runs each add-on module. Empty in the product, which ships no add-on module. (script: `base/module_commands.py`, through `base/workspace_capabilities.py`) |
| `modules.yaml` | Lists the core modules and the add-ons you turned on. Use it to see which modules this home has. (script: the installer; copied from `templates/` at install) |
| `naming.md` | Holds the front matter, naming, and record rules at the top of `SCHEMA.md`. Use it to change those rules, then rebuild. (script: `base/generate_pages.py`) |
| `optional-addons.tsv` | Lists the optional add-ons with what each needs, its license, its cost, and its tool page. Use it to change the add-on list. (script: `base/optional_addons.py`) |
| `owners.json` | Which agent owns each folder of the system home. A draft; the ruling puts this in each agent's file, and nothing reads this one. (no reader · not in product) |
| `person.json` | Holds your name, your workspaces, your default workspace, your runtime, and your leads. Use it to change who owns this install. (script: `base/person.py`; written at install) |
| `product-source.json` | Names the product folder of the last install or update. `foxrun.py update` uses it when you leave out `--source`. (script: `update.py`; written at install and update) |
| `squads/` | Your squad files (agent teams); nothing runs them yet. (no reader; `example.yaml` written at install) |
| `standing-seats.json` | Names the seats that keep a standing session, such as the Chief of Staff and the Architect. Use it to add a standing seat. (script: `work/standing.py`; copied from `templates/` at install) |
| `templates/` | Holds the first copy of each settings file and the portfolio pages. Use it to see the settings a new home starts with. (script: `install.py`, `base/install_system.py`) |
| `templates/profile/AGENTS.md` | Supplies the starter global contract; the installer keeps an existing profile contract. |
| `templates/workspace/AGENTS.md` | Supplies the workspace contract template. |
| `templates/workspace-lead/SKILL.md` | Supplies the generic workspace lead boot; install fills its paths and keeps a taken skill name. |
| `templates/chief/SKILL.md` | Supplies the chief seat boot; install fills the person name and keeps a taken skill name. |
| `templates/chief/replays/read-seat-boot.json` | Checks the chief seat boot reads. |
| `templates/architect/SKILL.md` | Supplies the architect seat boot; install fills the person name and keeps a taken skill name. |
| `templates/architect/replays/read-seat-boot.json` | Checks the architect seat boot reads. |
| `templates/keeper/SKILL.md` | Supplies the keeper seat boot; install fills the person name and keeps a taken skill name. |
| `templates/keeper/replays/read-purpose.json` | Checks the keeper seat boot reads. |
| `templates/toolsmith/SKILL.md` | Supplies the toolsmith seat boot; install fills the person name and keeps a taken skill name. |
| `templates/toolsmith/replays/read-purpose.json` | Checks the toolsmith seat boot reads. |
| `templates/skillwright/SKILL.md` | Supplies the skillwright seat boot; install fills the person name and keeps a taken skill name. |
| `templates/skillwright/replays/read-purpose.json` | Checks the skillwright seat boot reads. |
| `templates/scout/SKILL.md` | Supplies the scout seat boot; install fills the person name and keeps a taken skill name. |
| `templates/scout/replays/read-purpose.json` | Checks the scout seat boot reads. |
| `templates/adviser/SKILL.md` | Supplies the adviser seat boot; install fills the person name and keeps a taken skill name. |
| `templates/adviser/replays/read-purpose.json` | Checks the adviser seat boot reads. |
| `templates/workspace/home.md` | Supplies the workspace overview template. |
| `tools.yaml` | Your tool shelf: every tool, why you have it, and which workspaces get it. Change it to give a tool to more workspaces. (script: `base/make_workspaces_view.py`; `foxrun.py doctor` checks that it exists; copied from `templates/tools.yaml` at install) |
| `words.tsv` | Holds the reviewed words of the system, one row each, with group and meaning. Use it to change `GLOSSARY.md`. (script: `base/published_pages.py`, `base/generate_pages.py`) |

## ~/.foxrun/cron

| File | Description |
|---|---|
| `launchd/` | Holds `session-nightly.plist.template`, the nightly job with placeholders for the person's paths. Use it to see what the installer loads. (script: `cron/schedule.py`) |
| `README.md` | Explains the nightly job, its clock in `config/dream.json`, and how to turn it on or off. Use it before you change the schedule. (read by you) |
| `nightly.py` | Runs the nightly checks and asks macOS to alert on failure. Use its receipt to see failed steps and notification delivery. (cron 02:30 by default) |
| `watchdog.py` | Checks the nightly launchd label and receipt from a separate five-minute job. Use its alert receipt to prove a stopped or stale scheduler was detected. (cron watcher) |
| `tests/test_watchdog.py` | Tests measured launchd status, receipt age, alert delivery, and duplicate suppression. Use it before changing the watcher. (test) |
| `schedule.py` | Renders the job from its template and `config/dream.json`, writes it to `~/Library/LaunchAgents`, and loads it. Use it to turn the job on or to compare a job file. (script: `install.py`; user command) |
| `tests/` | Tests the nightly job and its schedule with a stub `launchctl`. Use them to prove a change did not break the clock. (user command) |

## ~/.foxrun/decisions

| File | Description |
|---|---|
| `README.md` | Gives the commands that list and show decisions. Use it to read a decision. (read by you) |
| `approve.py` | Plans, records, and lints the approval of a document draft, and recovers a half-done one. Use it to promote a draft after its approver said yes. (user command) |
| `blueprint.sql` | Adds no tables; it notes that decisions and approvals are in `work/blueprint.sql` today. Use it to know where those tables live. (script: `base/build_database.py`, `base/check_blueprints.py`) |
| `decisions.py` | Reads and changes decisions, and writes approvals for the work command. Approval writes preserve the supplied words exactly. (user command; script: `work/work.py`, `hooks/write_handoff.py`) |
| `defaults.json` | Holds the default values for this part's page templates. Empty today. (script: `base/install_workspace.py`) |
| `install.json` | Says that this part copies no files and builds no table of its own. (script: `base/install_workspace.py`, `install.py`) |
| `lint_replaces.py` | Lists open decisions that name a replacement but have no `replaces` value. Use it to find a ruling that is not linked to the one it replaced. (script: `memory/dream.py`) |
| `tests/` | Reserved for the tests of this part. Empty today. |

## ~/.foxrun/evals

| File | Description |
|---|---|
| `agents/` | Reserved for the agent test sets. Empty on day one. |
| `memory/` | Holds eleven memory evals and the runner `run.py`; each prints pass or fail with its cases. Use it to score the memory design. (user command) |

## ~/.foxrun/events

| File | Description |
|---|---|
| `README.md` | Says that this part records history and that the session hooks call `session_run.py`. Use it to find the session logger. (read by you) |
| `blueprint.sql` | Defines the events tables: changes, comments, attachments, receipts, runs. Use it to see what history the system keeps. (script: `base/check_blueprints.py`; checked by `tests/test_blueprint.py`) |
| `defaults.json` | Holds the default values for this part's page templates. Empty today. (script: `base/install_workspace.py`) |
| `history_action_map.csv` | Maps each kind of command to the history action, table, and load it records. Use it to change how a command shows in history. (script: `history_actions.py`) |
| `history_actions.py` | Reads the reviewed rules of `history_action_map.csv` for every writer of history. Use it so each command logs the same way. (script: `work/work.py`, `base/core.py`, `base/table.py`, `session_run.py`) |
| `history_proof.py` | Reads old history rows and freezes them in a bundle with a hash, without changing a source. Use it to prove a history move kept every row. (user command) |
| `import_log.py` | Imports old JSONL history into the changes table; it checks only unless you add `--write`. Use it once to move an old log. (user command) |
| `install.json` | Says that this part copies no files and builds no table of its own. (script: `base/install_workspace.py`, `install.py`) |
| `log.py` | Shows and adds history events through the work command. Use it to read or add what happened to a task. (user command; script: `work/work.py`) |
| `log_switch.py` | Reads an old `log.md` of a workspace into JSONL without changing it. Use it to move an old log into rows. (script: `skills/log`) |
| `session_run.py` | Logs each Claude and Codex session as a run on one standing task. Use it to see which sessions did work. (hook: session-start, session-end, through `hooks/claude/` and `hooks/codex/`) |
| `tests/` | Tests `blueprint.sql`. Use them to prove the events tables are right. (user command) |

## ~/.foxrun/hooks

| File | Description |
|---|---|
| `README.md` | Explains the hook commands in this folder. Use it to find the compact handoff check. (read by agents) |
| `after_compact.py` | Prints open handoff items after a compact. Use it to resume the unfinished work. (hook: after-compact) |
| `claude/` | Holds the Claude Code hooks. `session-start` and `after-compact` print the start page. `before-compact` checks the handoff. The two session scripts log each session. Use it to connect Claude Code. (hook: session-start, after-compact, before-compact, session-end) |
| `codex/` | Holds the same hooks for Codex. Use it to connect Codex. (hook: session-start, after-compact, before-compact, session-end) |
| `hermes/` | Holds the same three hooks for Hermes; they call `memory/session_start.py`. Use it to connect Hermes. (hook: session-start, after-compact, before-compact · Hermes is off on day one) |
| `start-rules.py` | Loads your soul and rules into every Claude and Codex session before its first reply, whatever folder it starts in. (hook: session-start) |
| `write_handoff.py` | Prints the handoff path a compact would reserve, without writing it. Use it to see where the next handoff goes. (hook: before-compact) |

## ~/.foxrun/memory

| File | Description |
|---|---|
| `lessons.py` | Reads active lessons for the workspace start page. Use it to load the lessons for an agent. |
| `lessons.sql` | Defines lesson rows and views. Use it to install the lesson reader tables. |
| `README-compile.md` | Explains the wiki compile command and its arguments. Use it to turn saved sources into topic pages. (read by you) |
| `README-search.md` | Says which command answers which search question: words, places, notes, and shared knowledge. Use it to pick the right search. (read by the Keeper and by you) |
| `README-shared-memory.md` | Explains how `foxrun.py start` builds the start page and keeps a copy in the run. Use it to learn what an agent reads at the start. (read by you) |
| `README.md` | Says what the memory part does. Use it to start reading `memory/`. (read by you) |
| `before_compact.py` | Checks the latest handoff of the workspace before a compact; the compact always goes on. Use it to catch a missing handoff. (hook: before-compact) |
| `blueprint.sql` | Defines the four memory tables: lessons, sources, evidence, and rollups. Use it to see what memory keeps as rows. (script: `base/check_blueprints.py`; checked by `tests/test_blueprint.py`) |
| `check.py` | Runs the link check and the handoff check with named inputs. Use it to find a broken link or a short handoff. (user command; cron 02:30 through `cron/nightly.py` on this Mac) |
| `compile.py` | Compiles saved sources into cited topic pages and research answers, with no model and no network. Use it to grow the wiki from your sources. (user command; script: `dream.py`) |
| `defaults.json` | Holds the default workspace name for this part's page templates. (script: `base/install_workspace.py`) |
| `dream.py` | Runs the memory job: a code half that builds pages and exports, then a model half that only proposes. Use it to keep memory fresh each night. (user command; cron 02:30 through `cron/nightly.py` on this Mac) |
| `handoff_check.py` | Reads a session transcript and checks that the handoff covers it. Use it to catch work a handoff left out. (script: `before_compact.py`, `check.py`, `dream.py`) |
| `health.py` | Reports memory health from the job receipts and lead beats, with no database. Use it to see that the memory job ran. (script: `check.py`, `dream.py`, `start_context.py`) |
| `install.json` | Marks this part for install. It writes no pages; the wiki starter pages are in `base/templates/wiki/`. (script: `base/install_workspace.py`, `install.py`) |
| `kept.py` | Freezes one kept reply and links it by topic; a frozen reply never changes. Use it to save an answer worth keeping. (user command; script: `dream.py`) |
| `link_cases.json` | Holds sample links and the result each must give. Use it to test the link rewriter. (read by the memory tests) |
| `link_check.py` | Checks that each relative link in a page opens from the page's own folder. Use it to find a broken link. (script: `check.py`) |
| `markdown_links.py` | Finds every link in a Markdown page with its exact place in the text. Use it to change a link without touching other text. (script: `compile.py`, `link_check.py`) |
| `model_proposals.py` | Sends one request to the model in `config/models.yaml` and keeps the answer only as a proposal. Use it for the model half of the memory job. (script: `dream.py`) |
| `session_start.py` | Finds the workspace, seat, and function of a session from its start data. Use it to give a session the right start page. (script: `foxrun.py`; hook: session-start, after-compact through `hooks/hermes/`) |
| `source_digest.py` | Makes one hash of captured files and folders, without following links. Use it to prove a source did not change. (script: the memory evals) |
| `start_context.py` | Builds shared start pages, the seat part, and the function part, and keeps the exact output in its run. Puts pending ownership alarms first for their owner and configured leads in the existing open-task list. (script: `foxrun.py start`, `session_start.py`) |
| `state.py` | Builds and shows `STATE.md`, the page an agent reads at the start, from the rows; its question table names a view or a `foxrun.py` command for each question. Use it to rebuild the state page or check it. (user command; script: `dream.py`, `work/work.py`, `foxrun.py`) |
| `tests/` | Tests the memory tables, the job's words, the link scanner, the source hash, the state page, and the seat part. Use them to prove a change did not break memory. (user command) |
| `turn_tag.py` | Tags your typed turns from the source-note list with recorded Jev judgments. Use it to sort turns by what they ask. (user command (check)) |

## ~/.foxrun/runs

| File | Description |
|---|---|
| `generated/` | Holds the agent files `agents/tools/agent_new.py` makes when no workspace is named. Do not edit them by hand. (script: `agents/tools/agent_new.py`) |
| `<date>-<name>/` | Keeps the working files of one run, such as its start page. Use one to see what that run read and wrote. (written by agents during a run · not in product) |
| `nightly-watchdog-state.json` | Records the last watchdog check and alert state. `cron/watchdog.py` writes it; operators read it to diagnose missed nightly runs. (not in product) |

## ~/.foxrun/small-talk

| File | Description |
|---|---|
| `pyproject.toml` | Defines Small Talk Python dependencies and test settings. `uv` reads it to install and test the service. (source: the add-on's own `pyproject.toml` · not in product) |

## ~/.foxrun/skills

| File | Description |
|---|---|
| `.release-manifest.json` | Records the active skill release, its source owners, and its checks. Use it to verify the shelf version. (script: `skillwright/tools/skill_ship.py`) |
| `log/` | Holds the log skill: write one receipt to the history of a workspace at a material moment. Use it to record a decision or shipped work. (read by agents) |
| `capability/replays/README.md` | Names the released capability replay and its vetting check. (read by agents) |
| `capability/replays/read-vet-before-adopt.json` | Checks vetting and the exact install fields before adoption. (script: `skillify`) |
| `orchestrate/` | Holds the released runtime router and its checks. Use it to route work across runtimes. (script: `skillwright/tools/skill_ship.py`) |
| `to-tickets/` | Holds the to-tickets skill: break a plan into tickets, each with what blocks it. Use it to turn a plan into tracked work. (read by agents, on your command) |

## ~/.foxrun/skillwright

| File | Description |
|---|---|
| `skills/README.md` | Explains the product skill sources. Use it to find their purpose lines. (read by agents) |
| `config/` | Holds `manifest.json`, which lists the product skills, where each lives, and its owner (`source: product`). Use it to see which skills the product owns. (script: `tools/skill_ship.py`) |
| `manifests/` | Holds `shipped.yaml`, the list of skills and add-on lists that ship. Use it to see what a new install gets. (script: `base/install_workspace.py`, `base/pack_policy.py`, `install.py`) |
| `retired/` | Keeps skills that are no longer in use. Empty on day one. (written at install) |
| `skill-releases/` | Keeps the released versions of skills. Empty on day one. (script: `tools/skill_ship.py`) |
| `skill-state/` | Keeps the state of the release tool. Empty on day one. (script: `tools/skill_ship.py`) |
| `skills/` | Holds the installed copy of the product skills: `log`, `to-tickets`, and `capture`. Use it to see the product skills. Do not edit them here; an update replaces them. To change one, copy it under a new name into `~/foxrun/skillwright/skills/`. (script: `tools/skill_ship.py`) |
| `tests/` | Tests the release tools and the skill rules. Use them to prove a change did not break a release. (user command) |
| `tests/README.md` | Names the purpose of Skillwright release tests, including workspace view refresh. (read by agents) |
| `tests/test_workspace_view_refresh.py` | Proves that a skill release refreshes workspace pages. (user command) |
| `skills/capability/replays/README.md` | Names the capability replay and its install vetting check. (read by agents) |
| `skills/capability/replays/read-vet-before-adopt.json` | Checks that capability asks for vetting before an install plan. (script: `skillify`) |
| `tools/` | Holds the tools that check, back up, route, and release skills. Use them to release a skill to `~/.foxrun/skills` and `~/.agents/skills`. (user command; `skill-ship-trigger.sh` runs after a catalog change) |
| `workflows/` | Holds the shared workflows that connect many skills. Ships two starters, each a `.yaml` file that runs and a `.md` page that explains it: `review` and `research`. Personal workflows have source in `<portfolio>/skillwright/workflows/` and release to the installed shelf. Use them to run a team as a graph with a loop. (script: `work/flow.py`) |


## ~/.foxrun/skillwright/skills/handoff

| File | Description |
|---|---|
| `README.md` | Lists the handoff source files and their purposes. |
| `SKILL.md` | Defines the existing handoff steps and boot sequence. |
| `bin/handoff-boot` | Selects the seat handoff sequence without blocking a session. |
| `bin/handoff-path` | Reserves a handoff path without overwriting an existing note. |
| `bin/handoff-precompact` | Writes a pre-compaction note from the settlement check. |
| `references/boot-hook.md` | Holds the existing optional boot hook registration instructions. |
| `references/precompact-hook.md` | Holds the existing optional pre-compaction hook instructions. |
| `replays/boot-pick-seat.json` | Checks that each seat receives its own newest handoff. |
| `replays/precompact-dirty-dry-run.json` | Checks the read-only settlement warning replay. |
| `replays/refuse-bad-subject.json` | Checks that invalid handoff subjects are refused. |
| `replays/reserve-first-path.json` | Checks the first handoff path reservation. |
| `tests/__init__.py` | Marks the handoff test package. |
| `tests/test_handoff_boot.py` | Checks handoff selection, sequence, and safe empty starts. |
| `tests/test_handoff_path.py` | Checks timestamps, reservations, and path collisions. |
| `tests/test_handoff_precompact.py` | Checks pre-compaction notes and settlement warnings. |
| `tests/fixtures/clean.jsonl` | Supplies a synthetic transcript with a recorded settlement. |
| `tests/fixtures/dirty.jsonl` | Supplies a synthetic transcript with an unrecorded settlement. |
| `tests/fixtures/created.jsonl` | Supplies a synthetic task creation transcript. |
| `tests/fixtures/tracker.sql` | Builds the synthetic handoff test tracker. |

## ~/.foxrun/skills/handoff

The installer copies the product handoff source to the released and runtime shelves.
It fills `@Person@` and keeps executable commands. Existing skill names stay untouched.

## ~/.foxrun/skillwright/skills/orchestrate

| File | Description |
|---|---|
| `README.md` | Explains the route skill's files. Use it to find its commands and checks. (read by agents) |
| `SKILL.md` | Gives agents the route rules. Use it before handing work to another runtime. (read by agents) |
| `bin/README.md` | Explains the route commands. Use it to find the resolver and brief checker. (read by agents) |
| `bin/brief-check` | Checks source anchors in a second opinion brief. Use it before a reviewer starts. (user command) |
| `bin/orchestrate` | Resolves a route and checks old routes. Use it for cross runtime work. (user command) |
| `replays/README.md` | Explains the saved replay cases. Use it to identify each case. (read by agents) |
| `replays/anchored-brief.json` | Holds a brief with all source anchors. Use it to prove brief-check accepts it. (script: tests) |
| `replays/missing-decisions.json` | Holds a brief without decisions. Use it to prove brief-check rejects it. (script: tests) |
| `replays/read-hosted-without-herdr.json` | Holds the missing host case. Use it to check the route answer. (script: tests) |
| `replays/route-codex-to-claude.json` | Holds a one shot route case. Use it to check the command. (script: tests) |
| `replays/t289-real-panel.json` | Holds a complex brief without owning lead sources. Use it to check that gap. (script: tests) |
| `tests/README.md` | Explains the tests. Use it to find the required checks. (read by agents) |
| `tests/__init__.py` | Marks the test package. Use it to load shared test helpers. (script: tests) |
| `tests/acceptance.md` | Lists manual desktop checks. Use it to prove live route behavior. (read by agents) |
| `tests/resolver_baseline.json` | Holds saved route outputs. Use it to compare resolver changes. (script: tests) |
| `tests/support.py` | Loads the resolver and sibling commands. Use it in the tests. (script: tests) |
| `tests/test_brief_check.py` | Checks source anchors in briefs. Use it to test the checker. (user command) |
| `tests/test_codex_thread.py` | Checks the Codex thread helper. Use it to test thread setup. (user command) |
| `tests/test_doctor.py` | Checks retired routes and local profile scope. Use it to test doctor. (user command) |
| `tests/test_resolver.py` | Checks every route and the saved baseline. Use it to test routing. (user command) |

## ~/.foxrun/skills/orchestrate

The released shelf carries the same files as `skillwright/skills/orchestrate`. Skillwright writes them from that source.

## ~/.foxrun/tests


| File | Description |
|---|---|
| `test_secret_check.py` | Tests fake secret blocking, staged-only reads, safe output, history bounds, narrow metadata and fixture allowances, and speed. Use it to verify the commit check. (user command) |
| `README.md` | Explains the launcher, installer, and workspace tests. Use it to find the test commands. |
| `test_after_compact.py` | Checks that compaction shows open handoff items and active lessons. |
| `test_day_one.py` | Checks a first install and first task with isolated sample homes. |
| `test_foxrun.py` | Checks launcher commands and doctor results in isolated test homes. |
| `test_install.py` | Checks installer files and settings in isolated test homes. |
| `test_update.py` | Checks upgrades from a committed older install, personal bytes, reruns, path refusals, migration failure, rollback, and competing writers. |
| `test_seat_boots.py` | Checks all seven seat boot templates, person names, and taken skill names. |
| `test_seat_resolution.py` | Checks personal seat priority, every seat reader, and install protection in temporary homes. |
| `test_start_workspace_db.py` | Checks that start selects the workspace database without exposing owner rows. |

## ~/.foxrun/tools

| File | Description |
|---|---|
| `bin/` | Holds optional browser, Instagram, and tweet reader scripts in the source folder. The default install excludes them. |
| `bin/browser-humanize.js` | Supplies timing and movement helpers for browser automation. Optional: copy it from the source folder; the default install excludes it. |
| `bin/ig-read` | Reads Instagram posts, comments, profiles, and transcripts through ScrapeCreators. Optional: copy it from the source folder; the default install excludes it. |
| `bin/tweet-read` | Reads one tweet through the X API. Optional: copy it from the source folder; the default install excludes it. |
| `CAPABILITIES.md` | Lists the tools and skills declared in the system home, from `config/tools.yaml` and the tool pages. Use it to see what an agent can use. (builder: `base/build_caps.py`; checker: `agents/tools/render_capabilities.py`) |
| `cli/`, `external-app/`, `mcp/`, `plugin/`, `schedule/`, `service/` | Each holds one page for each tool of that kind. Product pages ship in `cli/`, `mcp/`, `plugin/`, and `service/`: Foxrun commands and optional add-on guides (owner product; an update replaces them). Add your own pages beside them (owner person). Use one to learn or describe a tool. (read by agents · your pages are not in product) |
| `tools/cli/bm-render.md` | Mermaid diagrams as SVG or terminal text. Optional add-on guide. |
| `tools/cli/ffmpeg.md` | Convert and inspect audio and video. Optional add-on guide. |
| `tools/cli/repomix.md` | Pack repository files for an agent to read. Optional add-on guide. |
| `tools/cli/remindctl.md` | Apple Reminders from the terminal. Mac only. Optional add-on guide. |
| `tools/cli/summarize.md` | Summarize a web page, video, audio, or file. Optional add-on guide. |
| `tools/plugin/codex-at-openai-codex.md` | Codex reviews and tasks from Claude Code. Optional add-on guide. |
| `tools/cli/runtime-session-search.md` | Find past agent sessions by words or native ID. Foxrun interface guide. |
| `tools/cli/agent-secret-read.md` | Read one approved secret reference for a child process. Foxrun interface guide. |

## ~/.foxrun/wiki

| File | Description |
|---|---|
| `concepts/`, `entities/` | Hold the knowledge pages of the system home: one page for each idea, and one for each named thing. Empty on day one. (read by agents) |

## ~/.foxrun/work

| File | Description |
|---|---|
| `README-approve.md` | Explains the document approval command and what it does not do. Use it to promote a draft. (read by you) |
| `README-flow.md` | Explains the flow runner and gives its commands. Use it to run or check a workflow. (read by you) |
| `README-history-proof.md` | Explains the history proof helper and its limits. Use it to prove a history move. (read by you) |
| `README-standing.md` | Explains how to start a standing seat and how it keeps one conversation. Use it to start the Chief of Staff or the Architect. (read by you) |
| `README-work-relationships.md` | Explains the audit of the two proposed side tables for links and goal mirrors. Use it to check them on a copy. (read by you) |
| `README.md` | Says what the work part does. Use it to start reading `work/`. (read by you) |
| `apply-incidents.sql` | Adds the bug, incident, and record link tables to a work database. Use it to track bugs and incidents. (script: `apply_incidents.py`) |
| `apply-program-control.sql` | Adds the program, theme, and run tables and the program plan view. Use it to plan work by program. (script: `apply_program_schema.py`) |
| `apply.sql` | Upgrades an existing work database safely; you can run it more than once. Use it to bring an old tracker up to date. (script: `apply_program_schema.py`, `base/core.py`) |
| `apply_incidents.py` | Backs up the database, then adds, checks, exports, or removes the bug and incident tables. Use it to add them safely. (script: `work.py`) |
| `apply_program_schema.py` | Adds the program-control tables to a work database. Use it before you plan by program. (script: `work.py`, `program.py`) |
| `approve_rehearsal.py` | Practices a document approval on labeled sample files; it gives no real approval. Use it to test the approval steps. (user command) |
| `blueprint.sql` | Defines the work tables: goals, measures, programs, themes, tasks, links, and more. Use it to see what a task row holds. (script: `base/build_database.py`, `base/check_blueprints.py`) |
| `defaults.json` | Holds the default values for this part's page templates. Empty today. (script: `base/install_workspace.py`) |
| `fixtures/` | Holds two old database shapes for the upgrade tests. (script: tests) |
| `flow.py` | Runs a flow or a workflow and says where a run stands. Use it to run many skills in order with your approvals. (user command) |
| `flow_yaml.py` | Reads a small part of YAML for the flow runner, with no extra package. (script: `flow.py`) |
| `hooks/` | Holds the notes that show how to connect the session hooks in Claude Code and Codex. Use it to turn on session logging. (read by you) |
| `install.json` | Says that this part builds its tables and copies no files. (script: `base/install_workspace.py`, `install.py`) |
| `lessons.py` | Reads the open lessons, or files one lesson through its table command. Use it to keep what went wrong from happening again. (user command) |
| `load_history_actions.py` | Imports only blank old tracker actions into a practice copy; existing history stays. Use it once for that move. (user command) |
| `night_work_fixtures.py` | Makes made-up tracker data for small tests of the work command. (script: tests) |
| `program.py` | Prints the program plan, the open runs, and the inbox, and picks the next task in a stream. Use it to see where a program stands. (user command; script: `foxrun.py`) |
| `standing.py` | Starts a standing seat and binds it to its runtime session on later wakes. Use it to keep one durable agent. (script: `foxrun.py standing`) |
| `templates/` | Reserved for work page templates. Empty today. |
| `tests/` | Tests the work command and its helpers. Use them to prove a change did not break task writes. (user command) |
| `work/tests/test_ownership_alarm.py` | Tests tracker alarms, lead visibility, clearance reasons, a second reviewer, event history, exact-path checks, tracker selection, and rollback on fake data. (user command) |
| `tests/test_flow_workers.py` | Checks flow workers with fake runtimes and an isolated home containing the model resolver and policy. (test command) |
| `tests/test_work.py` | Checks tracker commands, including exact preservation of supplied approval words. (test command) |
| `work.py` | Creates, claims, updates, and closes tasks, and starts and ends runs. Logs ownership alarms and clearings in the existing tracker, and checks their clearance. (user command; script: `foxrun.py`, `memory/dream.py`, `events/session_run.py`, `base/ownership.py`) |
| `work_relationships.py` | Audits the proposed link and goal mirror tables on a copy, read only by default. Use it before that change goes live. (user command) |

## ~/.foxrun/hooks/git

| File | Description |
|---|---|
| `README.md` | Explains shared hook setup and preservation. Use it before changing Git settings. (read by agents) |
| `post-commit` | Runs the original post-commit hook. Use it to preserve repository checks. (hook: post-commit) |
| `post-merge` | Runs the original post-merge hook. Use it to preserve repository checks. (hook: post-merge) |
| `pre-commit` | Checks staged secrets and runs the original hook. Use it to preserve repository checks. (hook: pre-commit) |

| `work/tests/fixtures/personal-workflows/vote.yaml` | Preserves the personal vote gate regression test, build-only. |
| `work/tests/fixtures/personal-workflows/README.md` | Names the personal vote fixture and its build-only scope. |

## Workflow release files

| File | Purpose |
| --- | --- |
| `skillwright/tools/workflow_ship.py` | Releases a workflow from source to the shelf, or promotes a local workflow, with hashes and checked backups. |
| `skillwright/tools/README.md` | Names the workflow release tool and its state files. |
| `skillwright/workflows/README.md` | Explains the five pieces, workflow homes, names, and the release command. |
| `skillwright/tests/test_workflow_ship.py` | Proves workflow release, promotion, name approvals, backup, drift refusal, and dry-run behavior in temporary homes. |
| `work/tests/test_workflow_homes.py` | Proves local, shelf, and product precedence and real starter bindings without starting models. |
