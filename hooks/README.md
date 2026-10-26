---
type: doc
workspace: system
timestamp: 2026-10-24T16:10:09-04:00
---

# Hooks

The hook commands load session rules and keep handoffs across compacts.

| File | Purpose |
|---|---|
| `README.md` | Explains the files in this folder. |
| `after_compact.py` | Prints the current handoff open items before the resumed session continues. |

| `git/` | Holds shared Git hooks that check staged secrets and preserve original hooks. |

## Registration scope

Claude hooks stay at user scope in `~/.claude/settings.json`.
Keep Foxrun session-start, after-compact, before-compact, and session-end hooks registered.
Foxrun leaves every other hook you have registered as it is.
