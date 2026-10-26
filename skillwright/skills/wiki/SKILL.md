---
type: note
workspace: system
timestamp: 2026-10-26T14:20:00-04:00
name: wiki
description: "Add, refresh, or check a workspace wiki page: the memory step for what a thing is. Concepts, entities, and kept answers live in <ws>/wiki/. Use for /wiki add, /wiki refresh, /wiki check, or when someone asks what a thing is and the answer is worth keeping."
kind: knowledge
argument-hint: "add | refresh | check [page or topic]"
---

# wiki

The wiki answers what a thing is or how it works. It is the Semantic step of the memory ladder.
Each workspace keeps its own wiki in `~/foxrun/<ws>/wiki/`. The library `~/foxrun/atlas/` holds anything wider.
A wiki page explains. It never holds state: a number, a status, or what is next lives in tracker rows.

| You have | Folder |
|---|---|
| A page about a topic | `wiki/concepts/` |
| A page about one named thing | `wiki/entities/` |
| An answer worth keeping | `wiki/queries/` |

## Steps

1. **Add.** Search first: `rg -il "<words>" ~/foxrun/<ws>/wiki/`. If a page covers it, refresh that page instead. Otherwise, draft a new page with a kebab-case name and this frontmatter: `type` (`concept`, `entity`, or `query`), `workspace`, `timestamp`, `status`, `tags`. Link each source; never copy a raw capture. Run `python3 ~/.foxrun/base/lint_gate.py --mode write --target <page path> --body <draft file>`, then write. Done when the gate passed and the page is in its folder.
2. **Refresh.** Read the page and each source it links. Change only the lines the sources no longer support. Update `timestamp`. Add a short dated line to its `## Updates` section if it has one. Run the lint gate on the changed page. Done when every claim on the page has a live source.
3. **Check.** Run `python3 ~/.foxrun/base/check_workspace.py ~/foxrun/<ws>` and read the findings under `wiki/`. For each finding, fix the page, or say why it stays. Done when the wiki has no finding you did not name.
4. **Report.** Give the path of each page you added or changed, and one line on what changed. Done when the person has the paths.

## Gotchas

- `wiki/TOPICS.md` is built from the topic catalog. Do not edit it by hand.
- Run `python3 ~/.foxrun/foxrun.py glossary <term>` before you name or tag a page, so the words match the glossary.
- A page that only one task needs is a note, not a wiki page.
