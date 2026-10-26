# Codex Desktop native delegation acceptance

These procedures create desktop state. T159 does not run them. Each is **TO RUN BY THE PERSON'S LEAD**.
The evidence note keeps this experiment out of the tracker, so each procedure expects zero tracker rows.

## Conversation during work

- Steps: Start C with a visible worker and valid return thread; continue two lead messages; steer the worker once; wait for its callback.
- Expected tracker rows: zero.
- Expected messages: two normal lead replies, one worker steering acknowledgement, then one completion callback with outcome, evidence, or blocker.
- Stop: stop after the first valid callback; stop earlier on wrong thread, expanded authority, or conflicting instructions.
- Result: NOT RUN — to run by Person's lead; no desktop thread was created.

## Callback delivery

- Steps: Start C with both thread IDs; require one callback; let the lead turn end; verify the callback appears in the named lead thread.
- Expected tracker rows: zero.
- Expected messages: exactly one visible completion callback with outcome, evidence, and any blocker.
- Stop: reconcile delivery before any retry; stop on the first valid callback or confirmed delivery failure.
- Result: NOT RUN — to run by Person's lead; no desktop thread was created.

## Worker failure

- Steps: Start C with a controlled failing command; require the worker to report failure without fixing outside its allowed rounds.
- Expected tracker rows: zero.
- Expected messages: exactly one callback naming failure, evidence, attempted allowed fixes, and the blocker.
- Stop: stop at the stated fix-round limit; do not start a replacement worker without direction.
- Result: NOT RUN — to run by Person's lead; no desktop thread was created.

## Duplicate reply

- Steps: Start C; after one valid callback, simulate an uncertain acknowledgement; inspect the lead thread before any resend.
- Expected tracker rows: zero.
- Expected messages: one completion callback only; no second callback after reconciliation finds the first.
- Stop: never retry blindly; stop if delivery cannot be reconciled and report uncertainty without sending again.
- Result: NOT RUN — to run by Person's lead; no desktop thread was created.

## Scheduled-check cleanup

- Steps: Create one D check with timing, evidence, and a stop rule; satisfy the condition; verify its final message and removal or disablement.
- Expected tracker rows: zero; one temporary native schedule during the test and zero active schedules after cleanup.
- Expected messages: one condition report, then one cleanup confirmation; no later empty check.
- Stop: stop and clean up when the condition is met, the run limit is reached, or evidence access fails.
- Result: NOT RUN — to run by Person's lead; no schedule was created.
