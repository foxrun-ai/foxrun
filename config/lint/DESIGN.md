---
type: doc
workspace: system
timestamp: 2026-10-14T20:30:00-04:00
---
# Lint Checks And Sources

`python3 -B base/lint.py --home <system> --workspaces <portfolio>` checks both homes.
`--rule ID` selects a rule. `--json` returns the same findings as JSON.
Exit 0 means no error findings. Exit 1 means findings. Exit 2 means invalid inputs or policy.
The `lint(path, blueprint)` database API and `--db` entry remain available.

## Rules

| Rule | Code kind | Policy or source |
|---|---|---|
| L01 | page_spec | `pages.tsv`, `specs/`, `parts.tsv` |
| L02 | allowed_top | `allowed-top.tsv` |
| L03 | empty_folder | `empty-ok.tsv`; an absent reason fails |
| L04 | blank_page, state_tracker | Page body and resolver-selected task scope |
| L05 | frontmatter | `frontmatter.tsv` and bound spec |
| L06 | database | `db.tsv`, `db-reasons.tsv` |
| L07 | required_pages | `required-pages.tsv` |
| L08 | page_spec, no_business_name | Tool, team, build-spec forms; named workspace list |
| L09 | tool_inventory | `tool-roots.tsv`, `tools.tsv`, `tool-exceptions.tsv` |
| L10 | object_route | `routes.tsv`; each route carries its source and quoted rule |
| L11 | lint_growth | `skillwright/skills/lint-rule/SKILL.md`, `base/lint_rule.py`, `rule-evidence.tsv` |
| L12 | lint_gates | `gates.tsv`; write, commit, release, and nightly entries |
| L13 | brand_page | `brand.tsv`, `brand.css`, `visual-reviews.tsv`, `base/lint_render.py` |

A new rule of an existing kind is one row in `rules.tsv`.
The lint-rule command proves a good fixture passes and a bad fixture fails before adding that row.
Its default run checks the candidate without changing policy. `--write` records the finding hash and task.
A new kind requires code and fixture changes together.

## Page Forms

The approved taste v2 and v3 forms remain copied under `specs/`.
`spec-changes.tsv` records the eleven existing form repairs and the retained build-spec binding.
The applied `specs/build-spec/spec.tsv` form and its section content checks remain unchanged.
Workspace `specs/**/*.md` pages bind to that form through `pages.tsv`.
Its `specs/AGENTS.md` and `specs/CLAUDE.md` binding exceptions remain unchanged.
The current `pages.tsv` binding and `specs/build-spec/spec.tsv` place and type these build specs.
The global front matter retains `type`, `workspace`, and `timestamp`.
The binding adds no business facts or invented makers' words.

## Tool Pages And Homes

L09 covers cli, mcp, service, plugin, external-app, and schedule categories in both homes.
It identifies page files and executable files or payload directories separately.
Runtime mappings cite source-page paths. Exact hosted-app and research-report exceptions state their reasons.
Unmapped pages and unpaged tools produce findings. Exact exceptions require reasons.
External runtime entries receive existence checks only. The checker never executes them.
L10 compares each managed page's type and relative path with the source-backed route table.
Each installed binding supplies an exact home and pattern; its bound spec supplies the literal type.
`source` and `quote` cite the binding. `type_source` and `type_quote` cite the type.
Binding exceptions remain in `except_patterns`. AGENTS homes use required-pages.tsv and the current SCHEMA type row.
The builder's route-gaps.tsv retains 33 unsupported older generalizations. They provide no fallback route.
Unknown types, missing types, and wrong homes fail. A person's judgment cannot silently add a route.
The accepted C0336 drawing repair supplies the exact bm-render system wiki exception and its real source type.

## Writes And Releases

`base/lint_gate.py --mode write --target <path> --body <draft>` checks prospective bytes on a copy.
The copy keeps the supplied home names and their relative layout, including cross-home links.
It copies the complete safe policy, overlays the draft, and loads that candidate policy for validation.
Candidate scopes, workspace names, exclusions, database routes, and tool metadata select the copy inputs.
Exact required-page targets also supply their bytes for the existing bound-form checks.
Their existing parent directories retain their presence, including when the required page is absent.
Candidate rule scopes, owner lists, and `except_workspaces` select those targets.
The gate loads candidate policy before inventory, so expanded scopes include existing files.
Invalid candidate rules or specs stop the write. Protected policy entries stay outside content reads.
It refuses protected paths, linked targets, writes outside both homes, and unclassified writes.
The Claude hook adapts Write and Edit events and refuses unclassified shell mutations.
Deny responses use the documented PreToolUse hookSpecificOutput permissionDecision schema.
Successful hook checks return silent exit 0. Other command modes keep their existing exit contracts.
Other runtimes use the same prewrite command under the shared AGENTS contract.
The commit hook invokes `--mode commit`. The skill publisher does not run this lint; a ship runs the skill's own checks.
Missing or failed gates stop those actions. Help and status remain available.
No runtime settings, loaded jobs, or Git configuration are changed by this proposal.
Loading hooks and the nightly schedule remains a separate installation action.

## Visual Checks

The brand sources are Foxrun Brand Guidelines and Foxrun Design QA Checklist in the source vault.
The heading rule comes from a ruling: every file carries the brand.
The renderer uses the sourced near-white, dark text, green signal, and font stacks offline.
It escapes raw HTML and executable links. Tables scroll within the page. Long words and commands wrap.
L13 checks capitalized headings, prohibited generic copy, table width, and command width.
Each human page also needs real visual review at 390 and 1440 pixels.
A review binds the exact page hash, renderer-plus-style hash, screenshot hash, reviewer, status, and zero overflow.
The prewrite copy includes exact safe images referenced for pages selected by candidate L13 rules.
Unrelated images and protected paths stay excluded. Missing or changed images still invalidate the review.
The review ledger starts empty. The lint reports missing reviews; it never invents visual approval.
Tests use labeled synthetic receipts. They do not claim live-page acceptance.

## Scan Boundary

Each rule has explicit include and exclude terms in `rules.tsv`.
Protected names stop content reads before any rule runs.
Ordinary page checks exclude history, archives, backups, installed skills, source payloads, and generated caches.
UPKEEP05 checks selected history/LOG.md pages and validates their bound LOG form.
The prewrite copy includes these exact required pages. Unrelated history files remain excluded.
The other upkeep checks cover tmp/scratch, raw type subfolders, retired contract names, and tracked Python caches.
L11 checks the specific lint-growth entry without scanning other installed skills.
L12 checks only its declared gate files.
No check repairs source data, sends messages, opens secrets, or uses the network.

## Tracker Routing

`db.tsv` records the system and nine workspace routes from their resolver evidence.
Eight workspace routes share the system file. The commerce tracker keeps its local file.
Shared task counts and STATE checks require the declared workspace filter.
An absent workspace column is a schema finding. It never falls back to another workspace's count.
No tracker rows or schemas change here.

## Product Lists

One central refresh job rewrites both product lists after all streams apply.
This proposal contains no product-list edits. `evidence/payload-hashes.tsv` in the builder packet supports that refresh.
