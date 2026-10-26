---
type: doc
workspace: system
timestamp: 2026-10-19T19:04:46-04:00
---
# Nightly job

`cron/nightly.py` is the one nightly command.
It runs `base/lint.py`, `memory/dream.py`, then `memory/check.py`.
It runs both memory commands even when an earlier command fails.
It returns the first failure code after all three commands finish.
Lint findings and a Keeper receipt land in `runs/nightly/<UTC-time>-lint/`. The nightly receipt is `runs/nightly/<UTC-time>-nightly/receipt.json`.
The Keeper reviews findings and tracks repairs through task rows.
When a step fails, the job asks macOS to show one notification and writes `runs/nightly/<UTC-time>-nightly/alert.json`.
The alert receipt records whether macOS accepted the notification.
With `config/nightly.local.json`, the job also sends one short Telegram message through the Bot API `sendMessage`.
The message is the start page line: ok or failed and when, then the last GitHub backup.
That file holds only secret references and the reader command. The values stay in memory and are never stored.
It stays local and never ships. With no file, the job sends no message. A dry run sends none.
The result lands in `receipt.json` under `message`: `sent`, `message_id`, and no token or chat id.
`cron/watchdog.py` runs under a separate five-minute launchd job.
`cron/tests/test_watchdog.py` proves the watcher reads launchd status and the last receipt before it alerts. It checks whether the nightly label is loaded and whether the last receipt is within its schedule window.
It also checks whether the newest receipt shows a failed step or a nonzero exit.
A stopped, stale, or failed job gets its own macOS alert and receipt. The nightly job cannot set the watchdog status.
`--workspaces DIR` selects the portfolio. `FOXRUN_PORTFOLIO` supplies its default, then `config/person.json`, then `~/foxrun`.
`--dry-run` passes `--dry-run` to dream and `--readonly` to check.
`--schedule` prints the launchd job; it loads nothing.
The memory commands also run without the word `run`.

## The clock

The installer turns the job on. `install.py --no-schedule` leaves it off.
`cron/schedule.py` renders `launchd/session-nightly.plist.template` with the person's paths.
The template holds `@USER_HOME@`, `@FOXRUN_HOME@`, `@FOXRUN_PORTFOLIO@`, `@PYTHON@`, and `@LOG_DIR@`.
The clock comes from `config/dream.json`: `hour` and `minute`, or `interval_seconds` (60 or more).
The job file is `~/Library/LaunchAgents/com.foxrun.session-nightly.plist`.
The independent watcher is `~/Library/LaunchAgents/com.foxrun.session-nightly-watchdog.plist`.
It loads with `launchctl bootstrap gui/<uid>`.
Logs land in `~/.local/state/foxrun/session-nightly/`.
A matching job file is left alone. A different one is kept as `.bak-<time>`, then replaced and reloaded.
`python3 cron/schedule.py --compare FILE` shows how a job file differs from the render; it writes nothing.
`python3 cron/schedule.py --on` turns the job on after a change to `config/dream.json`.
To turn it off: `launchctl bootout gui/$(id -u)/com.foxrun.session-nightly`, then delete the job file.
Tests set `FOXRUN_LAUNCHCTL` to a stub. They never load a job into launchd.

## Dream and check

Dream has three words: `run`, `code`, `report`. No word means `run`.
`run` does the code half first: it builds `STATE.md` and writes the tables into `backups/jsonl/`.
Then it does the model half. The model half needs `FOXRUN_JEV_RUNNER` and an existing task for its run.
With no runner the model half is skipped. The report says so, and the command returns 0.
Each night leaves one folder: `runs/nightly/<date>-dream/`. `python3 memory/dream.py report` prints its report.
One memory job runs in a home at a time. A second one fails at once with exit code 3 and changes nothing.
The check command accepts `--workspace`, `--transcript`, and `--handoff`.
It reports skipped checks when their inputs are missing.
`nightly.py` passes these options when supplied.
The default job does not claim that every check ran.
