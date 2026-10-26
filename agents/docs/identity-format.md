# Identity file format — `<id>.md`

Frontmatter (all keys required unless marked optional):

```yaml
type: agent-soul                 # SCHEMA.md object type for this page
workspace: system                # system, or the owning workspace folder for team/<id>.md
timestamp: 2026-09-08T09:00:00-04:00  # ISO 8601 with time and offset; never created/updated
id: creative-strategist          # lowercase, hyphens; == filename
display_name: Creative Strategist
role: one line, what this identity is responsible for
summary: one sentence, used as the Hermes profile description and cape description
tier: work                       # judgment | work | cheap | code  (~/.foxrun/config/models.yaml)
shared: true                     # true = reusable across clients; false = one client only
client_default: example-work        # optional; team file decides the actual binding
runtimes: [claude, codex]
hermes_mode: none               # profile | child | kanban | none
hermes_profile: null             # profile name when hermes_mode is profile or kanban
sets: [base, example-work]       # catalog sets in config/catalog.yaml; the loader expands skills and tools
return_default: session:caller   # where results go unless the assignment says otherwise
version: 1
```

Agent pages write this frontmatter as JSON, which is also YAML; key names and rules are the same.
A workspace identity that still has `created` loads until its reviewed migration; a page never has both.

Current body shape, in this order, plain English, ≤120 lines:

1. `# <Display name>` — the existing identity name.
2. `## Who you are` — personality and the agent's own style.
3. `## Responsibility` — three to five lasting outcomes it owns.
4. `## Judgment` — how it decides and what it refuses to guess.
5. `## How you write state` — the one rule for writing rows with `work.py`. Required for seats and workers. It sits after `## Judgment` and before `## Boot reads`.
6. `## Boot reads` — what it reads on wake, in order. Required for seats (Chief of Staff, Architect, Communications lead); optional for other identities, which are not migrated.

How you write state rules:
- The text is the same in every identity. `agent_new.py` holds it (`WRITE_STATE_SECTION`), and `create` scaffolds it verbatim.
- The seven moves, in order, each with its exact `work.py` command: a task row (`create` or the existing row), `claim`, `run-start`, `comment`, `run-end`, `done` then `accept`, and the side rows `bug-open`, `approval-add`, `decision-add`.
- Commands use `--db ${FOXRUN_HOME:-$HOME/.foxrun}/data.db --receipt-root ${FOXRUN_HOME:-$HOME/.foxrun} --by <id>`.
- The person's words go in verbatim, in a comment that starts with their name and a colon (the `name` in `~/.foxrun/config/person.json`).
- The same-turn line reads exactly: Same turn, a row: see `~/.foxrun/profile/AGENTS.md`.
- A newer ruling kills the older version. When you write or read a decision row with a replaces field, the replaced statement is dead: drop it from your working picture and never present it again as settled. Before you call anything settled, check decisions.replaces for a newer row.
- A new word is written with its old name, what it is related to, what is in it, and what it replaces.
- Keep `--person-words` in approval and decision commands.
- `--person-words` is the general name, used once the work command accepts it.
- 25 lines or fewer. The validator checks the order and the length.
- Seats carry it now (Chief of Staff, Architect, Communications lead). Other identities get it in their reviewed migration.

Boot reads rules:
- Named reads only, in order. Each line is a command or a path.
- Decisions filtered by status and by subject (tags). Never "the newest N decisions".
- Only the `GLOSSARY.md` model sections the seat needs.
- Five open lessons: read the lessons the work command lists. Say which.
- One matching handoff: the seat's newest in its workspace (`handoff-boot --seat <id>`).
- Activity: 10 to 20 rows by subject. Never a full log. No `log.md` on wake.
- Queries are read-only (`sqlite3 -readonly`). Boot reads grant no authority to act.

The shared `soul.md` supplies Core Truths, How You Think, Vibe, Boundaries, and How We Work.
Gates and routing belong in the client `AGENTS.md` and existing execution policy.
The result contract remains `execution/result.schema.json`.
This follows ruled decisions `soul-six-headers`, `base-soul-plus-agent-soul`, and `agent-team-is-the-soul-source`.
Read their canonical records from the configured decisions store.

The loader still accepts the earlier Responsibility, Judgment, Style, Limits, and Return headings during migration.
That compatibility support does not make the older headings the current template.
Review each source identity before migration.
Preserve their exact financial, send, review, and access boundaries before moving any text.
This documentation correction changes no identity, personality, profile, or approval.

Rendering rules:
- Hermes SOUL.md = a one-line header + the body verbatim. The current shape also appends `soul.md` verbatim when present, without its frontmatter.
- A legacy body does not receive the base soul through this renderer branch. Verify startup separately; generated files are not live proof.
- Claude cape = frontmatter (name, description=summary, tools, skills, mcpServers=tools, model from tier) + a 6-line body that says: read `<id>.md`, read the client workspace contract, obey `~/.foxrun/config/models.yaml` approvals.
- Codex cape = TOML (name, description=summary, model from tier, developer_instructions = same 6 lines).
- Capes never copy the body. The identity file is the only place the body lives.

Draft seats:
- Use `Draft from rows, 10.12; the person who owns Foxrun reviews it.` after frontmatter.
- Decision rows supply duties. The shared state rules supply the state section.
- If the rows name one duty, keep that duty and add `The rows name one duty so far.` to the draft marker.

Capabilities come from `config/catalog.yaml`. The identity selects `sets`, and carries no skill or tool list.
Workspace identity: `team/<id>.md`; runtime files: `team/claude/<id>.md` and `team/codex/<id>.toml`.
