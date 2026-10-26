# Boot hook registration (draft)

**Not registered. This is a draft only. It waits for @Person@'s yes.**
Nobody adds these blocks to a live settings file until @Person@ approves them.

Read this when you register, check, or remove the SessionStart hook that runs `bin/handoff-boot`.

## What the hook does

On startup, resume, compaction, or clear, the runtime runs `handoff-boot`.
It prints the seat's boot sequence as SessionStart `additionalContext`: the newest hand-written handoff for the seat and session, then every newer pre-compaction note, oldest first. Each file has a `File N of M` header line. Over the cap it keeps the hand-written handoff whole and cuts the oldest notes first, and names them.
It exits 0 in every case, so it can never block a session start.
The seat comes from `FOXRUN_SEAT`, else from the handoff whose `session:` equals the incoming session id.

The command path below is the published skill path. Check it before you register:
`$HOME/.foxrun/skills/handoff/bin/handoff-boot`.

## Claude Code

Add this under `hooks.SessionStart` in the Claude user settings (`~/.claude/settings.json`).
Keep every hook that is already there; append this group to the list.
Source: Claude Code hooks reference, SessionStart (matchers `startup`, `resume`, `clear`, `compact`; output `hookSpecificOutput.additionalContext`).

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|compact|clear",
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.foxrun/skills/handoff/bin/handoff-boot",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

## Codex

Add this under `hooks.SessionStart` in `~/.codex/hooks.json` (same shape as Claude).
Source: openai/codex `codex-rs/hooks` (SessionStart `source` is `startup`, `resume`, `clear`, `compact`, or `fork`; a `|` list is an exact matcher; the output schema takes `hookSpecificOutput.additionalContext`).

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|compact|clear",
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.foxrun/skills/handoff/bin/handoff-boot",
            "timeout": 10,
            "additionalContextLimit": 4000
          }
        ]
      }
    ]
  }
}
```

- `additionalContextLimit` is in approximate tokens. Codex spills context above 2,500 tokens to a file by default. The boot text can reach 12,000 characters (about 3,000 tokens), so the draft raises the limit to 4,000.
- A new or changed Codex hook is ignored until it is trusted (`hooks.state` `trusted_hash` in `~/.codex/config.toml`). Trust it through the Codex hook-trust flow; never compute the hash by hand.
- The field names come from the Codex main branch source. Confirm them against the installed Codex version before you register.

## Check after registration

1. Run `handoff-boot --dry-run --seat <seat> --cwd ~/foxrun/<workspace>`. You see `picked:` with the expected file.
2. Start a fresh session with `FOXRUN_SEAT=<seat>` in a vault workspace. The first context holds `Boot: read this handoff first; rows win over it.` and the file path.
3. Compact the session. The same seat's newest handoff comes back.

## Remove

Delete the one group you added from each file. Nothing else changes.
