---
name: data-store-pick
description: "Pick where a piece of data should live and in what format: a Foxrun home first, then Markdown, YAML or TOML, JSON, JSONL, TSV, CSV, txt, code, SQLite, a hosted table, object storage, a secret store, or git. Use when someone asks where should this live, what format, what store, or is about to make a tracker, record set, config, log, export, or dataset."
kind: knowledge
---

# Data Store Pick

Answer one question: where does this data live? One pick, one-line reason. No essays.

## Steps

1. Check the Foxrun homes first. Read the `Where Things Go` table in `~/.foxrun/profile/AGENTS.md`, then the workspace `RESOLVER.md`. Run `python3 ~/.foxrun/foxrun.py where <path>` for a path.
   Done when: a Foxrun home fits, or you can say none does. If one fits, that is the answer.
2. Infer the four facts from context. Ask only what you cannot infer, one question at a time:
   1. What is it? Narrative, keyed records, config, event log, raw dump, tabular hand-off, media, secret, or code.
   2. Who updates it? A human, agents, or both.
   3. How often? Rarely or all the time.
   4. Who must reach it? This machine only, everywhere, or another person.
   Done when: all four have an answer.
3. Pick from the rules table. The tiebreaker: who must reach the data decides where it lives, not the shape of the data.
   Done when: one row matches.
4. Answer in one block:

   > **Store: SQLite** - keyed records, agent-written, local only.

   Add a second candidate only when the answer depends on a choice the person has not made. Then ask that one question.
   Done when: the block names one store and its reason.

## The rules

| It is... | It lives in... |
|---|---|
| Tracked work, people, rulings, approvals, lessons | A row in `~/.foxrun/data.db` through `work.py`, never hand SQL |
| A business's own records (orders, payments) | The tables named in the workspace `RESOLVER.md` |
| Narrative a human reads (policy, plan, write-up) | Markdown, in its workspace home |
| Keyed records agents update (tracker, register, inventory) | SQLite if this machine only; a hosted table (such as Postgres) if it must be reached from everywhere or shared |
| Human-edited settings | YAML, frontmatter, or TOML |
| A small keyed list kept in git that a human and an agent both edit (word lists, rule lists) | TSV |
| Data exchanged between systems | JSON |
| Things that happened, append-only (receipts, run logs) | JSONL or an append-only log; never edited, never in a page |
| A raw dump kept as is (transcript, export, scraped text) | `.txt`; if a human will read it, `.md` |
| Tabular data handed to a human or a spreadsheet | CSV; a hand-off format, never the system of record |
| Behavior, checks, automation | Code (`.py`, `.mjs`) in the owner's `scripts/` or `bin/` |
| Images, video, exports, big files | Object storage or a drive |
| Credentials and tokens | The secret store, read through `agent-secret-read`; never a file, never printed |
| Generated output you can rebuild | Outside git, or ignored by git; git holds intended versions only |

## Gotchas

- A Foxrun home in the contract beats this table. Say so when they differ.
- Never pick `.env` files for secrets. The secret store exists to stop them.
- Parquet is too heavy at this scale. Design and canvas files are media: object storage.
- CSV hands data to a person. It is never the record.
