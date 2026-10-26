---
type: doc
workspace: system
timestamp: 2026-10-19T20:36:00-04:00
---
# Workspace schematic

One page shows each workspace beside the model: folders on disk, tables in the database.
Red marks a break. Each break names the decision it breaks and gives one plain line.

The commands use Python's standard library. They make no network call and no model call.
They read names and counts. They never read a file body, a hidden folder, or `archive/`.
The database opens read-only and immutable. Equal sources give equal bytes.

## Run

```sh
python3 base/workspace_schematic.py lint --vault ~/foxrun --db ~/.foxrun/data.db --out /path/to/review/schematic/schematic.json
python3 base/workspace_schematic.py validate --data /path/to/review/schematic/schematic.json
python3 base/workspace_schematic.py page --data /path/to/review/schematic/schematic.json --out /path/to/review/schematic/index.html
```

Give `--vault` (the portfolio) and `--db` (the system `data.db`).
`--root` is an old test layout: it reads `<root>/vault/` and `<root>/home/.local/share/foxrun/data.db`.
Each source has its own flag: `--vault`, `--db`, `--blueprint`, `--location-map`, `--classification`, `--excluded`, `--decisions-db`, `--rules`.
The page is one file. It holds its data. It opens from a file and requests nothing.

## What it reads

| Source | Used for |
|---|---|
| `workspace-schematic-rules.json` | The folder model and the database checks, each with its decision ids |
| Blueprint objects and fields | The workspace list, the modules, the tables, the views, the fields |
| `data.db` | The tables, views, and fields as they are; row counts; installed-module rows |
| The leftover classification and the excluded paths | Move, keep, and ask counts under each folder |
| The location map | Counts of other locations by kind |
| The decisions table | The name and status of every decision id the page shows |
| The workspace's old database files | Row counts of the tables the blueprint names as sources |

## Status words

| Word | Meaning |
|---|---|
| `matches` | It is where the model says. |
| `change` | It is there and differs from the model. A break. |
| `not on disk` | The model has it; the disk or the database does not. A break. |
| `decide` | The model is not decided for this line. |
| `not checked` | The lint could not read what it needs. |
| `optional` | The model allows the line to be absent. |

The page uses these status words exactly as the table writes them.

## Counting

A workspace's folder breaks are its `change` lines plus the model lines that are `not on disk` with nothing arriving.
A model line that waits for a moved folder is not counted again.
A table breaks when it is missing, when its fields differ from the blueprint, or when its records still wait in an old file.
`validate` recounts every summary number. It refuses a break with no decision id or with an id that is not ruled.

## What a false match would be, and the guard for each

| Risk | Guard |
|---|---|
| A required contract is absent and shows as optional | A slot with `required_with` is required when the workspace takes that module. `DESIGN.md` and `BRAND.md` are required with `commerce`. |
| A view stands where the blueprint says table, or a table where it says view | The lint reads the object kind from the database and compares it. A mismatch is `change`. |
| A folder is on disk and not in the tree | Every folder below an opened folder is a line. A nested folder takes the status of the line above it and is not counted twice. Folders inside a matching model folder show one counted `decide` line. |
| A status is shown with another word | The page prints the status value itself. Context sits beside the tag. |

A folder name that carries a person's name from the people shelf, or a protected name, is shown as `(private name)`.

## Change the model

Edit `workspace-schematic-rules.json`. Every line needs one or more ruled decision ids.
The page file only draws the data. It holds no workspace name and no rule.

## Limits

The lint reads the main database file only. Checkpoint a write-ahead log before a run.
Names at a workspace root are shown. Names below the root are shown only for folders the model names.
The row counts say whether records arrived. They do not prove row parity; the migration rehearsal does.

## Test

```sh
python3 -B -m unittest base.tests.test_workspace_schematic -v
```

Run it from the root of your Foxrun source checkout, the folder that holds `install.py`.
