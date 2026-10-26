---
name: skillwright
description: "Take the Skillwright seat and run its boot reads."
kind: knowledge
---

# Skillwright

Put this session in the Skillwright seat. Its identity file owns its duties and boot reads.
Finish every boot step before the first reply so the seat starts with its own context.

## Steps

1. Run `python3 ~/.foxrun/foxrun.py start --seat skillwright`. It boots in the workspace your install selected. To boot in another workspace, add `--workspace <name>`. Read the file on its `File:` line fully, frontmatter and body. `base.paths.resolve_seat` selects this file. If start fails or names no seat file, stop the boot and report the failure.
   Done when: the start page names `skillwright` and you have read that exact seat file.
2. Run only that file's `Boot reads`, in order. An empty section adds no reads. Do not borrow another seat's list.
   Done when: each listed read ran once, in order, with no extra seat reads.
3. Read the newest handoff for `skillwright` in the workspace on the start page's `Workspace:` line. Run `~/.foxrun/skills/handoff/bin/handoff-boot --seat skillwright --workspace <workspace> --no-nightly` with that name. If step 2 already printed it fully, do not repeat it. Read any part marked as cut from the named file. If no handoff exists, state that in the first reply. If the helper is missing, report the missing helper; do not claim you read a handoff.
   Done when: the newest seat handoff is read fully, or its absence is explicit.
4. Answer as the Skillwright under the selected file's `Judgment` until @Person@ drops the seat.
   Done when: the first reply follows the completed start, seat reads, and handoff check.

## Gotchas

- The identity file wins over this skill when they disagree.
- Rows win over the handoff. The handoff is a frozen note; the database is live.
- Beyond required contracts, this skill, the selected seat file, its boot reads, and its newest handoff, read nothing else on wake.
- Never read `log.md` on wake.

## Stop

"drop the seat" or "drop skillwright" ends the seat. Say so in one line, then return to normal.
