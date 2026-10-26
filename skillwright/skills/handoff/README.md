---
type: doc
workspace: system
---
# Handoff product source

Copied from the existing handoff skill, with person names replaced by `@Person@`.
Install fills the name on the released shelves and keeps executable commands.

| File | Purpose |
|---|---|
| `README.md` | Lists the handoff source files and their purposes. |
| `SKILL.md` | Defines the existing handoff steps and boot sequence. |
| `bin/handoff-boot` | Selects the seat handoff sequence without blocking a session. |
| `bin/handoff-path` | Reserves a handoff path without overwriting an existing note. |
| `bin/handoff-precompact` | Writes a pre-compaction note from the settlement check. |
| `references/boot-hook.md` | Holds the existing optional boot hook registration instructions. |
| `references/precompact-hook.md` | Holds the existing optional pre-compaction hook instructions. |
| `replays/boot-pick-seat.json` | Checks that each seat receives its own newest handoff. |
| `replays/precompact-dirty-dry-run.json` | Checks the read-only settlement warning replay. |
| `replays/refuse-bad-subject.json` | Checks that invalid handoff subjects are refused. |
| `replays/reserve-first-path.json` | Checks the first handoff path reservation. |
| `tests/__init__.py` | Marks the handoff test package. |
| `tests/test_handoff_boot.py` | Checks handoff selection, sequence, and safe empty starts. |
| `tests/test_handoff_path.py` | Checks timestamps, reservations, and path collisions. |
| `tests/test_handoff_precompact.py` | Checks pre-compaction notes and settlement warnings. |
| `tests/fixtures/clean.jsonl` | Supplies a synthetic transcript with a recorded settlement. |
| `tests/fixtures/dirty.jsonl` | Supplies a synthetic transcript with an unrecorded settlement. |
| `tests/fixtures/created.jsonl` | Supplies a synthetic task creation transcript. |
| `tests/fixtures/tracker.sql` | Builds the synthetic handoff test tracker. |
