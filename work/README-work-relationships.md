---
type: doc
workspace: system
timestamp: 2026-10-19T19:35:51-04:00
---
# Work relationship guards

`work_relationships.py` audits the two side tables from the private owner-split proposal.
It does not discover databases, route work, move rows, or approve a cutover.

The default command opens one explicit database read-only:

```sh
python3 work_relationships.py --db /absolute/path/to/copy.sqlite
```

The audit checks the exact proposed `links` and `goal_mirrors` column and foreign-key shapes.
It checks only `goal` and `project` generic-link subjects.
It reports missing subjects, invalid types, invalid active flags, hash format defects, and foreign-key defects.
It reports guard trigger coverage without requiring guards for a read-only audit.
Conflicting same-name guard SQL fails the audit. Missing guards remain a separate installation state.
SQL comparison normalizes syntax outside quotes and preserves quoted literal bytes.

Mirror freshness needs explicit source bindings:

```sh
python3 work_relationships.py \
  --db /absolute/path/to/target-copy.sqlite \
  --source foxrun=/absolute/path/to/source-copy.sqlite
```

Each database uses its own read transaction. The snapshots are not cross-store atomic.
The comparison checks the recorded hash against the local and explicit source goal rows.
A matching SHA-256 reports freshness for those snapshots. It does not authenticate the writer or source file owner.
The target and its hardlinks cannot act as a source.
A source row marked in that source's `goal_mirrors` table is non-authoritative and uncheckable.

Guard installation requires an existing disposable copy and an exact attestation flag:

```sh
python3 work_relationships.py \
  --db /absolute/path/to/disposable-copy.sqlite \
  --install --disposable-copy
```

Installation validates the schema and current relationships inside one `BEGIN IMMEDIATE` transaction.
It installs only fixed SQL from the helper. It accepts no caller SQL.
It validates any same-name trigger before reuse and rolls back on failure.
It does not create or migrate tables.
Every opened SQLite connection closes on success and error.

The triggers enforce these boundaries:

- `links.subject_type` is `goal` or `project`.
- Each generic-link subject exists in its local table.
- Each new or updated link keeps `active` in `0,1` and a lowercase hexadecimal 64-character source hash.
- A linked subject cannot be deleted, have its key changed, receive another row's key, or be replaced.
- Mirror goal rows cannot be inserted over, updated, deleted, replaced, or overwritten through a destination-key update.
- Mirror metadata cannot be inserted, updated, deleted, or replaced after guard installation.

The final mirror rule intentionally blocks ordinary refresh SQL.
Mirror refresh therefore uses a sealed maintenance plan and one target transaction.
This candidate does not define a refresh token, authenticate a sync process, or grant refresh authority.
SQLite triggers do not constrain the database file owner, who can alter the schema or file.

## Mirror maintenance on a disposable copy

Planning is read-only. It requires the target and every source binding.
The detailed plan goes only to an explicit create-only private JSON file:

```sh
python3 work_relationships.py \
  --db /absolute/path/to/target-copy.sqlite \
  --source authority=/absolute/path/to/source-copy.sqlite \
  --plan-refresh /absolute/private/path/refresh.json
```

The command prints only the plan path, digest, source count, and action count.
The private plan seals source identities, source goal hashes, source mirror-authority metadata, target schema, all target table hashes, and exact row changes.
Each source and target uses an independent read transaction during planning.
These snapshots are not cross-store atomic.

Application requires the retained plan digest and an explicit disposable-copy attestation:

```sh
python3 work_relationships.py \
  --apply-refresh /absolute/private/path/refresh.json \
  --plan-sha256 EXACT_DIGEST \
  --disposable-copy
```

Application opens the target with `BEGIN IMMEDIATE`.
It refuses changed source goals, source authority metadata, target rows, schema, guards, paths, or file identities.
It rechecks every physical file identity after the target lock and before commit.
It temporarily removes only `goal_mirror_row_no_update` and `goal_mirror_metadata_no_update`.
It copies the planned source goal fields without changing the goal ID.
It updates only `source_hash` and `source_captured_at` in the mirror row.
It restores and validates every reviewed guard before commit.
Any failure rolls back the goal, mirror metadata, receipts, and trigger changes.

If the exact current `activity` schema exists, application inserts one hash-only activity row per changed goal.
Each row uses `subject_type='goal'` and the exact goal ID, so normal goal history can find it.
It does not change or remove earlier history.
An exact retry reports replay and does not insert duplicate activity.
The digest proves equality with a reviewed plan. It does not authenticate a person or source writer.
Only an external caller can attest that a target is disposable and the plan is approved.
An uncooperative process can replace a database path after the final identity check.
The helper cannot make filesystem path checks and SQLite commit one atomic operation.

Existing task writes remain outside these triggers.
The current `work.py` schema validation still accepts a guarded database.
The legacy store remains authoritative until the owner split receives separate approval and integration.

## Private candidate receipt

- Scope: relationship audit and disposable-copy guards for the already proposed split only.
- Start: 2026-09-20T08:34:05-0400.
- End: 2026-09-20T08:39:11-0400.
- Elapsed time: 306 seconds.
- Requested worker: `configured-model`, high reasoning, Codex native subagent.
- Actual backend version and token usage: unavailable.
- Final test result: 9 tests passed in 0.104 seconds.
- Attempts: three. The first found a test-module loader error. The second passed. The third passed after exact-schema and trigger-isolation strengthening.
- Private proof: all three lead-reviewed target schemas passed read-only audit. Their database bytes stayed unchanged.
- No private row body or business value was printed.

Selected source hashes:

- `work.py`: `45a9844792fc39a9fdfbfcbc281a542dceca5767cb5d5801e39af2407e14e02b`
- `blueprint.sql`: `3a5743e5ca7c7a4a798ab780ce028ab2174f6a9ecf58aa47a6b15d9d71dd9af2`
- `2026-09-20-foundation-work-split.md`: `05f5032d3cecbac0da206ba8fc824a436c16ab4ec3c9887e5f3675900a897134`
- Lead-reviewed `rehearse_split.py`: `261aa737c331fb89f24a5355dc6c9504ccbbe73e03ba2b19b74c808c4dda3893`

### Lead correction receipt

- Start: 2026-09-20T08:41:16-0400.
- End: 2026-09-20T08:44:39-0400.
- Elapsed time: 203 seconds.
- Focused final result: 7 tests passed in 0.102 seconds.
- Attempts: two. The first exposed one incorrect synthetic tuple index. The corrected focused run passed.
- Candidate `work_relationships.py`: `9a3f61075756de248e46bcdd722452a5c0b0f0d0796e3f38b9c4a76557ecb43f`.
- Candidate `test_work_relationships.py`: `d336e25662443db3afcbd6b0f4a6ab0298b7ed8f5539be13a51dfa6a90b7199a`.
- Actual backend version and token usage remain unavailable.

### Destination-key correction receipt

- Start: 2026-09-20T08:47:18-0400.
- End: 2026-09-20T08:47:55-0400.
- Elapsed time: 37 seconds.
- Focused result: 2 tests passed in 0.037 seconds.
- The proof used `PRAGMA recursive_triggers=OFF` and retained every source and destination row after each refusal.
- Legal title updates and an ordinary task status update still passed.
- Candidate `work_relationships.py`: `99a78b41a7236d82acc4de11fc418a00472dd6d8c15d663887bacabcefa5f926`.
- Candidate `test_work_relationships.py`: `c105dcdf562f36ee2190acceb5ac1c5bb6035ac2a72392c04a49fae6ee77b4fc`.
- Actual backend version and token usage remain unavailable.
