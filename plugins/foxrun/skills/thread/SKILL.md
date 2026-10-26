---
type: note
workspace: system
timestamp: 2026-10-23T22:07:53-04:00
name: thread
description: "Make an agent thread in Claude or Codex: a titled session that starts in its workspace and boots its seat, in the Claude app, a terminal, or Codex. Use for /thread (list the agents and offer the missing threads), /thread <agent>, /thread lead <workspace>, or the thread step of setup."
kind: tool
argument-hint: "[<agent> | lead <workspace>]"
---

# thread

One agent gets one thread: a titled conversation that starts in its workspace and boots its seat.
The title is `<emoji> <workspace> · <role>`, so the person finds the agent in the sidebar by sight.
`bin/thread` does the lookups and the writes. It prints JSON. Run `bin/thread --help` for the flags.

## Steps

1. **Pick the form.**
   - `/thread`: run `bin/thread list`. Show each agent with its emoji and whether it has a thread. Then offer to make the missing ones, one question at a time.
   - `/thread <agent>`: the agent is a seat id from the list, such as `architect`.
     An agent made for one workspace (`agent_new create --client <ws>`) lives in `<ws>/team/<id>.md`. The list shows its workspace.
   - `/thread lead <workspace>`: the workspace lead, seat `lead-<workspace>`.
   Done when you know the seat, or the person picked the seats from the list.
2. **Ask what the plan needs.** Use the runtime's question tool, one question each:
   - The workspace, for an agent thread. A lead thread or a workspace agent's thread starts in its own workspace.
   - The runtime: `claude-desktop`, `claude-cli`, or `codex`. Offer the one you run in first.
   - The model tier: `judgment`, `work`, `cheap`, or `code`, from `~/.foxrun/config/models.yaml`. The seat's own tier is the default. Name the model each tier gives.
   Done when each answer is in hand. Skip a question when the person already answered it.
3. **Pick the emoji.** Suggest one emoji that fits this thread's work, such as 📦 for a shipping thread. Offer the seat's default as the other choice: `bin/thread plan` prints it with `emoji_state` `default`. The person can type another one. The emoji varies by thread; the map holds only defaults. Done when the person picked one.
4. **Plan.** Run `bin/thread plan <seat | lead ws> --runtime <r> --workspace <ws> --tier <t> --emoji <picked>`. Leave out `--emoji` when the person took the default. Show the person the `title`, `cwd`, and `model`, and let them change the emoji or any answer before you go on. Done when the person says yes to that plan.
5. **Make it.** Pass the same `--emoji` as the plan. The route depends on the runtime:
   - `claude-desktop`: call the Claude app's own new-session tool with the plan's `title`, `cwd`, and `prompt`. Then run `bin/thread record <seat> --runtime claude-desktop --workspace <ws> --id <session id>`.
   - `codex`: run `bin/thread make ... --runtime codex`. It starts `codex app-server`, then sends `thread/start`, `thread/name/set`, and `turn/start`, and waits for the boot turn to end.
   - `claude-cli`: run `bin/thread make ... --runtime claude-cli`. It runs `claude --bg -n "<title>" --model <model> "<prompt>"` in the workspace folder.
   Done when the JSON shows `"made": true` or a `recorded` entry with an `id`.
6. **Report.** Give the title, the runtime, and where the person finds it: the Claude sidebar, the Codex sidebar, or `claude agents`. Done when the person has the title and the place.

## Gotchas

- `claude --bg` refuses a folder Claude does not trust yet. The error says to open `claude` once in that folder and accept the prompt. Tell the person that, then retry.
- A `claude --bg` session shows in `claude agents`, not in the Claude app sidebar. Use `claude-desktop` when the person wants the sidebar.
- The Codex app may not show a new thread until it refreshes. The thread exists when `make` returns its id.
- During the Codex boot turn, `make` declines each approval request. The person approves later steps in the app.
- `list` reads Codex thread names read-only from `~/.codex/state_5.sqlite`. It matches a title by its workspace and role, whatever the emoji. It never reads Claude's session files. A Claude thread shows only after `make` or `record` saved it.
- No hosted session tool is needed. Do not use herdr for a thread.
- `--emoji` wins over the defaults in `~/.foxrun/config/threads.json`, key `emoji`, which win over the shipped defaults. Change a default there, not in the script.
- Use `--dry-run` on `make` or `record` to see the exact plan. A dry run writes and starts nothing.
