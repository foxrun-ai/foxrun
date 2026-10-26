---
name: recall
description: "Recall what Foxrun knows: walk the memory ladder of State, Semantic, Procedural, Episodic, Raw, then Search last. Use when the person asks what happened before, what was decided, how something works, or to recall something the start page does not answer."
kind: knowledge
---

# Recall

The start page is working memory. Read it first. Use this ladder only when the start page does not answer.
Go down the ladder in order. Stop at the first step that answers. Name that step in the answer.
This skill reads Foxrun memory. It does not replace a runtime's own memory feature; a runtime's notes are a copy, never the record.

## Steps

1. **State:** what is ruled, open, blocked, next, or a number. Use the question table on the start page, then the tracker: `python3 ~/.foxrun/work/program.py --db <tracker> --receipt-root <workspace folder> show`, `python3 ~/.foxrun/foxrun.py rulings <words>`, and `sqlite3 -readonly <tracker>` on `tasks`, `decisions`, `approvals`, and `active_lessons`. `STATE.md` is a readout of the rows.
   Done when: a row answers, or you can say no row does.
2. **Semantic:** what a thing is or how it works. Read the workspace `wiki/`, then `~/foxrun/atlas/LIBRARY.md` for anything wider. For one word, run `python3 ~/.foxrun/foxrun.py glossary <term>`.
   Done when: a page answers, or none does.
3. **Procedural:** how to do a job. Read the skill, then the workspace `AGENTS.md`.
   Done when: a skill or contract line answers, or none does.
4. **Episodic:** what happened. Read the last handoff in `<workspace>/history/handoffs/`, then `<workspace>/history/daily/`, then `<workspace>/history/LOG.md`. For a past session, use the `runtime-session-search` skill.
   Done when: a dated note or session answers, or none does.
5. **Raw:** only to check a source. Read `<workspace>/raw/` or `~/foxrun/atlas/raw/`.
   Done when: the source confirms or refutes the claim.
6. **Search last:** `rg "<words>" <folder>` for exact words. `qmd query "<question>" -c <collection>` to search by meaning, when QMD is installed. Check every hit against the live file or row.
   Done when: a checked hit answers, or you say "No match for '<query>' in <places searched>."
7. Answer. Lead with the answer, then the step name and the source: a row id with its title, or a file path and date.
   Done when: the answer names its step and its source.

## Gotchas

- A row beats a page, and a newer ruling beats an older page. When they disagree, say so and cite both.
- When the person corrects a recalled fact, the correction wins. Say where the stale fact came from. File a durable correction in its home in the same turn: a row, `~/.foxrun/profile/USER.md`, or the wiki page.
- When the person narrows the question, answer only that slice.
- For a session name, never invent a title. Return a stored title or id you checked against the transcript.
- A search hit is a lead, not an answer. Read the file or row before you quote it.
- Never read `system/`, `.credentials`, `.env`, or auth files while you search.
