---
name: snapshot
description: "Save a blessed chat span word for word as a numbered file: a dated snapshot in the workspace history, with provenance. Use when the person says snapshot this, save this moment, lock this in, preserve this exchange, or blesses exact chat text to keep."
kind: knowledge
---

# Snapshot

A snapshot keeps the person's exact words. It never paraphrases. It runs only on the person's blessing.

## Steps

1. Get the person's explicit blessing. Never snapshot on your own judgment.
   Done when: the person said to keep this span.
2. Resolve the owning workspace and the exact span. Read the workspace `AGENTS.md`. Stop if the workspace folder is absent. If the span bounds are unclear, ask one sharp question.
   Done when: you can name the first and last line of the span.
3. Pick the file: scan `<workspace>/history/snapshots/` and take the next free `YYYY-MM-DD-NNN-<kebab-subject>.md` number for today. Get the date with `date`.
   Done when: the path is free. Never reuse a number or overwrite a file.
4. Write the frontmatter: `type: snapshot`, `workspace`, `session`, `agent`, and a `timestamp` with its UTC offset. Then write the span word for word. Keep any short context or source line outside the quoted span, so no one mistakes it for the person's words.
   Done when: the body matches the span exactly.
5. Land one receipt for the write with the `log` skill.
   Done when: the receipt shows in `log.py show`.
6. Report the path only.
   Done when: the file exists at that path.

## Gotchas

- A secret in the span: replace only the secret with `[REDACTED]`, and say a redaction was needed.
- A number collision: rescan and take the next free number.
- Never edit, replace, or delete an earlier snapshot.
- `close` does not run this skill. It fires only on the person's blessing.
- Follow `~/.foxrun/config/gates.md` before any gated action.
