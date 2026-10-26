---
type: doc
workspace: system
timestamp: 2026-10-19T19:35:51-04:00
---
# Standing seats

Start one named durable seat after the native hooks are activated:

```sh
python3 "$FOXRUN_HOME/foxrun.py" standing --seat architect --runtime claude --name architect-claude --workspace foxrun-dev --conversation codex:<your-current-thread-id>
python3 "$FOXRUN_HOME/foxrun.py" standing --seat chief-of-staff --runtime codex --name chief-codex --workspace foxrun-dev --conversation codex:<your-current-thread-id>
```

Use one stable conversation ID on every call.
The installed orchestrate resolver selects its durable Herdr route.
The launcher adds the name through Herdr's role and topic arguments.
It does not start a runtime unless the current identity and contracts pass.

The first prompt carries a non-secret `FOXRUN_STANDING=<launch-token>` argument.
The hook reads this token from its Claude or Codex process ancestor.
The hook binds the token to its native session ID before the first model turn.
The hook stops at its nearest native process, even when that process has no token.
An ordinary child never takes a standing parent's seat token.
This uses `/bin/ps` on macOS or Linux, with 24 ancestor steps at most.
The hook never reads a runtime store or depends on inherited `FOXRUN_SEAT`.
The launcher's environment does not need to reach the runtime.

`runs/standing/launches/<token>/record.json` holds the launch and returned spawn output.
`runs/standing/launches/<token>/trail.jsonl` holds the route and each start output.
`runs/standing/sessions/<runtime>/<native-id>.json` holds the seat binding.
`runs/standing/names/<runtime>/<name>.json` reserves the durable name.
Keep these private run files out of the product manifest and git.

Resume and compaction use the native ID, without a launch token.
The hook reads the current identity on each wake, including its Boot reads.
`config/standing-seats.json` names each current source through a home-relative reference.
Change that reference when its owner moves the identity.
The reference must point to an identity, never a generated runtime cape.
Sources with old Obsidian or Code paths refuse startup until their owner migrates them.
The current proposal configures Architect and Chief of Staff.
Communications lead still needs its source-path migration.

For management, use the installed Herdr wrapper:

```sh
~/.agents/skills/herdr/bin/herdr list --conversation codex:<your-current-thread-id>
~/.agents/skills/herdr/bin/herdr status <native-id> --conversation codex:<your-current-thread-id>
~/.agents/skills/herdr/bin/herdr read <native-id> --transcript --conversation codex:<your-current-thread-id>
~/.agents/skills/herdr/bin/herdr resume <native-id> --conversation codex:<your-current-thread-id>
```

Herdr proves writer release before Codex resume.
Codex Desktop-owned sessions need Herdr's fork route and a separate seat binding for the new native ID.
This launcher creates Herdr sessions; it does not adopt Desktop threads.
Send tasks with `herdr tell`; a queued message does not prove completion.
Keep existing tasks as the work queue pending the owner's queue decision.
No automatic Claude or Codex worker queue is added here.

A missing hook, missing native ID, budget hold, or mismatched ID fails the launch.
Inspect the saved output and existing session before any retry.
The launcher keeps the name and evidence; it never closes or retries automatically.
Close only after Person's numbered choice and required confirmation.

Offline checks prove the process-argument contract with fake native and process adapters.
The sandbox denies actual `/bin/ps`; real process ancestry remains part of activation proof.
Real native registration, context delivery, resume, and compaction wait for the move.
