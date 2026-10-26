---
type: doc
workspace: system
timestamp: 2026-10-19T20:36:00-04:00
---
# Workspace Pages

The Keeper builds these pages from explicit source paths. Database connections stay read-only.
Use the report date for repeatable checks. Run checks on a copy before application.

`page_indexes.py --portfolio DIR --system-home DIR --as-of DATE --kind all`
builds workspace indexes, the portfolio index, permitted wiki topic indexes, and the portfolio library.
Each index.md fills the slots of `templates/index.md`, the one shape of the page.
Add `--check` to detect changed pages and pages of another shape, without writes.
Atlas gets index.md like every workspace. A move-only workspace keeps its exception: it gets index.md, and its wiki is never read or written. The person names it in `config/person.json` as `"workspace_settings": {"<id>": {"move_only": true}}`.
Wiki catalogs contain existing topic words marked proposed. Untopiced pages remain counted.

`workspace_pages.py NAME --system-home DIR --workspace-root DIR --as-of DATE`
builds team/TEAM.md and tools/CAPABILITIES.md from seat, skill, and tool declarations.
Add `--check` to flag hand edits outside TEAM Notes.

`make_workspaces_view.py --system-home DIR --workspace-root DIR --as-of DATE`
builds the three reviewed view pages for every workspace. Add `--check` for comparison.

`workspace_reports.py --workspace DIR --db ~/.foxrun/data.db --as-of DATE`
builds ops/DASHBOARD.md, goals.md, programs.md, streams.md, tasks.md,
measures.md, decisions.md, issues.md, and ops/functions/<group>/<function>.md.
It also builds history/LOG.md and history/daily/<date>.md.
Add `--check` to compare the pages without writes.

There is one database, `data.db` in the system home. A workspace never gets its own.
`workspace_reports.py` reads only the rows whose `workspace` tag names the workspace you give.
Explicit workspace tags on project rows exclude another workspace's project and events.
Event mapping preserves source IDs, subjects, actors, fields, old/new values, and original dates.
Daily grouping uses the source calendar date. Blank action words remain action unknown.
LOG.md shows event labels; full note text stays in the database and daily pages.

Past days freeze in history/daily/frozen.json after their first build.
The manifest stores the event fingerprint and page hash for each frozen day.
A changed frozen page or changed frozen source rows stops the builder before any writes.
Late historic rows need a separate reviewed correction. The builder never rewrites a frozen day silently.
Existing daily pages replaced by this proposal remain in the applier's before/ receipt.

Each capital rollup starts with a built marker. Lint recognizes the metadata after that marker.
These commands build pages. They do not install a clock or prove runtime access to a tool.
