---
type: doc
workspace: system
timestamp: 2026-10-22T13:10:21-04:00
---

# Gates

The actions that wait for the person's yes.
Read this page before one of them.
A workspace `AGENTS.md` can add gates. It never removes one.
A direct word from the person wins over this page.

## Ask first

Show the person the exact thing. Wait for the yes. Then act.

| Action | Show the person |
|---|---|
| Money: a payment, a transfer, a purchase, a budget change | The amount, the account, the payee |
| A send in the person's name: a message, an email, a post, an invite | The exact words, the fact lines, the recipient, the account, the thread |
| A change on an outside platform: a listing, a catalog item, an order, a setting, a new repository | The exact change |
| A deploy | The commit and the target |

Before a launchd or keychain action, read the `incidents` table in `data.db`.

## Workspace gates

Each workspace names its own gates in its `AGENTS.md`, section `When To Ask Here`.

## What a yes covers

- One action, in the exact version the person saw.
- A changed version needs a new yes.
- On a message, the yes covers the words and the fact lines shown with them.
- An edit from the person is not a yes. Show the new version and wait.
- A direct, specific ask from the person is the yes. A send still shows the exact text first.
- A yes for money or a send counts only in the session where the person gave it.
- The lead writes the yes as a row, in the person's words, the same turn: `work.py approval-add`.
- A click on a page is one approval row for that version. Money and sends still need a yes in chat.
- "Stop" and "let me think" are holds. Start nothing until the person says so.

## Deletes

Do not ask about a delete.
Back the thing up, check the backup, then delete.
A delete that no backup holds does not happen.
A file under git is backed up by git.

## No yes needed

- Edits, commits, and pushes to a branch of the person's own private repositories.
- A merge: its tests pass and a second agent, not the author, read the change. The lead merges.
- A change to a runtime config file, with a backup and an exact undo.
- A Hermes gateway action: a start, stop, restart, or reload. It needs a named plan first and a receipt after.
- A write in another agent's part: it raises an alarm. The lead clears it with a logged reason.

## Hermes gateway plan

Write this plan before a Hermes gateway action. Fill in every line.

```
Plan: <plan name>
Gateway: <profile or gateway name>
Action: <start, stop, restart, or reload>
Files: <each file the action reads or changes>
Commands: <each exact command, in order>
Check before: <the command and the result you expect>
Check after: <the command and the result you expect>
Rollback: <the exact commands that put the old state back>
Receipt: <the receipt path; write it with the `log` skill after the action>
```

## Hard blocks

A hard block is only for security and for what git cannot undo.
Secrets: never print one. Never commit one.
Secret files, auth files, and `.env` files stay closed.
Everything git can undo gets an alarm, not a wall.

Your own gates: `config/gates.local.md`.
