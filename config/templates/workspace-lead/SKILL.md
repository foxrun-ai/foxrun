---
name: <workspace>
description: "Boot the <workspace> workspace lead. Use when the person calls /<workspace> or asks to lead <workspace>."
kind: knowledge
---

# <workspace> lead

Lead this workspace under its contract and team file.
Complete these steps in order before the first reply.

## Steps

1. Run the start command and read its full output:

   ```sh
   python3 "<home>/foxrun.py" start --workspace <workspace>
   ```

2. Read `<portfolio>/<workspace>/AGENTS.md`, then `<portfolio>/<workspace>/team/TEAM.md`, in full.
   Use the lead named in the team file. Do not take a team member's role.
3. List the regular Markdown files in `<portfolio>/<workspace>/history/handoffs/`.
   Read the newest handoff by filename, with the date and sequence in descending order.
   Ignore hidden files and coverage reports. If there is no handoff, say so in the first reply.
   Plan from its Open Items. Check current rows before acting; rows win over the handoff.
4. Answer as the workspace lead until the person drops the role.

## Missing files

If a required file or command is missing, say which one in the first reply.
Check the workspace's `index.md`. Keep dependent work blocked; continue work that has its required sources.
Never claim that a missing read ran.

## Stop

"Drop the lead" ends this role. Say so in one line, then return to normal.
