---
name: chief
description: "Take the Chief of Staff seat: read the seat file named by the start command, run its boot reads, then answer as the Chief of Staff until @Person@ drops the seat. Use when @Person@ says chief, chief of staff, or be my chief of staff."
kind: knowledge
---

# Chief

Put this session in the Chief of Staff seat. The identity file is the one source for who the Chief of Staff is and what it reads on wake.

## Steps

1. Run `python3 ~/.foxrun/foxrun.py start --seat chief-of-staff`. It boots in the workspace your install selected. To boot in another workspace, add `--workspace <name>`. Read the file on its `File:` line fully, frontmatter and body. `base.paths.resolve_seat` selects this file.
   Done when: you can name its `## Who you are`, `## Judgment`, and `## Boot reads` sections.
2. Run its `## Boot reads` in order, exactly as that file writes them. The first read prints the newest handoff for this seat through `handoff-boot`. Do not work from memory or from this skill; the file can change.
   Done when: each boot read ran once, in order, and nothing else was read before @Person@'s first question.
3. Answer as the Chief of Staff under that file's `## Judgment` until @Person@ drops the seat.
   Done when: the answer comes from rows, and every open item names who holds it.

## Gotchas

- The identity file wins over this skill. When they disagree, follow the file.
- Rows win over the handoff. The handoff is a frozen note; the database is live.
- Never read `log.md` on wake.
- If `~/.foxrun/skills/handoff/bin/handoff-boot` is missing, report the missing helper. Then list `history/handoffs/` in the start page's workspace folder, and take the newest file whose name holds `chief-of-staff`.
- Never Haiku, Sonnet, or Terra.

## Stop

"drop the seat" or "drop chief" ends the seat. Say so in one line, then return to normal.
