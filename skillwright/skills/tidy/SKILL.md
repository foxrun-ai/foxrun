---
name: tidy
description: "Run the Keeper nightly upkeep by hand with the installed nightly job: lint, the dream code half, the memory check, the workspaces view, and the state push. Use when the person says `/tidy`, when the start page says the nightly is OLDER THAN 36 HOURS, or when a failed nightly needs a rerun."
kind: knowledge
---

# Tidy

`/tidy` runs the same job the scheduled nightly runs, now. It uses the installed nightly, never a copy.

## When

- The person says `/tidy`.
- The start page `NIGHTLY` line ends with `OLDER THAN 36 HOURS: run /tidy`.
- The nightly failed and its fault is fixed.

## Steps

1. Check that no nightly runs now: `ls ~/.foxrun/runs/.dream.lock`.
   Done when: the file is absent. If it is there, stop and say who holds it. Never remove it.
2. Run the installed nightly the way the scheduled job runs it:

   ```
   cd ~/.foxrun && FOXRUN_HOME=~/.foxrun FOXRUN_PORTFOLIO=~/foxrun PYTHONDONTWRITEBYTECODE=1 python3 -B ~/.foxrun/cron/nightly.py
   ```

   Add `--dry-run` to see the steps with no push and no dream write.
   Done when: it prints its last line, `Nightly: exit <n>; ...; <receipt folder>`.
3. Read the receipt: the newest `~/.foxrun/runs/nightly/*-nightly/receipt.json`.
   Done when: you have the exit and the result of each step: lint, dream, check, workspaces view, push.
4. Rebuild the start pages: `python3 ~/.foxrun/memory/state.py build --all`.
   Done when: the `NIGHTLY` line shows this run and has no `OLDER THAN 36 HOURS` flag.
5. Report one line for each step, ok or failed, with the finding counts and the receipt path.
   Done when: each failed step has a task or bug row the same day (the Keeper loop).

## Gotchas

- The job runs at low priority, so it can take a few minutes. Wait for its last line.
- A finding is not a fix. Do not fix findings inside `/tidy`; file them.
- The push step sends only `~/.foxrun/state/` to its own remote, as the nightly does each night.
- If `~/.foxrun/cron/nightly.py` is missing, say so and stop. Do not run a source copy.
- Nothing is cleared or deleted. Receipts stay in `~/.foxrun/runs/nightly/`.
