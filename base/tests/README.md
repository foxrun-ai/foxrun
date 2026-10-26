---
type: doc
workspace: system
timestamp: 2026-10-19T23:49:25-04:00
---
# Base tests

Tests the base package: install, pages, lint, the database, and the guards.
Use them to prove a change did not break them.

From the system folder, run one file:

```sh
python3 -m unittest base.tests.test_install
```

## Build only

| File | Purpose |
| --- | --- |
| `test_tool_shelf.py` | Checks that `config/templates/tools.yaml` pushes shelf tools into each workspace's `TOOLS.md`, and that every product tool page has a shelf row. It reads the product `tools/` folder, so it does not ship. |

## Write checks

| File | Purpose |
| --- | --- |
| `test_write_contract.py` | Proves fail-closed write input, per-rule write behavior, fast scoped checks, and workspace contract discovery. |
| `test_words.py` | Checks sourced word writes, duplicate refusal, TSV shape, rebuilt pages, and failed-write recovery. |
