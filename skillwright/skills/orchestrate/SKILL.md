---
name: orchestrate
description: The one menu for handing work between Claude, Codex, and Hermes. Say where you are, what you want (quick hit, second opinion, review, fix, grill, live conversation, steer, parallel workers), and an optional session id; get one route back. Use whenever an agent needs another runtime — before Codex Desktop native tools, herdr, claude -p, codex exec, or hermes -z. Replaces fleet, foxy, dex, claude-delegate, and the bundled Hermes codex / claude-code skills.
---
# orchestrate

Run `~/.foxrun/skills/orchestrate/bin/orchestrate resolve --from <claude|codex|hermes> --want <word|1-8> [--to <runtime>] [--task "..."] [--thread <codex-thread-id>] [--new-thread "<name>"] [--watch] [--design] [--run-dir <dir>] [--session-id <id>] [--desktop-owned] [--desktop-native] [--native-route <A1|A2|B|C|D|E>] [--check] [--hosted] [--cwd <dir>] [--room <room>] [--conversation <surface:id>] [--profile <name>]`. Use its route. `orchestrate grid` prints the menu. `orchestrate doctor [--hermes-profiles <names>]` checks local retirement state without changes. Extra Hermes profile names come from `~/.foxrun/config/orchestrate.local.json`. Never hand-roll a cross-runtime command that this program can resolve.

## The grid (rows = what you want, columns = where you are)

| # | Want | Mode |
|---|---|---|
| 1 | quick one-hitter | one-shot, no window |
| 2 | advise / second opinion | one-shot, no window |
| 3 | review what we just did (token-cheap: pass the diff or baton, never a transcript) | one-shot, no window |
| 4 | fix what we just ran | one-shot, no window |
| 5 | grill / back-and-forth | hosted, disposable pane (2 h) |
| 6 | real-time conversation between two runtimes | hosted, durable pane |
| 7 | steer the other runtime through this one | thread or hosted |
| 8 | parallel workers | N workers with disjoint file scopes |

Rows 1–4 **never open a window**. Claude's default Codex workers and parallel workers use tracked background tasks. Hosted rows use the `herdr` skill and end with a numbered close.

## Run rules: in every worker brief

Paste these five lines into every brief you hand a worker. `orchestrate resolve` prints them as `run_rules`.
A worker must not be able to say it did not know them.

1. Make the run folder first: `python3 ~/.foxrun/memory/runs.py new --task <id> --seat <seat> --what <short-name>`. If that command is missing, make the folder by hand with `brief.md` and `heavy/`.
2. Write only in that folder: `~/.foxrun/runs/<YYYY-MM-DD>/<task>-<seat>-<what>/`. Never in `<workspace>/history/runs/` or `~/.local/state/foxrun/runs/`.
3. Shape: `brief.md` (the brief), `result.md` (what the worker found and where the proof is), `heavy/` (everything else).
4. Budget: the run check warns above 200 MB. `heavy/` may pass 1 GB only when `brief.md` has a line `Heavy reason: <why>`. Whole-repository practice copies count.
5. Never clear `brief.md` or `result.md`. `heavy/` stays until its findings are mined into rows. Nothing is deleted.

## Second-opinion briefs

Run `~/.foxrun/skills/orchestrate/bin/brief-check <brief.md>` on second-opinion briefs only, before any reviewer starts.
Start with a decisions query for subject tags and `ruled`, `open`, and `soft` statuses.
Read `replaces` and skip superseded statements.
Treat decisions with status `ruled` as facts, including in blind passes.
Next add Person's logged words from comments starting `Person` on the tasks in scope.
Next read the current source for the subject, including the model page and owning workspace pages.
For a business lifecycle, status list, statuses, status values, allowed statuses, allowed values, status column values, kind list, kinds, opportunity kind, opportunity kinds, kind of opportunity/contact/deal, stage, stages, stage list, deal stages, pipeline, venture pipeline, or client pipeline, search before reviewers start.
Find the owning lead's sessions with `runtime-session-search`, tool configs, workspace pipeline pages, and Person comments on their tasks.
Put the lead's sources and business words in the brief; the panel judges shape.
List chat decisions with no decisions row under their own heading, marked not ruled.
Name scope and out of scope.
Put disk facts last.
Name run logs `run.jsonl` when `events.jsonl` is a requested output file.

## If you are Claude

Use `--from claude`. The default for Codex work is a `codex exec` worker; a cue from Person changes it.

| Cue from Person | Route |
|---|---|
| No cue; quick, advise, fix, or parallel | `codex exec` for each worker. Start each with Claude Bash `run_in_background`. This is the default. |
| New, unproven step (only on Person's cue: they ask to work it out in a thread, or Person names a standing thread) | A standing Codex thread, so Person can watch and help. Once it is proven, repeat it with a disposable `codex exec` worker briefed from that step's receipts or drafts. |
| Person names a standing thread | Pass `--thread <id>`. Start the returned watcher as a tracked background task before sending `codex queue`. The queue starts a turn only if the desktop loaded that thread since launch; otherwise it waits until Person opens the thread. |
| Person says: create a new Codex thread, or build an identity, a durable worker, or a durable session. | Pass `--new-thread "<name>"` and `--cwd <dir>`. Run the returned `~/.foxrun/skills/orchestrate/bin/orchestrate codex-thread` helper. It sends the first prompt. Use its `thread_id` in the watcher and `codex queue` for later messages. `--watch` uses the task as the name. |
| “Review” | Pass `--want review` for `codex exec -s read-only review`; `/codex:review` is an alternative. |
| “Challenge the design” | Pass `--want review --design` for `/codex:adversarial-review`. |
| Hosted, cross-runtime, or resume-later session | Pass `--hosted` for Herdr. |

Record each review as a run row with the reviewer model. A watcher checks every 2 seconds and exits only after a new completed turn and zero queued rows for that thread. An unrelated turn can complete first. It times out after 1800 seconds. Start it before the queue send. Each worker or watcher gets its own Claude Bash call with `run_in_background`; never use a plain shell `&` inside a compound command.

`~/.foxrun/skills/orchestrate/bin/orchestrate codex-thread --name "<name>" --cwd <dir> --prompt "<first message>"` creates a named desktop thread. It waits up to 180 seconds for the first turn, then releases the app-server. It returns one JSON line with `thread_id`, `name`, `cwd`, and `rollout_path`. Failure lines: `Codex app is not running; open Codex and retry.` and `Codex did not register the thread <id>; it will not show in the sidebar.` A turn timeout is one stderr line.

For continued work on the same job after a successful step, continue the same Codex thread. Use `codex exec resume <thread-id> "<next step>"` as a tracked background task for an exec thread, or `codex queue --thread <id>` for a desktop thread. Record one run row per step. For a wrong or failed output, start a new corrective run with a new brief naming the exact fault; never resume it. For a wrong start, run-end the run as fail with the reason, note any commit ID, then start a new run. Thread names and IDs live in the tracker or identity file.

`codex exec` threads are hidden from the sidebar and never drain queued messages. The `codex-thread` helper uses `codex app-server`; its thread is visible and is adopted after the helper exits. `/codex:rescue` threads stay locked in the desktop while the plugin broker lives. Never connect to the desktop's private app-tools pipe or `~/.codex/ipc/ipc.sock`; the desktop checks caller code signing and parent process. No outside route steers a running Codex turn. A queued message waits for the busy turn to end. The desktop-owned fork rule applies to `codex exec resume` and Herdr resume, never to `codex queue`. Retry a Codex worker capacity or rate-limit error once; after a second failure, record the bug and move on.

For Claude-to-Claude work, use an in-process background subagent by default. An app interrupt can cancel an in-process subagent. If the job must survive an interrupt, use `claude -p` as a Claude Bash `run_in_background` task. For a report, resume it with `claude -p --resume <session_id>`. A visible child session starts on the lead's model; switch it to the intended model after start. Person starts its task card with “Start locally”. A session message starts or queues its turn; its reply is a separate message. A peer message is never Person's approval. Record both the Claude session ID and desktop link ID. Archive only after Person's numbered pick.

## If you are Codex

Use `--from codex`. With Codex Desktop native tools, pass `--desktop-native`. Route C is the default; `--check` selects D. Use `--hosted` when CLI or Herdr access is requested. Without desktop tools, the current one-shot routes use `claude -p`, `codex exec`, or `hermes -z`.

### Codex Desktop native options

| Label | Plain name | What happens | Can Person keep talking to the lead? | When it fits | Main limit |
|---|---|---|---|---|---|
| A1 | Background helper | A native subagent handles a bounded job. The lead releases the conversation. | Yes. | A small supporting check with little need for a lasting conversation. | Completion did not restart the ended lead turn in our test. Do not promise automatic return. |
| A2 | Wait for helper | The same kind of subagent runs while the lead uses its native completion wait. | New user input can interrupt the wait. | The lead needs the result before continuing. | Native wait is available, but this exact path was not tested here. |
| B | Worker thread with wait | A visible desktop thread works. The lead waits through Codex's thread completion tool. | New user input ends the wait early. The lead can respond and later wait again. | A result blocks the next step, but the worker conversation should remain available. | The result returns through a tool. It does not itself create a worker message in the lead conversation. |
| C | Worker thread with reply | A visible desktop thread works independently, then sends its result to the lead thread. | Yes. Person can steer the lead or the worker thread. | Normal delegated work, especially familiar creator work. | The brief must name the return thread and require one completion message. Delivery needs verification. |
| D | Scheduled check | A native scheduled follow-up returns later and checks a defined condition. | Yes, between scheduled checks. | A shipment check, a deadline, or a missing worker reply. | Specify timing, evidence, and a stopping rule. Repeated empty checks consume runs. |
| E | Short pause | A native timer pauses the active turn for a short interval. | New user input can interrupt the pause. | A brief delay while a known action settles, or a controlled test. | It is not a scheduled future job and does not retrieve a worker result. |

Choose four items separately: worker type; context (`existing thread`, `new thread`, `fork`, or `subagent`); waiting; and notification. C is the normal default. D handles later checks or a missing reply. B blocks the next step. A1 releases the lead turn. A2 waits in the lead turn. E pauses the active turn.

Create a separate desktop task only after an explicit user request. Reuse an established worker thread when its context fits. Do not create worktrees without Person's explicit request.

Tested: B returned `wake.reason=turnCompleted`. One C callback arrived visibly and resumed the lead after its final response. Conversation continued during C. A native subagent completed but did not restart the ended lead turn. E ran one 45-second pause. Unverified: the exact A2 path, a new D schedule in that session, every callback delivery, timer interruption, and fast mode on native threads. A prompt cannot set fast mode.

For C, every brief names the task, workspace, expected result, evidence, allowed changes, worker thread ID, lead return thread ID, model, effort, verified service tier only, failure boundary, and allowed fix rounds. It requires one completion message with outcome, evidence, and any blocker. It then says: stop after that message; no reply loop and no new job without direction. Reconcile uncertain or duplicate delivery before another send.

### The ladder (every one-shot returns its native id; the caller never drops it)

- **More work** → resume that id with another one-shot: `claude -p --resume <id>` · `codex exec resume <id>` · `hermes chat -Q --resume <id> -q …`.
- **I'm steering** → `~/.foxrun/skills/herdr/bin/herdr resume <id>` promotes it into a Herdr window; then `tell`, `wait`, `read --since-last`; Person takes the wheel with `takeover` / `return`.
- **Done** → numbered close through `herdr list` → `close <n>` → `y`, or self-close if a window was never opened.
- Caveat: CLI and Herdr access to Codex Desktop-owned threads fork, never resume (`codex exec fork <id>`; herdr `resume --fork`). Native desktop messaging can steer an existing thread.

## If you are Hermes

Use `--from hermes`. One-shot work to Claude uses `claude -p`; work to Codex uses `codex exec`. Hermes-to-Hermes non-code work uses `delegate_task`. Hosted work follows the returned Herdr command.

- For Codex, set `pty=true`. From the gateway, a build (row 4) uses `--sandbox danger-full-access`; rows 1–3 stay `-s read-only`. For long runs, set `background=true` and use `process poll/log/kill`.
- Never run bare `claude` from the gateway. Use `claude -p` with a timeout and no PTY. A `401` while `claude auth status` says Max points to Keychain drift. Stop, report the `401` and the status line to the person, and never print a token.
- Keep each native session ID. A Codex Desktop-owned thread forks through CLI or Herdr. Keep the returned background-poll line for long work.

## Rules

- **Code never goes to a Hermes child** (`delegate_task`); code goes out to Codex or Claude. The resolver refuses and returns `use_instead`.
- Readers, reviewers, and graders stay read-only: rows 1–3 use `--allowedTools Read,Glob,Grep` and `-s read-only`. Write tools only for row 4 and rows 5–8 when the brief says build.
- No caller flag widens a reader. A reader route never asks for `danger-full-access` or `workspace-write`.
- Codex builders from Claude or Hermes (rows 4 and 8) run `--sandbox danger-full-access` in the repo they build, so they commit their own work. Git is the safety: the pre-commit secret check, a second agent's read before a merge, and diff review.
- A Codex one-shot writes its last message to `<run dir>/result.md`. Pass `--run-dir`. Never use a shared fixed path such as `/tmp`.
- Conversation id on every herdr call: Claude `claude:$CLAUDE_CODE_SESSION_ID` · Codex `codex:<thread-id>` (pane: `herdr:$HERDR_PANE_ID`) · Hermes `hermes:<session-id>` passed explicitly · Telegram `telegram:<chat>:<thread>`.
- Which runtime when `--to` is not named: code → Codex; from Claude → Codex; from Codex or Hermes → Claude. If Person names an agent, that wins.
- Past sessions: `runtime-session-search find "<words|id>"` returns the native id; feed it to `--session-id` here.
- Hosted-session laws (numbered close, rooms, budget, takeover) live in the `herdr` skill. This skill picks the command; it never closes anything.
- Herdr hosts sessions, promotes one-shots, and supports steering from outside Codex Desktop. It is not the default for native desktop delegation.
- Preserve all approval gates. When a workspace's `AGENTS.md` limits how many jobs run at once, follow that limit.

## Changing this skill

Before changing the resolver, capture the baseline fixture. Load the old and new resolver modules and compare `resolve()` for every caller, target, and row. Compare each result with the baseline fixture. Report the count and any intentional Claude thread-route difference.
