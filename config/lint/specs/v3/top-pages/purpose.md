# Purpose: the five top pages

His answer on version 2: mostly yes, with two points. Version 3 makes `STATE.md` right for an agent and adds the page kinds that had no template. See `locations.md` and `STATE-grade.md`.

| Page | Reader | Comes with the question | Leaves for |
|---|---|---|---|
| `STATE.md` | An agent at the start of a session | What is open here, and what do I read first? | The three pages in `Read first`; then a view in `Ask the rows` |
| `index.md` | Person; an agent that looks for a place | Where is it? | The folder, or the page in capitals of that folder |
| `GLOSSARY.md` | Person; an agent that meets a word | What does this word mean here? | The folder or page the word names, by `Where` |
| `RESOLVER.md` | An agent before it changes a fact | Where does this fact live, and what changes it? | The table or file in `Lives in`; the rules in the system home |
| `README.md` | A new person who installed Foxrun | What is this, and where do I start? | `INSTALL.md`, then `GUIDE.md`, by `Start here` |

**In ten seconds each page must answer its one question from its first screen:** the title, one line, and the count block or facts table.

## The check against version 1

| Page | It answers its question | A gap the check found |
|---|---|---|
| `STATE.md` | Yes: counts, then open work by stream | `Functions` and `Program` are words of the model. Person knows them; a new person does not. |
| `index.md` | Yes: pages, folders, tree | A folder with no line in the system `RESOLVER.md` shows `(not on disk)`. The fix is in that page. |
| `GLOSSARY.md` | Yes: one table for each group | Groups come from a place rule until the glossary rows have a group. |
| `RESOLVER.md` | Yes: two tables and a lookup | The page lists rows; it does not say which command to type. `Changed by` names it only. |
| `README.md` | Yes: one screen | None. |

## The pages added in version 3

| Page | Reader | Comes with the question | Leaves for |
|---|---|---|---|
| `atlas/LIBRARY.md` | Person; an agent that looks for knowledge | Which wiki has pages on this, and under which topic? | The `TOPICS.md` of that wiki, at the topic |
| `TOPICS.md` | Person; an agent in one wiki | Which pages does this wiki have on this topic? | The page |
| `LOG.md` | Person; an agent that picks up old work | What happened here last? | The page of that day in `daily/` |
| `DASHBOARD.md` | Person, the operator | How does the business stand, by program, stream, and function? | A function page; `STATE.md` for the tasks |
| `RESOLVER.md`, system | An agent before it makes a file | Where does this kind of thing live, and who writes it? | That folder; the workspace `RESOLVER.md` |
| `SCHEMA.md` | An agent before a query | Which table holds this, and what is one row? | The table; `v_dictionary` for its fields |
| `CHANGELOG.md`, `INSTALL.md`, `GUIDE.md` | A new person who installed Foxrun | What changed; how do I install; what do I type each day? | The next page in `Next` |
| `CLAUDE.md` | Claude Code at the start | What do I read first? | `AGENTS.md` |

## The examples in this folder

| Example | Read from the disk at | Note |
|---|---|---|
| `example-STATE.md` | 2026-10-13 18:44 | Made again for version 3, in the new form. |
| `example-index.md` | 2026-10-13 18:20 | Made for version 2. |
| The nine new examples | 2026-10-13 18:47 | Made for version 3. |
| `example-RESOLVER.md` | 2026-10-13 17:12 | Not made again: `sample-shop/RESOLVER.md` was rewritten after 17:12 and has other headings now. |
| `example-GLOSSARY.md` | 2026-10-13 17:09 | Not made again: `sample-shop/CONCEPTS.md`, its source, left the build. |
| `example-GLOSSARY-system.md`, `example-README.md` | 2026-10-13 17:09 to 17:12 | Not made again: the system `GLOSSARY.md` is now built in this form, with 34 words. |
