---
type: module
name: base
workspace: system
timestamp: 2026-10-19T20:32:00-04:00
tier: base
built_by: ours
version: 0.1.0
requires: []
status: draft
tags: [object-model, data-model-definition]
---

# Base

Base builds the database and the workspace folders.
The table shape lives in `blueprint/`. The generated SQL lives in `schema.sql`, `views.sql`, and `guards.sql`.
Workspace templates live in `templates/`. The tests live in `tests/`.
Base needs only the Python standard library. Its small front matter reader ships here.

| `words.py` | Adds, changes, or removes one sourced glossary word and rebuilds its page. Removal requires a source reason. Checks: `tests/test_words.py`. |
| `paths.py` | Resolves each seat through workspace, personal, and shipped files. |
| `build_caps.py` | Builds the tool capability pages from the declared tool records. |
| `questions.tsv` | Holds 20 portable rubric cases for the grader self-test. |
| `t97_grade.py` | Grades saved rubric answers and checks the rubric with `--self-test`. |

From the system home, see the command options:

```sh
python3 base/build_database.py --help
```

Read [the system guide](../GUIDE.md) and [the global contract](../profile/AGENTS.md).
[`DOCUMENTATION.md`](../DOCUMENTATION.md) has one row for each file in base.

## Tool pages

Each page is the manual of one tool or one group of tools.

| Page | Tools | Use it to |
|---|---|---|
| [README-contract-lint.md](README-contract-lint.md) | `contract_lint.py`, `contract-lint-rules.json`, `contract_judgment.py` | Check chosen contracts without changing them |
| [LINT-GRAMMAR.md](LINT-GRAMMAR.md) | `contract_lint.py` | Read the exact forms the contract lint accepts |
| [README-contract-test.md](README-contract-test.md) | `contract_test.py`, `contract_runtime_adapter.py`, `contract-test-*.json` | Ask a model fixed questions with only the chosen contracts (deferred) |
| [README-install.md](README-install.md) | `install_workspace.py` | Plan, then apply, a create-only workspace install |
| [README-reader-check.md](README-reader-check.md) | `reader_check.py` | List what still uses a name before a move, and test the move on a copy |
| [README-recovery.md](README-recovery.md) | `recovery_bundle.py`, `prove_recovery_bundle.py` | Make and restore a private recovery bundle |
| [README-state.md](README-state.md) | `backup.py`, `state_jsonl.py`, `state_rebuild.py` | Export the tables to JSONL, and rebuild a database from an export |
| [README-workspace-pages.md](README-workspace-pages.md) | `page_indexes.py`, `workspace_pages.py`, `make_workspaces_view.py`, `workspace_reports.py` | Build the index, topic, library, team, and ops pages |
| [README-workspace-schematic.md](README-workspace-schematic.md) | `workspace_schematic.py` | Draw each workspace beside the model |

## The data.db commands

`schema.sql`, `views.sql`, and `guards.sql` are made by `regenerate.py` from `blueprint/`. Do not edit them by hand.
Each table has one command in `commands/`. Each command gives its table name to `core.py`.

```sh
base/commands/work_tasks --db ~/.foxrun/data.db --actor keeper --workspace system --session SESSION insert --json '{"title":"Example","status":"todo","reviewer":"lead","reviewed_by":"chief-of-staff"}'
base/commands/work_tasks --db ~/.foxrun/data.db --actor keeper --workspace system --session SESSION --reason 'The work is no longer needed.' update --id 1 --json '{"status":"canceled"}'
python3 base/lint.py --db ~/.foxrun/data.db
```

The database gives hidden ids and the event sequence. Commands give display numbers inside one transaction.
Commands stamp new times from the machine clock.
Each declared state change makes one change row. Equal values make no row.
Event rows only append. A rollback also rolls back its sequence number.
A raw SQLite write fails, because it does not have the command function that the guards in `guards.sql` ask for.
A process that controls its own SQLite connection can imitate that function. The guards do not stop hostile local code.
The nightly lint reports differences. It never repairs records from events.

Approval responses use `approved`, `rejected`, `edited`, or `discussed`.
An approval sends nothing. A review milestone does not allow a business action.
Change milestones use `verified`, `accepted`, `merged`, `released`, or `rolled-back`.
Page publication uses the `published` operation and a JSON `payload` with `version`.
Module release versions stay text. Integer record versions go up by one.

## Proposed writes

`lint_gate.py --mode write --target PATH --body FILE` reads one existing UTF-8 regular file.
`--body` is a file path. Inline text, unreadable files, secret files, and linked files fail closed.
The command checks the proposed bytes without changing the target.
`config/lint/rules.tsv` uses `write=blocking` to refuse a finding and `write=warning` to allow it.
Missing `write` columns retain the legacy warning behavior. Invalid values fail closed.
The existing `level` column controls full lint severity. Nightly Keeper reports retain both fields.
All current rules start as warnings, as the existing write gate did. Policy changes need the person's decision.
Contracts in immediate portfolio folders register workspaces for both lint modes and conformance.
`workspaces.tsv` retains shared-place roles only; workspace rows no longer control registration.
`tests/test_write_contract.py` proves input failures, timing, rule behavior, and new workspace saves.

## Commit secrets

`python3 base/secret_check.py` checks only staged additions. It uses no network.
It prints the file, line, and pattern name with `[REDACTED]` in place of each value.
A match or a scan error stops the commit. `op://` references and prose are allowed.
Entropy checks read quoted and unquoted values, including punctuation.
Python references and calls pass after syntax checks; file names never allow shell punctuation.
They allow UUIDs and SHA-256 digests in manifest, `.sha256`, dependency lock, and `integrity.json` files.
Known filesystem paths and shell variable references also pass.
Web storage, HTML data keys, and record identity fields allow structured lowercase IDs.
Generic keys still receive entropy checks.
Provider token patterns still apply in these files.
Fake, sample, and test fixture names allow only repeated short units or explicit placeholder words.
A fixture name alone never allows a random provider token or password.
Use `--history --repo PATH` for a bounded read of all refs.
The defaults are 1000 commits, 67108864 bytes, and 30 seconds per repo.
A bounded result never claims the full history is clean.
The check forces text diffs for binary files too. Git options can still bypass hooks.

| File | Purpose |
|---|---|
| `secret_check.py` | Checks staged additions and bounded Git history without printing values. |
| `secret-patterns.json` | Holds all token, key, cookie, bearer, and entropy patterns for both scans. |
