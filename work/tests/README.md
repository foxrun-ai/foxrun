---
type: doc
workspace: system
timestamp: 2026-10-19T23:49:25-04:00
---
# Work tests

Tests the tracker, approvals, flows, and the handoff check.
Use them to prove a change did not break them.

From the work folder, run one file:

```sh
python3 -m unittest tests.test_work
```

## Build only

| File | Purpose |
| --- | --- |
| `replays/` | Recorded sessions and rows that `test_handoff_check.py` replays. They hold real recorded words, so they do not ship. The 10.16 leak audit asks for placeholder copies. |

`test_workflow_homes.py` proves workflow home precedence and starter bindings.
`fixtures/personal-workflows/README.md` names the build-only vote gate fixture.
`test_flow_workers.py` ships; only its vote test skips when the build-only fixture is absent.
