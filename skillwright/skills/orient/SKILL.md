---
type: note
workspace: system
timestamp: 2026-10-26T14:25:00-04:00
name: orient
description: "Orient a session at its start: read the start page, then say where we stand, what needs the person, and the next move, in three short lines. Use for /orient, at the start of a session, after a compaction, or when someone asks where are we, what is next, or what needs me."
kind: knowledge
argument-hint: "[workspace]"
---

# orient

A session never opens cold. Orient reads the start page and turns it into three lines the person can act on.
The start page is working memory: state, lessons, what is new, and the last handoff.
A summary from a compaction is not a source. Read the start page again.

## Steps

1. **Read the start page.** Run `python3 ~/.foxrun/foxrun.py start --workspace <ws>`. Skip this only when a hook already printed it in this session and no compaction came after. Done when you have the start page text.
2. **Read what needs the person.** Run these on the tracker the start page names:
   `sqlite3 -readonly <tracker> "SELECT id,title,status FROM needs_me"` and
   `sqlite3 -readonly <tracker> "SELECT id,title,status FROM close_now"`.
   If the last handoff has Open Items, plan from them. Done when you have the list, or know it is empty.
3. **Pick the next move.** Use the handoff's next step first, then `SELECT id,title,status FROM next_step`. Pick one. Done when you can name one task and the first step.
4. **Say it in three lines.** Where we stand. What needs the person, with each id and its title. Your next move. Then start the move if it is yours. Done when the person has the three lines and you started, or you are waiting on them.

## Gotchas

- Run `date` before you write the time or the day.
- Give each id with its title, read from the tracker in this turn.
- Do not repeat the start page back. The person can read it. Give the signal.
- Outside `~/foxrun` and `~/.foxrun`, follow the repository's own rules; the start command does not apply.
