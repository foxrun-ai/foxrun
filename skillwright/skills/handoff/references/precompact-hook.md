Not registered: waits for @Person@'s yes.

# Pre-compaction hook registration (draft)

Read this when you register, check, or remove the hook that runs `bin/handoff-precompact` before a compaction.
Nobody adds these blocks to a live settings file until @Person@ approves them.

## What the hook does

A runtime is about to compact a session. The hook runs `handoff-precompact`, which:

1. Finds this session's newest handoff in the workspace (`session:` in its frontmatter). The check window starts at its `timestamp`, else at the session start.
2. Runs the read-only check: `python3 ~/.foxrun/memory/handoff_check.py --transcript <path> --settlements [--since <time>]`. It opens trackers with `mode=ro` and writes no file.
3. Reserves the path with `bin/handoff-path <workspace folder> <seat>-precompact` (or `precompact` with no seat) and writes the handoff there.
4. Dirty (a @Person@ settlement with no decision, approval, or comment row): the handoff opens with `## Unpromoted` (time and his words), and the script prints one warning line.
5. Clean: the normal handoff by the ruled shape, no warning.

It exits 0 in every case, so it never blocks a compaction. It never writes a tracker row.
A subagent compaction (`agent_id` in the input) and a session outside the vault write nothing.

Where the warning line shows:

| Runtime | Channel |
| --- | --- |
| Claude | Claude discards a PreCompact `systemMessage`, and a successful hook's stdout goes only to the debug log. The warning reaches the model through the SessionStart `compact` hook (`handoff-boot`, see `boot-hook.md`): it prints this handoff, and the warning is its first bold line. |
| Codex | stdout `{"systemMessage": "<warning>"}`. Codex shows it to the user as a hook warning. |

The command path below is the published skill path. Check it before you register:
`$HOME/.foxrun/skills/handoff/bin/handoff-precompact`.

## Claude Code

Add this under `hooks.PreCompact` in the Claude user settings (`~/.claude/settings.json`).
Keep every hook that is already there; append this group to the list.
Source: Claude Code hooks reference, PreCompact (matchers `manual` and `auto`; input `session_id`, `transcript_path`, `cwd`, `trigger`, `custom_instructions`; exit 2 or `"decision": "block"` would block, and the script never does either).

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "manual|auto",
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.foxrun/skills/handoff/bin/handoff-precompact",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

Pair it with the SessionStart draft in `boot-hook.md` (matcher includes `compact`). Without it, the Claude warning stays in the file only.

## Codex

Codex 0.155.1 has a PreCompact event (`codex-rs/hooks/src/events/compact.rs` at tag `rust-v0.155.1`).
Input: `session_id`, `turn_id`, `agent_id`, `agent_type`, `transcript_path` (can be null), `cwd`, `hook_event_name`, `model`, `trigger` (`manual` or `auto`).
Output: the universal fields only (`continue`, `stopReason`, `suppressOutput`, `systemMessage`); unknown fields fail the parse. The script prints only `systemMessage`.

Add this under `hooks.PreCompact` in `~/.codex/hooks.json` (same shape as Claude):

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "manual|auto",
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.foxrun/skills/handoff/bin/handoff-precompact",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

- A new or changed Codex hook is ignored until it is trusted. Trust it through the Codex hook-trust flow; never compute the hash by hand.
- With a null `transcript_path`, the script asks the check to find the transcript by session id.

## Hermes

No pre-compaction hook: Hermes fires `session:compress` only after compression and only in the gateway, and keeps turns in its state database, not a transcript file the check reads. Fallback: the handoff skill's manual trigger plus the nightly handoff check.

## Check after registration

1. Run `handoff-precompact --dry-run --seat <seat> --cwd ~/foxrun/<workspace> --session <id> --transcript <path>`. You see `dry run: would write` and the handoff text. Nothing is written.
2. In a test session, run `/compact`. A `<date>-NNN-<seat>-precompact.md` file appears in `<workspace>/history/handoffs/`, and after compaction the first context holds it.

## Remove

Delete the one group you added from each file. Nothing else changes.
