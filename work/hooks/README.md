# session run hooks

These blocks describe the native hook registration. Keep all existing entries.
For existing trackers, follow [the holding-key migration order](../README.md) before activating this code.
`session_run.py setup --db <tracker>` verifies the live keyed task. An unkeyed tracker returns non-zero with a backfill requirement.
Only explicit first installation on an empty tracker uses `setup --db <tracker> --create`.
That creates one keyed, open `recurring` task named `Session work to place` under . Repeating setup changes nothing.
`backfill-key --db <tracker> --task <id>` assigns the key to an existing live recurring task. A repeat changes nothing.
Backfill refuses another holder, a BLOB key, a closed task, invalid tags, or an existing different key. It records one history row.
Only setup and backfill assign `tasks.idempotency_key = 'session-holding-task'`. The value is reserved and stored as TEXT.
No public work verb can set, change, or clear that key. The hooks never create tasks or repair identity.
The standing task can move between streams, including another program, with `--approval` on that task. It cannot leave to the inbox.
The writer and logger use `work.py`'s `session_holding_task()` helper. Identity comes only from the exact TEXT key.
Logging requires only that keyed task's status is neither `done`, `canceled`, nor `superseded`.
Titles, timestamps, tags, and stream placement do not select identity. Another task can share the display title without protection.
The keyed task permits retitles and other tag changes. It must keep `recurring`; done, accept, cancel, and inbox moves remain refused.
Destination checks, task-only move approval, atomic history, and subtask rewrite approvals remain unchanged.
Setup and start diagnose missing or corrupt identity without adoption or replacement. Start prints one stderr line and exits zero.
`end` still finds the open run by session, even after the run moves or the holding identity is damaged.

## Claude Code user scope: `~/.claude/settings.json`

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|fork",
        "hooks": [
          {
            "type": "command",
            "command": "~/.foxrun/hooks/claude/claude_session_start.sh",
            "timeout": 5
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.foxrun/hooks/claude/claude_session_end.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Claude `SessionStart` supplies `session_id`, `cwd`, `transcript_path`, `source`, and optional `model`. `SessionEnd` supplies the common fields and `reason`. The tool ignores compact and reopens an ended run on resume. It skips `CLAUDE_CODE_ENTRYPOINT=sdk-*` workers. `claude-desktop` and `cli` still log. Sources: [Claude hook input](https://code.claude.com/docs/en/hooks#sessionstart-input), [Claude session end](https://code.claude.com/docs/en/hooks#sessionend-input).

## Codex user scope: `~/.codex/hooks.json`

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear",
        "hooks": [
          {
            "type": "command",
            "command": "~/.foxrun/hooks/codex/codex_session_start.sh",
            "timeout": 5
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.foxrun/hooks/codex/codex_session_end.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Codex `SessionStart` supplies `session_id`, `cwd`, `transcript_path`, `model`, and `source`. `SessionEnd` supplies the common fields and `reason`. A local `codex exec` probe with a temporary `CODEX_HOME` found no exec marker in the payload or hook environment. Set `FOXRUN_NO_SESSION_LOG=1` when launching Codex workers. The installed `codex features list` reports `hooks stable true`. Codex requires trust review for the exact hook definition before it runs. Sources: [Codex hooks](https://learn.chatgpt.com/docs/hooks), [Codex hook registration](https://learn.chatgpt.com/docs/hooks#where-codex-looks-for-hooks).

The scripts pass hook JSON on stdin to `session_run.py`. `SessionStart` creates one run on the standing task. A repeated start writes nothing while that run remains open. Resume reopens an ended run and writes one activity row. `SessionEnd` closes that hook run and leaves `result` empty. If the model was pending, it reads the transcript's first assistant model. The vault root and every vault folder outside `cedar-shop` and `example-client` use the `foxrun` tracker. `cedar-shop` and its descendants use the `cedar-shop` tracker. `example-client` and paths outside the vault write nothing. Set `FOXRUN_NO_SESSION_LOG=1` in a worker process to skip both hooks. Each handler has a five-second hook timeout and exits zero. Codex `SessionEnd` may fire after 30 idle minutes rather than when a client switches away.

At wrap, place the run on its work task with `work.py run-move <run-id> --task <task-id> --by <actor> --db <tracker> --receipt-root <workspace>`. The move changes its subject and records one activity row. It refuses a non-task or a done, canceled, or superseded task.

Direct use:

```sh
python3 events/session_run.py start --runtime claude --session SESSION --cwd WORKSPACE_DIR [--model MODEL] [--desktop-session LOCAL_ID] [--by NAME]
python3 events/session_run.py end --session SESSION --cwd WORKSPACE_DIR [--model MODEL]
```

`end` also accepts `--transcript PATH` for a native JSONL transcript. If the model is pending, it reads the first assistant message model. The hook passes the runtime transcript path automatically.
