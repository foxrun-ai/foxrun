---
type: doc
workspace: foxrun-dev
timestamp: 2026-10-22T11:48:23-04:00
status: draft
tags: [object-model]
---

# Wiki schema: {{workspace}}

The rules of this wiki. Read this page before you write a page here. Change a rule here; then change the pages.

## Domain

This wiki holds what the workspace `{{workspace}}` found and learned.
Our words are in the wiki. Their words are in `raw/` of the workspace.
A wiki page cites the raw file it comes from.

## Where things are

```
{{workspace}}/
├─ raw/                 the sources; one flat level of folders; beside the wiki
└─ wiki/                this wiki
   ├─ SCHEMA.md         this page
   ├─ TOPICS.md         the page at the top; a script builds it; nobody writes it
   ├─ concepts/
   ├─ entities/
   ├─ comparisons/
   └─ queries/
```

| Folder | What goes there | Writer |
|---|---|---|
| `concepts/` | How a thing works: a method, a rule, a guide. | Keeper |
| `entities/` | One page for one person, company, product, or account. It links each raw file about it. | Keeper |
| `comparisons/` | Two or more things side by side. | Keeper |
| `queries/` | The kept answer to one research question. | Keeper |

A page about a tool is not in the wiki. It is in `tools/<kind>/`.

## Raw sources

The sources are not in the wiki. They are in `{{workspace}}/raw/`, beside `wiki/`.

| Rule | Detail |
|---|---|
| Folders | One flat level, no folder inside a folder. |
| From the internet, by source | `x`, `youtube`, `instagram`, `reddit`, `github`, `articles` |
| Spoken words | `transcripts` |
| Files, by type | `documents`, `spreadsheets`, `decks`, `images`, `video` |
| What a system gave | `exports` |
| One writer | The Scout agent writes a raw file, its row, and its hash in one move. |
| No edit | Nobody edits a raw file. New evidence is a new file. |
| Hash | `sha256` of the body, below the front matter. The Keeper checks it each night. |

## Pages

| Rule | Detail |
|---|---|
| Sources | Each page names its sources. Each source is a file in `raw/` of this workspace or of Atlas. |
| The path of a source | A relative link from the page. From `wiki/concepts/` it starts with `../../raw/`. |
| When to make a page | The subject is in two sources or more, or it is the center of one source. |
| When not to | A passing mention. A thing outside the domain. |
| Length | Above 200 lines, split the page and link the parts. |
| Links | A page links the pages it depends on. Do not invent a link. |
| Two claims that disagree | Keep both, with their dates. Mark the page `contested: true`. |
| Weak support | Mark the page `confidence: low`. A page never approves a business action. |

A page with three sources or more ends each paragraph with the link of its source.

## Topics

| Rule | Detail |
|---|---|
| The list | Each wiki has one list of allowed topics, in two levels, about 30 in all. |
| Who makes it | A model proposes topics. The person blesses or strikes each one. Nobody types the list. |
| A new page | It gets one topic from the list, with a confidence. |
| A new topic | Only when no topic fits. It is marked proposed until the person blesses it. |
| No topic | The page shows in its own group in `TOPICS.md`, so a check finds it. |

## Atlas is flat

Atlas is the library. It is a wiki at its own top level: it has no `wiki/` folder.
`TOPICS.md`, `SCHEMA.md`, `concepts/`, `entities/`, `comparisons/`, `queries/`, and `raw/` are at the top of `atlas/`.
From `atlas/concepts/` the path of a source starts with `../raw/`.
A capture lands in Atlas when no workspace is named.

## What is not here

- Tasks, decisions, and measures are rows in the database.
- Handoffs, run reports, and outputs are in `history/`.
- Settings a script or a skill reads are in `config/`.
- The words of the setup and of the business are in `GLOSSARY.md`.
