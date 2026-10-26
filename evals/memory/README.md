# The memory evals

Run `python3 -B evals/memory/run.py` from the system home. Each numbered script also runs alone.
Eleven scripts ship (01-11). Each emits pass/fail, numerator, denominator, named cases, failures, and scope limits.
A failed eval means a failed requirement or missing proof. It is not a passing build test.
No model, network call, live financial write, runtime start, or source move runs.
Fixture mutation uses temporary homes only. The runner preserves failures instead of skipping an eval.

| Script | Scored requirement |
| --- | --- |
| 01_rule.py | Every shipped dictionary binding, unknown type and missing workspace; one declared home or review |
| 02_read.py | Seven CEO routes in three workspaces, plus all fourteen dated Sample Shop questions; no draft/raw read |
| 03_reliability.py | Eager model pen, replacement, stale cache, conflicting writers, replay and late source |
| 04_code_first.py | All twenty declared flow steps and references, then implemented nightly steps; model need and proposal boundary |
| 05_trace.py | One command verifies 100 row/page/raw/speaker/time chains and exact hashes; a changed quote refuses |
| 06_fetch.py | Seven ordinary routes and fourteen Sample Shop questions; one query, bounded rows/files and 12,000 bytes |
| 07_triangulate.py | Five registered links across raw/event/claim/contradiction, two independent origins and one-source flag |
| 08_field.py | Six departures each carry owner need, first-hand source evidence and cost; no relative-merit claim |
| 09_portability.py | Consulting, personal finance and healthcare core homes use installed scoped readers without commerce |
| 10_night_shift.py | Cold task, missing approval, stale source, wrong workspace, absent model and dead pending writer |
| 11_seven_nights.py | Seven real fault probes, retained events, independent health, live-week and local-alert delivery proof |

The source test names come from `round-b/03-tests.md:1-17`.
The detailed scoring and six departures come from `round-b/astra/own-design.md:782-846`.
The retired Move input files stay local. `run.py` does not score them.
Shipped data is labeled fake: the fourteen Sample Shop questions and the Sample Shop `field-evidence.json`.
Unknown approvals and unconfirmed payments remain unknown. Stale stock or receiving feeds do not become current facts.
Empty views do not prove zero replies, zero money owed, or an empty creator pipeline.

Some checks verify existing mechanisms on synthetic data. Their result includes that limit.
The fault recovery checks fail while the actual dispatcher keeps a failed step failed.
A later passing step and preserved events do not prove recovery of the failed mechanism.
The live-week check fails without seven explicit completed live receipts.
To supply live-week evidence, set `FOXRUN_EVAL_LIVE_WEEK` to a directory of approved, sanitized run receipts.
Each live receipt requires `mode: live`, `date`, `finished_at`, `result: pass`, and the current dream.py `code_sha256`.
Set `FOXRUN_EVAL_LOCAL_ALERT_RECEIPT` to an approved sanitized receipt of actual macOS alert delivery while the scheduler was stopped.
The alert check fails without that receipt; health.json alone does not prove alert delivery.
A mapped item is not a moved item. Synthetic proofs never satisfy the live-week acceptance.

After switch and database migration:
`python3 -B evals/memory/run.py --write --db <migrated-database> --workspace <workspace> --actor keeper --session <run-id>`.
The current table writer records one named measure and one work_measure_history score for each eval that runs.
Each note preserves cases, failures and limits, including failed evals. The runner verifies each value and note.
The runner creates no schema and refuses old trackers. Default scoring records no measurement rows.
Unit tests independently check the evaluator and failure handling. They are not the eleven design evals.
