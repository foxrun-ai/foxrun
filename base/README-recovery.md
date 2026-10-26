---
type: doc
workspace: system
timestamp: 2026-10-19T20:35:00-04:00
---

# Private database recovery

`recovery_bundle.py` rebuilds a supported module database into a new file.
It never replaces a database or promotes the restored file into service.
This route is separate from the JSONL export (`backup.py`, see [README-state.md](README-state.md)).

The private bundle includes all physical tables, including mirrors and runtime tables.
Keep it outside Git and outside synchronized folders. It can contain contact, payment, and message data.
Use a private local folder such as `~/.foxrun/runs/<run>/` with mode `0700`.
The command creates bundle directories with mode `0700` and payload files with mode `0600`.
Choose a new bundle path and a new restore path. Existing paths are refused.

```sh
python3 base/recovery_bundle.py create \
  /absolute/path/source.sqlite /private/local/run/bundle \
  --modules work

python3 base/recovery_bundle.py restore \
  /private/local/run/bundle /private/local/run/restored.sqlite \
  --modules work
```

Choose exactly the installed modules; `base` is implicit. Add each installed add-on by name, for example `--modules work,people`.
The command reads the source through SQLite's online backup API before export.
The manifest binds schema, blueprint hashes, payload hashes, counts, row identifiers, and SQLite metadata.
Triggers install after row import, so restored history does not replay.
Schema SQL passes an authorizer and object-identity checks before the target is published.
Publication uses an exclusive hard link after the transaction and validation pass.

Hashes detect changed bytes. They do not authenticate an unknown sender.
Only restore bundles from the trusted local recovery route and trusted module blueprints.
The tool does not promise byte-identical files. It verifies logical rows, accessible implicit rowids, schema, metadata, integrity, and foreign keys.

## Compatibility limits

- Format: `foxrun-private-recovery-v2`. Recreate earlier private candidate bundles from their source.
- Exact module identities and current blueprint hashes are required. Stale module installations fail closed.
- The legacy planning database lacks current base-module identity tables. Its SQLite backups remain the current recovery route.
- Any foreign-key defect refuses bundle creation or restoration. The command never repairs source records.
- Virtual tables, generated columns, and hidden columns are unsupported.
- A table that shadows all implicit rowid aliases is unsupported when no integer primary-key alias exists.
- `$foxrun_rowid` is reserved when implicit rowids need capture.
- Schema statements must declare ordinary tables, indexes, views, or triggers with their actual object identity.
- A successful file restore does not verify external feeds, runtime loading, business acceptance, or a live cutover.

The reviewed integration used Python 3.14.4 and SQLite 3.53.0.
Minimum-version portability has not been established.

## Verification

```sh
python3 -B -m unittest base.tests.test_recovery_bundle -v
python3 base/prove_recovery_bundle.py
```

Run both from the root of your Foxrun source checkout, the folder that holds `install.py`.
The proof command uses synthetic data and retains its files under the system temporary directory.
It verifies nonempty mirrors, runtime tables, BLOB/null/Unicode values, sparse rowids, and trigger-generated history.
Its source fixture is not a production database.
