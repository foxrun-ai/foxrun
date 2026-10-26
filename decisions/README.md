---
type: doc
workspace: system
timestamp: 2026-10-19T18:21:58-04:00
---
# Decisions

Read decisions with the installed command:

```sh
python3 ~/.foxrun/decisions/decisions.py list --db ~/.foxrun/data.db
python3 ~/.foxrun/decisions/decisions.py show DECISION_ID --db ~/.foxrun/data.db
```

The command opens the database read-only for list and show.
Add and update use the checked work writer.
Read [command code](decisions.py), [approval code](approve.py), and [the module definition](blueprint.sql).
The switch carries the existing tracker unchanged.
Follow [the global contract](../profile/AGENTS.md) for approval rules.
