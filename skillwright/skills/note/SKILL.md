---
type: note
workspace: system
timestamp: 2026-10-26T14:20:00-04:00
name: note
description: "Write a note to the notes/ folder of the owning workspace, with the managed frontmatter and a lint check before the write. Use for /note, or when someone says write this down, make a note, or save these findings for later. A rule goes to lesson; a topic page goes to wiki."
kind: knowledge
argument-hint: "<title> [workspace]"
---

# note

A note is a working page: findings, a draft, a list, a comparison. It lives in `<ws>/notes/`.
A note is not the record. State lives in tracker rows, rules live in lessons, and durable knowledge lives in the wiki.
Each managed page follows `~/.foxrun/SCHEMA.md`, so the lint gate checks it before the write.

## Steps

1. **Pick the home.** Set `<ws>` to the workspace that owns the subject. If the content is a rule, use `lesson`. If it is a page about a topic or one named thing, use `wiki`. If it is a plan to build, use `spec`. Done when you know the note belongs in `~/foxrun/<ws>/notes/`.
2. **Name it.** Use `YYYY-MM-DD-<short-kebab-slug>.md`. Run `date +%Y-%m-%d` for the date. If the name exists, add a word; never overwrite. Done when the path does not exist yet.
3. **Draft it.** Write the draft to a scratch file first. Start with this frontmatter:

   ```yaml
   ---
   type: note
   workspace: <ws>
   timestamp: <date +%Y-%m-%dT%H:%M:%S%z, with a colon in the offset>
   ---
   ```

   Then one `#` title, then the body. Link sources; do not copy them. Done when the draft file exists.
4. **Check, then write.** Run `python3 ~/.foxrun/base/lint_gate.py --mode write --target <note path> --body <draft file>`. If it fails, fix the draft and run it again. Done when the gate passes and the note is at its path.
5. **Tie it to work.** If a task owns the note, add a comment: `python3 ~/.foxrun/work/work.py --workspace <ws> --db <tracker> --receipt-root ~/foxrun/<ws> --by <you> comment <task id> "note: notes/<name>.md"`. Done when the comment prints `ok`, or no task owns it.

## Gotchas

- Edit an existing note in place. Never replace a whole note you did not just make.
- Give the path of the note in your reply, so the person can open it.
