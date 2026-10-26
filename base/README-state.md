---
type: doc
workspace: system
timestamp: 2026-10-19T20:33:00-04:00
---
# Exports and rebuild

Three tools keep a text copy of the database and prove that a copy can rebuild it.
They use the Python standard library. The two `state_*` tools also use local Git.

| Tool | What it does | Who runs it |
|---|---|---|
| `backup.py` | Writes a read-only JSONL snapshot of every table, one file per table | The nightly job (`memory/dream.py`), and you |
| `state_jsonl.py` | Writes a full export with a `manifest.json` of counts, row hashes, and schema | You, by hand |
| `state_rebuild.py` | Builds a new database from the blueprint and a `state_jsonl.py` export, then compares every row | You, by hand |

## The nightly export

```sh
python3 base/backup.py run ~/.foxrun/data.db --output-dir ~/.foxrun/state
```

The nightly job runs this command. It writes `~/.foxrun/state/<table>.jsonl`.
The database opens read-only. Each file is replaced in one step. Equal rows give equal bytes.
The default output folder is `state/` beside the database.
`work.py` writes there after each change, even with a different `--receipt-root`.
The handoff hook reads export metadata from the selected database's `state/` folder.
`backup.py` writes no `manifest.json`, so `state_rebuild.py` cannot read its output.

## A full export and a rebuild

Give every path. The old defaults name a test layout (`home/.local/share/foxrun/data.db`, `code/foxrun-modules`).
Every path must be inside the root you give.

```sh
python3 base/state_jsonl.py ROOT --database ROOT/data.db --exports ROOT/exports
python3 base/state_jsonl.py ROOT --database ROOT/data.db --exports ROOT/exports --check all
python3 base/state_rebuild.py ROOT --database ROOT/data.db --exports ROOT/exports --blueprint ROOT/base/blueprint --output ROOT/rebuild/data.rebuilt.db
python3 base/state_rebuild.py ROOT --database ROOT/data.db --exports ROOT/exports --blueprint ROOT/base/blueprint --check all
```

Work on a copy: put a copy of `data.db` and of `base/blueprint/` under a new ROOT.
The exporter holds one read transaction. It records counts, row hashes, schema, and metadata in `manifest.json`.
Old export files make it refuse. Archive them before the table set changes.
The exporter makes a local Git repository with no remote. It makes no commit, push, or network request.

The rebuild does not run SQL from the export manifest. It builds the schema from the blueprint.
It loads the saved rows before it installs the guards. Foreign-key checks wait until all rows load.
It checks every row and the schema before it keeps the new file. The original database does not change.
An older rebuild moves to `rebuild/data.rebuilt.db.archive/` when its inputs differ.

When the original database is lost, add `--without-original`.
The rebuild then compares itself with the hashes in the export only.
Linked source files need their own backup. These tools rebuild only the database.

## Test

No unit test covers these three tools yet. The two `--check all` commands above are the proof run.
