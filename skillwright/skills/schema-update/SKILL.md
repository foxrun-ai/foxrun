---
name: schema-update
description: "Update the data dictionary of Foxrun and its schema guide: add or change an object type or field in the seed, rehearse the apply on a copy, then regenerate and check the guide. Use when an approved model change adds or changes an object type, a field, or a table."
kind: knowledge
---

# Schema Update

The data dictionary is two tables in the system database: `object_types` (one row per object type) and `fields` (one row per field).
The system database is `$FOXRUN_HOME/data.db`; on a standard install that is `~/.foxrun/data.db`. Every workspace shares it. A workspace that still keeps its own database has its own copy of both tables until it migrates; its `RESOLVER.md` names that database.
The source is the Foxrun product file `src/base/dictionary-seed.sql`. The generated Schema Guide goes to `$FOXRUN_HOME/docs/schema`.

## Steps

1. Confirm the change is approved and name its target. Set the four paths:
   - `FOXRUN_HOME`: the installed system home.
   - `FOXRUN_DB`: the target database. A live apply uses `$FOXRUN_HOME/data.db`; a rehearsal uses a fresh private copy.
   - `FOXRUN_BACKUPS`: a separate backup folder.
   - `FOXRUN_SCHEMA`: the generated schema folder. A live apply uses `$FOXRUN_HOME/docs/schema`.
   Done when: the approval id and all four paths are written down.
2. Edit `src/base/dictionary-seed.sql`. Keep the seed idempotent. Put the object's meaning in `description`, `why`, and `example`. Put each field in `fields` with its type, order, requirement, and source.
   Done when: the seed holds the change and no generated file was edited by hand.
3. Rehearse on a fresh private copy. Run the apply twice:

   ```bash
   python3 "$FOXRUN_HOME/base/apply_dictionary.py" --db "$FOXRUN_DB" --backup-dir "$FOXRUN_BACKUPS"
   ```

   The first apply makes a backup and prints the exact undo command. The second must make no backup and leave the database bytes unchanged.
   Done when: both results match, and you kept the backup path and undo command.
4. Generate and check against the same copy:

   ```bash
   python3 "$FOXRUN_HOME/base/generate_schema.py" --db "$FOXRUN_DB" --out "$FOXRUN_SCHEMA"
   python3 "$FOXRUN_HOME/base/generate_schema.py" --db "$FOXRUN_DB" --out "$FOXRUN_SCHEMA" --check
   ```

   Done when: `--check` exits 0.
5. Prove the undo on the copy: `python3 "$FOXRUN_HOME/base/apply_dictionary.py" --db "$FOXRUN_DB" --backup-dir "$FOXRUN_BACKUPS" --undo latest`, or `--undo <exact backup path>`. Compare the schema, row counts, and `PRAGMA quick_check` with the original copy.
   Done when: the restored copy matches the original and `quick_check` says `ok`.
6. Show the lead the SQL and the proof: apply, repeat, generate, check, undo, and restore. Then run the live apply with the live paths.
   Done when: the lead said yes and the live `--check` exits 0.
7. Commit the changed seed and the generated output together.
   Done when: one commit holds both.

## Gotchas

- A new table changes database structure. It always needs the rehearsal and the lead's yes before a live apply.
- Never run a live apply during a rehearsal. Use a fresh private copy for each rehearsal.
- Never write tracker rows with hand SQL to fix a dictionary gap.
