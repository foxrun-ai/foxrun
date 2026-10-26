---
type: doc
workspace: system
timestamp: 2026-10-20T20:01:52-04:00
---
# Workflows

| File | Purpose |
| --- | --- |
| `research.yaml` | Runs three independent researchers and merges their evidence. |
| `research.md` | Explains research, its roles, and its skill bindings. |
| `review.yaml` | Runs a draft, routine read, recheck, and judgment read, with at most three repairs. |
| `review.md` | Explains review, its roles, and its repair limit. |
| `README.md` | Names the product workflows and their release command. |

Research and review ship to every user. Personal workflows remain in their source repository.
The installed shelf holds released copies. Edit source, then release. Never edit the shelf.

## Five pieces

- A workflow connects many skills in ordered steps.
- A flow belongs to one skill at `skills/<name>/flow.yaml`.
- A local workflow serves one workspace at `<workspace>/workflows/<name>.yaml`.
- A squad names who runs the steps in `config/squads/`.
- Models belong in `config/models.yaml`.

These workflows copy the approved dev-lean role settings into their members.
The runner reads members; it does not load squad files or change model settings.

## Release

```sh
python3 "$FOXRUN_HOME/skillwright/tools/skill_ship.py" ship --workflow research --source /path/to/source/research.yaml --dry-run
python3 "$FOXRUN_HOME/skillwright/tools/skill_ship.py" ship --workflow amazon-audit --workspace shop --dry-run
```

Remove `--dry-run` only for an authorized release.
The second command promotes the local workflow to the shared shelf. It keeps the local source and creates the shared source in `<portfolio>/skillwright/workflows/`.
A default source is `<portfolio>/skillwright/workflows/<name>.yaml`.
The source-tree command also finds its product workflows.
The installed tool requires `--source` for product authoring source.

Names use one or two lowercase words with dashes.
A longer name needs `--approval <id>` with an approval that names that workflow.
The friend test remains a human check. Existing local names do not change.

The runner reads local workflows first, then the shared shelf, then the released product snapshot.
Installation and product workflow releases keep that snapshot in `skillwright/workflows/.product/`.
This is release storage. It is not an authoring source.
Product updates preserve workflows marked `owner: person` in the shelf release record.
