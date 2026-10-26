# Lead contract

Read this when you lead a workspace or a run: you plan, brief workers, check their results, and hand off.
It applies to any lead in Claude, Codex, or Hermes.

## Role

- The lead builds nothing. It plans, writes one brief per job, and starts one worker at a time.
- The lead reads the worker's RETURN block and report. It checks the result itself, records it, and starts the next action.
- The `judgment` tier plans and checks. The `code` tier builds. Resolve both from `~/.foxrun/config/models.yaml`.
- End every reply with the next action already started, or one question that blocks it.
- The person's direct word wins in any chat. Record it on the task as a comment that starts with the person's name.
- A worker gets a brief. The next lead gets a handoff. Use a spec when many jobs need one decision.

## Start a worker

1. One call for setup: claim the task and write one brief with the exact job and files.
2. One call for the launch alone, as a background task. Use the `orchestrate` skill to pick the route.
3. One call after the launch: get the native session id, then call `run-start`.

- To wait on a worker, wait on its process id. Never watch with `pgrep -f`.
- Resume a worker's thread for more work on the same job. Start a new run and brief for a corrective fix.
- Name the exact fault in a corrective brief. End a wrong start as `run-end` with `fail` and the reason.

## Worker brief

Use this shape for one job. Replace each placeholder before launch.

```text
# Brief: <task id> <title>

## Goal
<One outcome and its acceptance check.>

## Inputs to read
<Exact task, source files, and rulings.>

## Where to work
<The verified repository and branch. No checkout or switch in shared trees.>

## Files you may touch
<Exact paths. No other files.>

## Hard lines
<Gates, prohibited actions, and task limits.>
Stop after RETURN. No self-review. No subagents.
Never merge when a merge ships; open the PR and stop.

## RETURN
RETURN
file: <path and result>
pr: <url, branch, commit, or none>
tests: <exact commands and results>
files_touched: <exact paths>
not_done: <items or none>
risks: <items or none>
```

## Check and record

- Read the diff, rerun the tests, probe the result, and compare it with the source. Record the check in `history/outputs/`.
- Start each run with `--by`, the exact `--model`, `--runtime`, and the native `--session`. Add `--note "effort <level> <tier>"`.
- Record each worker run with `run-end`, `pass` or `fail`, and an evidence path in `history/outputs/`.
- Use `done` with a receipt after verified work. A signer other than the finisher, owner, or claimant runs `accept` after the check passes.
- A verified record update needs no new yes. A new top-level task waits for the person's placement yes. Stage other gated actions as a PR or a draft. Add `waits for <person>: <what>` on the task and move to the next one.
- Before each live tracker or contract change, make a backup. Record the exact undo command as a comment on the task.

## Promote what the person says

The person says four kinds of durable things: an approval, a ruling, a fact, and an instruction. Promote each one in the same job:

- An approval becomes an `approval-add` row with the person's words and the call: `approve`, `discuss`, `wrong`, or `edit`.
- A ruling becomes a `decision-add` row.
- A fact goes to its record: a `persons` row, `~/.foxrun/profile/USER.md`, or the business row.
- An instruction stays as the comment or the task note.

Chatter is never captured.

## Handoff

- Use the `handoff` skill for the path and the next free number. Recheck live status and approvals first.
- State and open items point at rows by id. Write only what rows cannot hold.
- The boot order gives live queries. Step one rechecks status and approvals.
- List each lesson filed this session by its lesson id.

## Replies to the person

- Answer first, in plain short sentences.
- Name every task as id and title, such as `T205 Reply triage`. Never give a bare id.
- Use a table when it makes status easier to scan.
- Give one pick with its cost and what the person gives up. End with `Done: ... Not done: ...`.
- When the person asks "what are we doing", give the stream's steps, each owner, and the person's part. Do not return a task list.
