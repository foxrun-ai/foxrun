---
type: doc
workspace: system
timestamp: 2026-10-19T19:35:51-04:00
---
# Shared Memory commands

`python3 -B foxrun.py start --workspace <workspace> --seat <seat> --function <function>` builds fresh shared pages.
It prints the system, workspace, and function parts, up to 200 lines.
Claude and Codex keep native standing binding and hook JSON. Their hooks find the home from their installed path.
A standing seat also receives its full identity and Boot reads. Optional memory detail shrinks to fit when possible.
A long required seat identity can extend the readout; it is never removed.
It preserves Always, exact event counts, and every question command. It trims optional open rows and decision examples first.
Each start appends one line to `runs/<date>/sessions.jsonl`: time, workspace, seat, function, session.
`--run-dir` or `FOXRUN_RUN_DIR` chooses an existing run. The start keeps its text there in `start-page.md`; a repeated start keeps a new compact copy inside it.
The marker key is seat, workspace, and function. It counts exact event times after the previous start.
The printed SQL follows the same workspace tags and default-workspace rule as the page.
The function part uses tasks.function. No kept function page is created.
Unfinished work adds the first 20 lines of the latest matching handoff.
A session compact always adds its matching handoff, including when its tasks are closed.
The runtime payload and stored start context recover seat and function. Explicit settings win.
All three session-start and after-compact starters use the same payload-aware command. Runtime registration is part of the switch.

`python3 -B memory/kept.py keep --workspace <workspace> --input <relative-path> --topic wiki/concepts/<topic>.md` freezes a reply.
The topic note must exist. The original goes into `history/snapshots/`.
Omit `--topic` when no topic is known. Dream creates an inbox task that points at the original.
`python3 -B memory/kept.py link --workspace <workspace>` runs the linking step by hand.
`python3 -B memory/dream.py run` runs the whole job. A close command can call it.
Linking is safe to repeat. The reply stays frozen. The topic note holds a dated link, without a second text copy.
Historical snapshot formats remain unchanged and appear in runs/kept-link-review.json. They do not block new replies.

`config/dream.json` holds the schedule. The default is nightly at 02:30.
Set hour and minute for a nightly time, or interval_seconds for another frequency.
`python3 -B cron/nightly.py --schedule` prints a launchd definition from those settings.
The installer loads it. After a change, `python3 -B cron/schedule.py --on` reloads it. Changing the setting alone does not change a loaded schedule.

`python3 -B memory/check.py --health-only` writes `health.json` without reading the database.
It reads dream manifests and lead beats. Missing, unfinished, failed, or old runs fail the dream check.
Start writes a seat beat. `python3 -B memory/check.py beat --seat <seat>` records another beat.
These beats mean start or explicit activity. They do not prove a standing process is alive.
The independent health launchd example must be loaded separately from dream.
The job runs its code half first. It writes a completed manifest after both halves finish.
The model half only writes memory/proposals/<date>.md. It never applies a page or database change.
A failed model half keeps the code half. Health records the result of each half.
No configured model transport records skipped: no model. The job still passes.
The independent check also handles invalid receipt and beat files. It records failure and still updates health.json.
The trusted inference adapter receives JSON on stdin and returns only a proposals string on stdout.
It has no agent tools. Do not select an interactive agent as its transport.
Choose it in config/models.yaml. Use this YAML-compatible JSON example:

```json
{"format":1,"dream":{"model":"nightly"},"models":[{"id":"nightly","runtime":"chosen-runtime","model":"chosen-model","adapter":"memory/adapters/inference.py"}]}
```

The example describes the interface. It does not install a transport or activate a model.
Adapter output: {"proposals":"Markdown proposals for review"}.
A second call keeps the original nightly proposal file.
Installed code proposals are the scope here. Product source synchronization is left for the release owner.
