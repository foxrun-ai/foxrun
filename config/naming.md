---
type: doc
workspace: system
timestamp: 2026-10-19T19:39:39-04:00
---
## Front matter

Each Markdown page in a workspace starts with front matter.
The workspace check reads these three keys on each page.

| Key | Form | Meaning |
|---|---|---|
| `type` | One lowercase word | The kind of page, for example `doc`, `index`, or `agents`. |
| `workspace` | The folder name, in kebab case | The workspace that owns the page. |
| `timestamp` | ISO 8601 date and time with an offset | When the page was made or last changed. |

Each of the three keys has one plain value, not a list.
Use one `timestamp`. Do not use `created` and `updated` pairs.
Do not use a date with no time, or a time with no offset.
`tags` is optional. Pick each tag from the approved words of the workspace.

## Names

- Use short kebab-case names for files and folders.
- Use capitals only for the top pages, for example `AGENTS.md` and `SCHEMA.md`.
- Name a dated file `YYYY-MM-DD-###-<slug>.md`. The `###` counts up that day.
- One word is better than two. Use three only when the source uses three.

## Records

- A current record is a row in `data.db`, not a table in a Markdown page.
- A report or a view reads rows. It owns no business state.
- Add a field when a record needs one. Do not rename a field.
