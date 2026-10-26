---
type: doc
workspace: system
timestamp: 2026-10-19T23:27:47-04:00
---
# Tests

Tests the launcher, the installer, the day-one flow, and the workspace database.
Use them to prove a change did not break them.

From the system folder, run them all:

```sh
python3 -m unittest discover -s tests -p "test_*.py"
```

The installer tests need `install.py`, so they run from the product folder only. An installed home skips them.

## Build only

| File | Purpose |
| --- | --- |
| `test_fresh_install.py` | Runs a new person's install, doctor, start, and first session on a clean home. It needs `install.py`, so it does not ship. |

## Files

| File | Purpose |
|---|---|
| `test_seat_resolution.py` | Checks personal seat priority, each reader, and install protection in temporary homes. |
| `README.md` | Explains the launcher, installer, and workspace tests. Use it to find the test commands. |
| `test_after_compact.py` | Checks that compaction shows open handoff items and active lessons. |
| `test_day_one.py` | Checks a first install and first task with isolated sample homes. |
| `test_foxrun.py` | Checks launcher commands and doctor results in isolated test homes. |
| `test_workspace_lead.py` | Checks generated lead boots, name collisions, workspace exclusions, and a staged first session. |
| `test_update.py` | Checks an older committed install update, personal byte preservation, reruns, failure rollback, and unsafe paths. |
| `test_install.py` | Checks installer files and settings in isolated test homes. |
| `test_seat_boots.py` | Checks seven seat boots, shipped handoff commands, boot files, person names, and taken skill names. |
| `test_start_workspace_db.py` | Checks that start selects the workspace database without exposing owner rows. |

| `test_secret_check.py` | Proves commit blocking, safe output, bounded history, hash metadata, synthetic fixtures, and speed with fake values generated at runtime. |
