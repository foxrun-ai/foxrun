---
type: doc
workspace: system
timestamp: 2026-10-19T19:35:51-04:00
---
# reader-check

Run this check before a table, file, folder, or program moves or leaves.
It lists old-name dependencies and runs configured tests against an offline copy.
It never changes a source or performs a live move.

```sh
python3 base/reader_check.py --plan /path/to/plan.json --out /path/to/report
python3 base/reader_check.py --plan /path/to/plan.json --out /path/to/report \
  --run-tests --scratch /path/to/new-scratch
```

```json
{
  "thing": {"kind": "table", "name": "people", "database": "/state/service-example.db"},
  "roots": [{"path": "/source/service", "program": "service", "database": "/state/service-example.db"}],
  "readers": [{
    "program": "service",
    "workspace": "/source/service",
    "offline": true,
    "commands": [["/usr/bin/python3", "tests/rename_probe.py", "{copy}"]],
    "env": {"SERVICE_DB": "{copy}"}
  }]
}
```

Search roots include all relevant code, scripts, tests, skills, jobs, and contracts.
Each root can specify `program`, `database`, and `role` (`skill` or `contract`).
Declare database context only after checking the root's database owner.
`thing.aliases` accepts additional known spellings, such as ORM names or an installed command path.
Table searches also include database paths, service/module spellings, and snake-case ORM aliases.
Python SQL analysis expands constants, concatenation, table lists, and f-strings.
Unknown SQL arguments, including join, format, percent, dictionary, and attribute constructions, emit `needs a look`.
Python SQL context comes from SQL text, SQL APIs, or a SQL argument name.
Other unknown `execute` arguments remain possible readers and emit `needs a look`.
Generic calls such as `executor.execute(task)` do not create SQL rows.
JavaScript constructions need a SQL call or SQL structure before the built part, in either case.
Python follows SQL fragments through assigned expressions without a receiver-name list.
Shared JavaScript methods (`run`, `exec`, `get`, `all`) need a SQL argument.
Python also checks `read_sql`, `read_sql_query`, and `read_sql_table` calls.
Program searches include the module spelling, such as `small_talk` for `small-talk`.

`file`, `folder`, and `program` kinds use `thing.name` and `thing.path`.
For tests, that path can sit inside or outside the reader workspace.
An external target gets its own frozen copy, then separate baseline and renamed copies.
`{workspace}` names the copied workspace. `{copy}` names the copied database or renamed target.
Each test command must receive `{copy}` in an argument or environment value.
For non-table tests, `{original}` names the old target path in both copies.
Use it to test readers that still need that old path after the rename.
Use test commands that actually exercise that input. A supplied path alone cannot prove consumption.
Each reader root requires at least one command run in both baseline and renamed copies.
The command's `program` must match the root. Its reader `root` must name that exact search root.
`root` defaults to the reader's source `workspace`. Set `root` explicitly for a file or child-folder search root.
The source `workspace` must contain that root. One wide workspace cannot silently cover several roots.
Each root needs its own reader entry and command, even when several entries share a workspace.
If a dry test is impossible, only the named work lead may add a `dry_test_exemptions` entry:

```json
{"path": "/source/service", "by": "<work-lead>",
 "at": "2026-10-06T21:00:00+00:00", "reason": "Why no offline test is possible for this root."}
```

The path must name the exact root. The lead name and timestamp follow the confirmation rules below.
The runner cannot supply its own exemptions. An exemption never clears a found reader or another blocker.
Without a command or accepted exemption for every root, exit is nonzero.
When search finds no reader, the verdict is `search found no reader; not proven by a dry test`.
`--run-tests` with zero commands supplies no dry-test proof.
Relative commands run inside the copied workspace. Set `cwd` with `{workspace}` when needed.
An absolute `cwd` outside that copy is refused.

Baseline and rename use the same frozen source snapshot.
The table source uses SQLite's read-only backup API under a filesystem sandbox.
The test sandbox denies network access and writes outside scratch.
Test execution requires macOS `sandbox-exec`; other platforms can run the static scan.
Select offline unit tests. Do not select a daemon, send, channel pull, or model command.
Tests receive `PYTHONDONTWRITEBYTECODE=1`, disabled pytest plugin discovery, and a scratch `TMPDIR`.
Settings, secrets, dependencies, and symlinks do not enter the copied test workspace.
Supply configuration through the declared test environment instead of changing live settings.

`readers.csv` contains locations and identifiers. It contains no source text or argument values.
`sure=yes` means a confirmed old dependency. `needs a look` means source review is required.
Resolve a common-name match with a confirmation:

```json
{"path": "/source/other.py", "line": 12, "decision": "unrelated",
 "reason": "This local list has no database reader.", "sha256": "<current-file-sha256>",
 "by": "<work-lead>", "at": "2026-10-06T21:00:00+00:00"}
```

Put confirmations in the plan's `confirmations` array. `decision` accepts `reader` or `unrelated`.
Set `work_lead` in the plan. Only that lead may confirm; the scanner agent cannot confirm its own rows.
`by` must match `work_lead`; `at` must be an ISO timestamp with a timezone.
A confirmation applies only to the named line and current source bytes.
Settings use an identifier-only Python search and byte hash; no settings values reach outputs.
This search works without `rg`. Settings matches use the same hash-bound confirmation.
The scanner cannot downgrade a proven SQL reader through an `unrelated` confirmation.
Unrelated matches remain visible as `sure=no`. Stale confirmations refuse clearance.
Every excluded file or tree appears in `scan.json`, with `category` and `requires_confirmation`.
Dependency trees and data files are listed only; they need no lead confirmation.
Closed private files and binary files require confirmation.
So do logs, sessions, raw, build, dist, target, vendor, and coverage trees.
These places also appear as line 0 rows in `readers.csv`.
Each required place blocks until the lead confirms its exact path with decision, reason, by, and at.
Line 0 confirmations use path-only lead attestation, with no content hash.
Never open closed secret or settings files to confirm them.
Private names match whole words; `tokenizer.py`, `authors/`, and `secretary.py` remain searchable.
A confirmation records the lead's own look at the place, never a list copied from `scan.json`.
Protected private folders stop the whole root from being searched.
The verdict lists these roots plainly, including after path-only confirmation.

Private-named source code is searched in memory; outputs contain paths, lines, and match kinds, never line text.
Names use whole private words: auth, oauth, token(s), secret(s), credential(s), key(s), and password(s).
The fixed source extensions are:

```text
.py .go .ts .tsx .js .jsx .mjs .cjs .rb .rs .java .kt .swift .c .h .cpp .cs .php .sh .zsh .bash .sql .lua
```

`.env*` stays closed, whatever its extension.
Key formats stay closed: `.pem`, `.key`, `.p12`, `.pfx`, `.keystore`, `.jks`, `.crt`, and `.cer`.
This includes names equal to those formats and chained extensions such as `server.key.py`.
Private key names stay closed: `id_rsa*`, `id_dsa*`, `id_ecdsa*`, `id_ed25519*`, and `id_ed448*`.
Protected folders stay closed: `.ssh`, `.gnupg`, `.aws`, `.credentials`, `secrets`, `mcp`, and `.codex`.
The existing vault system boundary stays closed.
Private-named data/settings stay closed, including `.json .yaml .yml .toml .ini .cfg .conf .txt .plist .xml .csv .db .sqlite`.
Unknown extensions and files without extensions also stay closed when their paths have private words.
Files matched by repository or nested `.gitignore` rules stay closed.
Repositories use `git check-ignore --no-index`; Git decides negated exceptions too.
Outside repositories, `**/` matches zero or more folders; `*` stays within one folder.
Outside repositories, negated exceptions remain closed; unreadable ignore rules also keep contents closed.
Source files get a first look before any identifier search or test copy.
The first look can open bytes. It stores no content and does not count as a source search.
A PEM header stops the file, including after whitespace or source code. Mostly non-code or encoded text stops it too.
Rejected files appear by path at line 0, count as closed, and require lead confirmation.
This includes neutral source names such as `module.py`.
Quoted base64 values with at least 40 encoded characters stop the first look when their encoding is valid and canonical.
This includes assigned keys, URL-safe or unpadded base64, and base64 within data URIs.
The rule closes base64 image and font data too. It conservatively closes other long encoded literal values.
Exactly 64 hexadecimal characters, including uppercase SHA-256 constants, do not trigger this rule.
A comment containing only a PEM header remains searchable. A header alone contains no key payload.
Rejected values never enter identifier searches or scratch copies. Reports keep only the file path at line 0.
Private-named source files never enter workspace or target test copies.
Their reader rows say `found; not dry-tested: private-named file` and still block clearance.
The lead confirms these readers by path with line 0 and no content hash.
Key detection is a best effort.
The guarantee is that no file content is shown or kept after the run, unless the lead explicitly keeps copies.

`scan.json`, `verdict.json`, and stdout report `private_named_source_files_searched` and `private_named_files_closed`.
They state that closed files still need work lead confirmation by path.
Closed-file counts include files below protected folders, counted by path metadata without opening contents.
Overlapping roots count each identical path once; different alias paths remain separate.

`verdict.json`, `scan.json`, and `test-results.json` include write timestamps.
The verdict records search gaps, old readers, test exits, and recreated old tables.
Both `readers.csv` and `verdict.json` record confirmation by, at, reason, and decision, including rejected confirmations.
Output and scratch paths must stay outside checked roots, workspaces, targets, databases, vault, and `~/foxrun`.
They also stay outside `~/bin`, `~/.local/share/foxrun`, and `~/Library/LaunchAgents`.
The same rule protects checked symbolic-link destinations.
Test setup errors save a refusal and the available scan rather than losing the report.
Test stdout and stderr are discarded because they can contain private values.
Keep richer sanitized failure evidence in the reader's own test adapter when required.
The program removes every test copy when the run ends, including errors and interrupts.
It creates copies with mode 700 under the supplied new scratch folder, outside repositories and the vault.
Reports must stay outside that disposable scratch folder. Existing scratch folders remain untouched and cause refusal.
After a normal run, `private_scratch_copy_paths` is empty. `private_scratch_copies` remains its compatibility alias.
Only the lead can request retention with `--keep-copies --keep-copies-by <work_lead>`.
The name must match the plan's `work_lead`; the verdict lists every kept file path and `copies_kept_by`.
These retained copies are private. A cleanup failure stops clearance and lists any remaining file paths.

Exit codes: `0` clear to move; `1` refused; `2` unsafe or invalid input, or unavailable test sandbox.
A clear verdict requires no old reader, unresolved match, unconfirmed skipped place, or scan gap, and passing configured tests.
Exit 2 also stops the move. It never means clear.
Passing tests cannot override an old name or an automatically recreated old table.
The verdict never authorizes a live mutation.
Its first fields and the printed line include `unsearched_places_cleared` and `confirmed_by`.
This count covers only required unsearched places cleared by accepted lead confirmations.
Line confirmations and listed-only dependency/data paths do not increase it.
The count discloses unsearched places even when the verdict says `clear to move`.
File, folder, and program names built at run time can escape the static search; use the dry test.

```sh
python3 -m unittest discover -s base -p 'test_reader_check*.py'
```
