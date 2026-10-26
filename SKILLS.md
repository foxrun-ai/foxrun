# Skills

Foxrun ships 62 skills. A skill is the steps your agent follows for one job. Type the command, or ask for the job in your own words.

## Run the work

| Command | What it does |
|---|---|
| `/bug` | Open, show, update, link, or close a bug in the tracker, with a duplicate-title check before every open. |
| `/checkpoint` | Save a light checkpoint mid-session as one task comment: where the work stands and the next move. |
| `/decision` | Record a ruling as one decision row in the tracker, with the exact words of the person, after a duplicate check. |
| `/goal` | Create or show a goal row in the tracker and tie tasks to it, with a duplicate-title check before every create. |
| `/orient` | Orient a session at its start: read the start page, then say where we stand, what needs the person, and the next move, in three short lines. |
| `/program` | Create or show a program and its themes in the tracker as a plan, with a duplicate-name check before every create. |
| `/spec` | Write a spec to the owning workspace's specs/ folder from what the session already settled, with no new interview. |
| `/stream` | Create, show, or rename a work stream in the tracker with a duplicate-title check before every create. |
| `/task` | Create, show, claim, finish, or move a task in a tracker with a duplicate-title check before every create. |
| `/close` | Close a working session on Foxrun: sweep a named folder, land missing receipts, place the session's work on tasks, file each yes and ruling as a row, write the handoff, and rebuild the start page. |
| `/decide` | Decide one choice through a door check and one resolver: two-way door, the 4-step, the algorithm, inversion, hell yes or no, and kill criteria. |
| `/flow` | List, check, run, and move forward graphs and loops with work/flow.py: the shipped review, research, and vote workflows, or any flow.yaml. |
| `/grill` | Grill the person on a plan, decision, or idea, in rounds, until every branch is decided. |
| `/handoff` | Write the restart baton for the next session: a thin, frozen note that points at live state in the database and holds only what rows cannot. |
| `/log` | Write one receipt to the owning workspace's history at a material moment: a decision, a direction change, shipped work, a material source, or a blocker. |
| `/program-control` | Control tracked work in a Foxrun workspace tracker: find it, check for duplicates, claim tasks, record runs and evidence, report defects, and close out on evidence. |

## Agents

| Command | What it does |
|---|---|
| `/foxrun-help` | Answer how Foxrun does something from its own pages: the nearest AGENTS.md first, then DOCUMENTATION.md, and name the file and section used. |
| `/foxrun-setup` | Install the Foxrun core when it is missing, or rerun the setup again, all of it or one part. |
| `/push` | Turn on push discipline for the rest of the session: take each next step that is obvious and yours without being asked, and end every reply with the work done or a named owner. |
| `/queue` | Queue worker results for review and report the count in a line: hold each finished result, and list them on request. |
| `/thread` | Make an agent thread in Claude or Codex: a titled session that starts in its workspace and boots its seat, in the Claude app, a terminal, or Codex. |
| `/workspace` | Make a new workspace or check one in the Portfolio: plan the create-only install, apply it on a yes, and run the read-only structure check. |
| `/adviser` | Take the Adviser seat and run its boot reads. |
| `/agent-new` | Create or update an agent worker from any runtime: write its identity file, render its Claude and Codex capes, and list the team. |
| `/architect` | Take the Architect seat: read the seat file named by the start command and run its boot reads, then answer as the Architect until @Person@ drops the seat. |
| `/capability` | Search, compare, vet, understand, adopt, and guide agent capabilities such as skills, CLIs, MCP servers, and libraries. |
| `/chief` | Take the Chief of Staff seat: read the seat file named by the start command, run its boot reads, then answer as the Chief of Staff until @Person@ drops the seat. |
| `/jev` | Run typed Jev judgments through OpenRouter, then log them: a choice, a score, or a yes or no, stored in the tracker. |
| `/keeper` | Take the Keeper seat and run its boot reads. |
| `/orchestrate` | The one menu for handing work between Claude, Codex, and Hermes. |
| `/runtime-session-search` | Find a past agent session by words or id in Claude, Codex, or Hermes (every profile), read its final reply, and return the native session id so orchestrate can resume it. |
| `/scout` | Take the Scout seat and run its boot reads. |
| `/skill-ship` | Ship a checked skill from the skillwright main branch to the shared shelf, with no release id to type, then prove it in a fresh session. |
| `/skillify` | Turn text, a session, or a Hermes skill into a Dojo skill that passes the skill law, and check any skill against that law. |
| `/skillwright` | Take the Skillwright seat and run its boot reads. |
| `/toolsmith` | Take the Toolsmith seat and run its boot reads. |

## Memory and knowledge

| Command | What it does |
|---|---|
| `/lesson` | Add, promote, or prune a lesson in the tracker. |
| `/note` | Write a note to the notes/ folder of the owning workspace, with the managed frontmatter and a lint check before the write. |
| `/wiki` | Add, refresh, or check a workspace wiki page: the memory step for what a thing is. |
| `/capture` | Capture one link into raw: read the URL with the capture tool and save it as a raw file in Atlas and one captures row. |
| `/glossary` | Sharpen and record the words of a project as you design: challenge fuzzy terms, test edge cases, write approved glossary rows through the checked writer, and offer an ADR for a hard trade-off. |
| `/recall` | Recall what Foxrun knows: walk the memory ladder of State, Semantic, Procedural, Episodic, Raw, then Search last. |
| `/snapshot` | Save a blessed chat span word for word as a numbered file: a dated snapshot in the workspace history, with provenance. |

## Research and reading

| Command | What it does |
|---|---|
| `/read` | Read one outside source into the chat and save nothing: a web page, a post, a video, a repo, a PDF, audio, or a local file. |
| `/summarize` | Summarize audio, video, podcasts, web pages, and local files with the summarize CLI, an Add-on. |
| `/clipy` | Read a Clipy screen recording from a shared link or your own library: transcript, screen frames, and pointer evidence through the Clipy MCP. |
| `/research` | Research one question with fetched, numbered sources: quick (one reader on primary sources, the default), deep (the research workflow), or docs (library and repo docs). |

## Writing and messages

| Command | What it does |
|---|---|
| `/copy-last-response` | Copy the last assistant response, or a named chat message, into a paste-stable Markdown fenced code block. |
| `/tldr` | Compress messy notes, reports, plans, sessions, research, or agent output into a short readout the person can scan on a phone. |

## Browser

| Command | What it does |
|---|---|
| `/browse` | Browse a web page with a fast headless browser: open it, read it, click through a flow, take screenshots, or scrape its data. |
| `/setup-browser-cookies` | Import browser cookies from a real Chromium browser into the headless browse session, so browse can test a logged-in site. |

## Data

| Command | What it does |
|---|---|
| `/data-store-pick` | Pick where a piece of data should live and in what format: a Foxrun home first, then Markdown, YAML or TOML, JSON, JSONL, TSV, CSV, txt, code, SQLite, a hosted table, object storage, a secret store, or git. |

## Your apps

| Command | What it does |
|---|---|
| `/reminders` | Read and write Apple Reminders with the remindctl command: show today or overdue, search, add, edit, and complete reminders. |
| `/apple-notes` | Create, search, or read Apple Notes with osascript, plus formatted notes and native checklists. |
| `/gog` | gog CLI: safe Google Workspace automation, JSON, auth, scoped reads/writes. |
| `/gog-gmail` | Gmail operations through gog. |
| `/gog-inbox-triage` | Gmail inbox triage with gog: prioritize unread mail, inspect safely, and prepare reply drafts. |
| `/imessage` | Read, send, or react to iMessage chats with the imsg tool, or stream new ones, with a read-back and a yes-gate before every send. |

## System upkeep

| Command | What it does |
|---|---|
| `/lint-rule` | Add a lint rule, or repair a page template, after a real finding shows a gap. |
| `/schema-update` | Update the data dictionary of Foxrun and its schema guide: add or change an object type or field in the seed, rehearse the apply on a copy, then regenerate and check the guide. |
| `/tidy` | Run the Keeper nightly upkeep by hand with the installed nightly job: lint, the dream code half, the memory check, the workspaces view, and the state push. |

## Add-ons

Most skills need nothing more. A few run on a tool you install yourself, an Add-on from the [tool guide](OPTIONAL-ADDONS.md). When the tool is missing, the skill says so and gives you the install line.

| Skill | Add-on it needs |
|---|---|
| `browse`, `setup-browser-cookies` | The gstack browser engine. Without it, `browse` falls back to Claude's built-in browser. |
| `summarize` | `summarize` |
| `clipy` | The Clipy app |
| `gog`, `gog-gmail`, `gog-inbox-triage` | `gogcli` |
| `jev` | Node.js 22.18 or newer, and your own OpenRouter account and credit |
| `imessage` | `imsg`. Mac only. |
| `reminders` | `remindctl`. Mac only. |
| `apple-notes` | Nothing to install: it uses `osascript`, which comes with macOS. Mac only. |
