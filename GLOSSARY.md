---
type: glossary
workspace: system
timestamp: 2026-10-25T03:50:26-04:00
---
# Glossary: system

Generated from `config/words.tsv`. Change the rows, then rebuild.



## In the system home

| Word | Meaning | Where | Source |
|---|---|---|---|
| Agent roster | The shared roster in the system home. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Base | Builds the database and installs workspaces. Builds and checks pages. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Cron | The clock that starts scheduled work. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Hook | A trigger during a runtime session. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Module | A pack with its own tables, command, and templates. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Raw | Outside material kept as source evidence. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Resolver | The rules that name the source and writer for a fact. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Run | A row, a system trail, and a workspace report. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Schema | The tables and naming rules. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Skill | A procedure an agent follows for a task. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Skillwright | The agent and workshop that keep the skills. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Start page | The page an agent reads at the start. |  | Current build GLOSSARY.md; 10.12 glossary split |
| System home | The installed Foxrun code, shared settings, and database. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Wiki | Knowledge pages that cite outside material. |  | Current build GLOSSARY.md; 10.12 glossary split |
## In the portfolio

| Word | Meaning | Where | Source |
|---|---|---|---|
| Atlas | The library and default home of a capture. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Library | The knowledge in Atlas and workspace wikis. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Portfolio | The folder that contains your workspaces. |  | Current build GLOSSARY.md; 10.12 glossary split |
## In each workspace

| Word | Meaning | Where | Source |
|---|---|---|---|
| History | Frozen work, handoffs, snapshots, and run reports. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Notes | Living pages, one per topic. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Ops | Pages that show the business from source rows. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Specs | Living pages for things being built. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Team | The agents that work in one workspace. |  | Current build GLOSSARY.md; 10.12 glossary split |
## No one place

| Word | Meaning | Where | Source |
|---|---|---|---|
| Catalog | The list that controls where skills apply. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Core | The system parts every install includes. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Dream | The name chosen for the memory job. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Feeder | Code reads an outside source and refreshes its mirror on a schedule. It ships with the add-on; the outside system owns the facts; implementations can change without changing tables. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Mirror | An outside system owns these rows; a feeder refreshes them one way; local users never edit copied facts. Keep each outside ID and row age; keep local additions in a separate table linked to the mirror. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Report | Presents views and trends for a person; it owns no data and is not a database type. Its skill generates it and records runs in history; keep an exact rendered page in `outputs/` when needed. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Snapshot | A kept reply in its own frozen file. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Table | Holds rows that Person and authorized agents write and edit. The local writer accepts field changes under their rules; other surfaces submit requests. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Trend | Holds dated observations that a schedule appends and nobody changes. Its writer adds rows with an `as_of` date to preserve values for comparison over time. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Trigger | A moment that fires a command. |  | Current build GLOSSARY.md; 10.12 glossary split |
| View | A saved database query reads existing rows; the database computes results without owning separate business data. Its module blueprint ships it; skills call it by name; agents propose it; Person approves it through shared creation. |  | Current build GLOSSARY.md; 10.12 glossary split |
| Workspace | A place for one business or body of work. |  | Current build GLOSSARY.md; 10.12 glossary split |
## Agents and work

| Word | Meaning | Where | Source |
|---|---|---|---|
| Orchestration | Directing work across agents and runtimes, retrieving results, and managing the lifecycle of delegated work. Native runtime paths and Herdr are possible adapters; neither defines the whole capability. |  | Ruled |
| Multi-Agent Run | One lead runs several agents from one brief, then reviews and closes their work. |  | Ruled |
| Agent | One identity on one runtime: a Hermes profile, a Claude subagent (`.claude/agents/*.md`), or a Codex custom agent (`.codex/agents/*.toml`). The same persona on two runtimes (e.g. the Keeper) is two agents that share a name. |  | Ruled |
| Agent Definition | Its own object, seven dimensions from the Anatomy of an Agent: model, contract, capabilities, stores, anchor, triggers, guardrails. Links to many Capability Records. ADR 0005. |  | Ruled |
| Capability | One usable thing in eight categories: Skill, CLI, MCP, Plugin, Service, Connection, Hook, Script. |  | Ruled |
| Capability Record | One object for everything an agent can use: type is skill, cli, mcp, plugin, or automation; trigger is on demand, event, or schedule; connection is a field naming the outside account. Service, hook, and script are all automation. ADR 0005. |  | Ruled |
| Scope | Where an agent or capability belongs: Global (home-directory dotdirs) or one workspace. For Claude/Codex, scope is the literal location of the definition file; for Hermes, scope is the lane the profile's working directory points at. |  | Ruled |
| Applies To | The affected boundary on a decision, task link, or external system record. |  | Ruled |
## Memory words

| Word | Meaning | Where | Source |
|---|---|---|---|
| Records | Facts held as rows that authorized writers can change. |  | Ruled; object_types/lens=records |
## Setup words

| Word | Meaning | Where | Source |
|---|---|---|---|
| Collection | A collection is a named, marketable group of related object types inside a module. A folder or table that holds one object type is not a collection. |  | Ruled |
## Model words

| Word | Meaning | Where | Source |
|---|---|---|---|
| Portfolio | A portfolio contains workspaces and shared material. It sets the broadest scope in this model. |  | Ruled |
| Workspace | A workspace is a portable operating home for a business or another continuing body of work. |  | Ruled |
| Function | A function is a continuing seat of responsibility with an owner and a scorecard. It owns recurring work inside an organization. |  | Ruled |
| Subfunction | A subfunction is a function with a parent. It adds no container type. |  | Ruled |
| Kit | A kit is a module someone else built, used as it ships. Keep its native structure and names. |  | Ruled |
| Subcollection | A subcollection is a collection with a parent collection. |  | Ruled |
| Tier | A tier says which workspaces receive a module. The three tiers are base, workspace type, and add-on. |  | Ruled |
| You install a module, you open a collection (rule) | You install a module. You open a collection. |  | Ruled |
| Object type | An object type names a distinct thing the business tracks, with its own purpose and rules. |  | Ruled |
| Supertype | A supertype supplies shared fields and rules across distinct object types. It needs shared fields and a shared rule or query. |  | Ruled |
| Subtype | A subtype is an object type considered in relation to its supertype. This relationship describes the object, not nested placement. |  | Ruled |
| Link | A link connects related records or files. |  | Ruled |
| Playbooks | Playbooks explain how work must run. They always live in files, such as skills, procedures, and agent rules. |  | Ruled |
| Records | Records hold changing business state. A linked file can hold the readable body while the row owns current state. |  | Ruled |
| History | History preserves what happened or what was kept at a particular time. It uses frozen files or rows. |  | Ruled |
| A file that claims a status is wrong (rule) | The database owns current state; a file holds the body or evidence. Generated reports display state from views without owning it. |  | Ruled |
| JSONL | JSONL stores one JSON record per line. Exported state is a copy; the local database remains authoritative. |  | Ruled |
| Table | A table holds rows that the person and authorized agents write and edit. The local writer accepts changes under the rules for each field. |  | Ruled |
| Mirror | A mirror holds a local copy of rows that an outside system owns. The feeder refreshes those rows; local users never edit the copied facts. |  | Ruled |
| Trend | A trend holds dated observations that a schedule appends and nobody changes. These rows preserve values for comparison over time. |  | Ruled |
| View | A view is a saved database query that reads existing rows without owning separate business data. The database computes its result. |  | Ruled |
| Report | A report presents views and trends for a person. It holds no data of its own and is not a database type. |  | Ruled |
| Feeder | A feeder is code that reads a source and refreshes its mirror on a schedule. The feeder writes the mirror rows; the outside system owns their facts. |  | Ruled |
| Contract | A contract defines rules an agent must follow. Business agreements use agreement, whose row links the draft or signed document. |  | Ruled |
| Template | A template is a reusable file that supplies a starting shape for its user's output. It travels with the skill or module that uses it. |  | Ruled |
| Decision | A decision records a choice, its reason, and its current standing. Its row holds state, scope, date, and what it replaces. |  | Ruled |
| Approval | An approval records the person's response to an exact version of something. Approval does not prove sending, external acceptance, delivery, or payment. |  | Ruled |
| Activity | Activity records who changed a record, what changed, when, and from where. Every accepted change leaves an append-only row. |  | Ruled |
| Tag | A tag names an approved subject shared by related material. Approved tags live as rows, with one list per workspace. |  | Ruled |
| Topic | A topic is the subject that material is about. Its wiki page gathers tagged material across object types in date order. |  | Ruled |
| Topic rule | The topic rule lets the person name the subject while the agent chooses the correct object type. A choice becomes a decision row; a to-do becomes a task row. |  | Ruled |
| Workspace type | A workspace type names the business domain that determines its shared module needs. The workspace-type tier adds to base. |  | Ruled |
| Program | A program is a large, coordinated effort with one record that everyone reads and updates. |  | Ruled |
| Work stream | A work stream is a project that belongs to a program; the same table holds both. A standalone row in that table is called a project. |  | Ruled |
| Project | A project delivers a defined result and always ends. Its row owns current state. |  | Ruled |
| Rock | A Rock is a goal with horizon quarter. It needs no separate milestone object. |  | Ruled |
| Task | A task is one piece of work with an owner and a completion check. A task can stand alone. |  | Ruled |
| Schedule | A schedule defines when recurring work runs. It supplies the timing for a workflow or feeder. |  | Ruled |
| Measure | A measure is a named number with an owner and target for a function or goal. The blueprint stores its definition in measures and dated observations in measure_history. |  | Ruled |
| Scorecard | A scorecard groups measures so its owner can compare results with targets. A function uses its scorecard to track ongoing responsibility. |  | Ruled |
| Replaces | Replaces names the older record or decision that the current record replaces. |  | Ruled |
| Backlog | Backlog means the work is decided but not planned now. |  | Ruled |
| To do | To do means the work is next and has not started. |  | Ruled |
| In progress | In progress means the work started but is not finished. |  | Ruled |
| Blocked | Blocked means the work cannot continue until a named condition changes. |  | Ruled |
| Module | A module is a group of tables in the core database. Every core table belongs to exactly one module. |  | Ruled |
| Collection | A collection is a named, marketable group of related object types inside a module. A folder or table that holds one object type is not a collection. |  | Ruled |
| Knowledge | Knowledge holds what is known. It may live in rows when agents query and cite it. |  | Ruled |
| Database | Each install has one core database, with every table once. Rows owned by a business carry a workspace column. |  | Ruled |
| Organization | An organization is a people-module record. It is outside the work ladder. |  | Ruled |
| Theme | A theme is a topic tag that can sit on anything. A program may use its topics as headlines to group work streams. |  | Ruled |
| Goal | A goal is the why at the top of the work ladder. Measures and their dated observations judge it. |  | Ruled |
| Subtask | A subtask is a child row under a task, inside or outside a program. It has one parent and cannot have its own child. |  | Ruled |
| Workflow | A workflow is a YAML file that flow.py runs. Each workflow also has a short Markdown page that explains it in plain words. |  | Ruled |
| Run | A run is one job an agent or tool does. Its row is created at start and updated at end with status, result, and cost. |  | Ruled |
| Standing task | A standing task holds each day's run of purely recurring work. It is not a new task per day. |  | Ruled |
| Replaced | Replaced is the status of a record that a newer record replaces. The newer row stores the replaces link to the older row. |  | Ruled |
| Done | Done means the work is checked and nothing remains to ship. Finished work that is not yet checked or shipped is in-review. |  | Ruled |
