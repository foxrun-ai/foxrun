---
type: note
workspace: system
timestamp: 2026-10-24T17:29:31-04:00
name: foxrun-setup
description: "Install the Foxrun core when it is missing, or rerun the setup again, all of it or one part. Parts: the questions, the agent threads, the hooks, and the backup. Use for /foxrun-setup, /foxrun-setup <part>, a thread's first boot, or when someone asks to redo, check, or finish setup."
kind: tool
argument-hint: "[questions | threads | hooks | backup]"
---

# foxrun-setup

Install sets Foxrun up once. This skill reruns it: all four parts in order, or the one part the person names.
If the Foxrun core is not installed yet, this skill installs it first.
`bin/setup status` reads where each part stands and gives the `next` open question. It writes nothing.
Ask each question with the runtime's question tool, one at a time, so the person answers with one tap.

## Steps

1. **Check the core.** If `~/.foxrun/foxrun.py` is missing, the core is not installed, and `bin/setup status` reads an empty home. Ask for the name, the first workspace, and the runtime, one question each. Offer the runtime you run in first. Show the person these commands, and run them only on their yes:

   ```sh
   uv tool install git+https://github.com/foxrun-ai/foxrun
   foxrun install --home "$HOME/.foxrun" --portfolio "$HOME/foxrun" --yes --person <name> --workspace <workspace> --runtime <claude|codex|both>
   python3 "$HOME/.foxrun/foxrun.py" doctor
   ```

   If `uv` is missing, send the person to https://docs.astral.sh/uv/ first. On Windows, use `py -3` in place of `python3`. Done when doctor prints `Doctor: 0 failed`, or the core was already there.

   **Update an existing core.** After a plugin upgrade, tell the person that the plugin refreshed only its three skills. Show these commands and ask them to run the update, or run it on their explicit yes:

   ```sh
   uv tool upgrade foxrun
   foxrun update --home "$HOME/.foxrun"
   ```

   For a clone install, use `git pull`, then `python3 foxrun.py update --home "$HOME/.foxrun"` from the product folder. Use the person's custom home path when needed. Success ends with `Doctor: 0 failed`. Keep the printed backup path if update fails. A plugin upgrade alone does not update the core.
2. **Read the state.** Run `bin/setup status`, or `bin/setup status --part <part>` for one part. Done when you have the `parts` list and its `next`.
3. **Questions.** For each item in the questions part's `open`, ask its `question` with its `choices`. To change an answer, run `bin/setup set --field <key>=<value> --dry-run`, show the person the `changes`, and on their yes run it again without `--dry-run`. Only `runtime` and `default_workspace` change here. A new name is a new install; a new workspace is a workspace job. Done when the questions part has no `open` item, or the person skipped it.
4. **Threads.** Use the `thread` skill. Offer each seat in the threads part's `open`, one question at a time. Done when each offered seat has a thread or the person said no.
5. **Hooks.** If the hooks part has an `open` item, ask its `question` word for word, with `Yes (recommended)` first. Then run `bin/setup hooks --answer yes` or `--answer no`. On yes, it runs `foxrun.py hookup` for each app with missing hooks. That command copies the app's settings file to the backup folder first, adds only the Foxrun entries, and keeps every other entry. Show the person the result in plain words: each settings file in `connected`, what it turns on from `what_it_does`, and each folder in `backups`. Then say `next`. If `still_missing` is not empty or the command fails, show the error and stop. Do not edit a settings file yourself. Done when the person answered and saw the result.
6. **Backup.** If the nightly job is off, show its `command` and run it only on the person's yes. A state remote is a change on an outside platform: tell the person the steps; never make the remote for them. Done when `open` is empty, or the person said no to each item.
7. **Report.** Rerun `bin/setup status`. Say in one line per part what changed and what stays open. Done when the person has that list.

## Gotchas

- The whole setup runs the parts in the order above. One part runs only that step and the report.
- A new thread's boot prompt runs `bin/setup status` and asks its `next`. If `next` is empty, setup is done; ask what to work on.
- `status` counts the nightly job as on when it ran in the last two days, even if install did not turn it on.
- Hooks are checked by script path. A hook entry that runs the same script from another path shows as missing.
- Claude and Codex keep four hooks: session-start, after-compact, before-compact, and session-end. start-rules is for Hermes only, so `status` never reports it missing here.
- `bin/setup hooks --answer yes` is safe to run twice. The second run finds every entry and writes nothing. An older core with no `hookup` command gets an error that says to update the core first.
- The same command works by hand: `python3 "$HOME/.foxrun/foxrun.py" hookup --runtime <claude|codex|both>`.
