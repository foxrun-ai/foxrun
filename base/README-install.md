---
type: doc
workspace: system
timestamp: 2026-10-19T20:34:00-04:00
---
# Create-only workspace installer

`install_workspace.py` plans first. It applies only a saved plan that still matches its sources.
`install.py` calls it for the first workspace. You can also run it by hand.

## Plan

```text
python3 install_workspace.py \
  --modules-root ~/.foxrun \
  --workspace-type personal \
  --modules base,work \
  --target-workspace fixture-workspace \
  --install-timestamp 2026-09-20T10:00:00Z \
  --approved-tags '["fixture"]' \
  --target /private/tmp/existing-sandbox \
  --live-vault-root /path/to/live/vault \
  --values-json /path/to/explicit-values.json \
  --plan-out /path/outside-target/install-plan.json
```

The installer builds no database. `--database` and `--by` are refused.
There is one database, `data.db` in the system home. A workspace never gets its own.
`install.py` builds the tables of every shipped pack, add-ons included, in that one file.
`--modules-root` is the folder that holds `base/` and `work/` (the system home or `src/`).
An add-on is any other folder there, or under its `modules/`, with an `install.json`. Its `requires` list is read from that file.

## Apply

```text
python3 install_workspace.py --apply /path/outside-target/install-plan.json
```

Apply reconstructs the plan from current manifests and recorded inputs before any write.
It also rechecks source hashes, the full target tree, placeholders, and destination boundaries.
It creates missing directories and files only. Existing files remain byte-identical, including empty files.
Run a fresh plan before a second apply. The fresh plan records installed paths as preserved.

## Boundaries

- The target must be an existing sandbox outside the declared live vault.
- Manifest paths must be safe relative paths. Only `if_exists: skip` is supported.
- Every declared `{{placeholder}}` needs an explicit string value.
- New Markdown receives explicit workspace, timestamp, and approved-tag metadata.
- The metadata stamp preserves each source status and the complete rendered body.
- Conflicting duplicate destinations fail before any target write.
- No database is created, opened, or changed. A plan with a database step is refused.
- Runtime, skill, config, and auth destinations are refused.
- The declared live vault and inferred source vault are both protected.
- Each module's `install.json` names the templates it writes. Base templates live in `templates/`.
- Generated stubs are installed package files. They are not accepted contracts or completed generated pages.
- Skills, runtime files, configuration, registries, deletion, and overwrite remain outside this package.

## Test

```text
python3 -B -W error::ResourceWarning -m unittest base.tests.test_install_workspace
```

Run it from the root of your Foxrun source checkout, the folder that holds `install.py`.
The selected-source integration test uses real manifests only in `/private/tmp`.
