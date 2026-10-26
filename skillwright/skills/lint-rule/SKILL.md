---
name: lint-rule
description: "Add a lint rule, or repair a page template, after a real finding shows a gap. Use existing check kinds first."
---
# Grow The Lint

Keep the finding, its source, and its task ID before changing policy.
Use the system home's `config/lint/` and `base/lint.py`.
Read `config/lint/DESIGN.md` for source boundaries and the available kinds.

For an existing kind, add one `rules.tsv` row through `base/lint_rule.py`.
Supply `--id`, `--words`, `--kind`, `--scope`, `--task`, and `--evidence`.
Supply small labeled good and bad fixture homes with `--good-home`, `--good-workspaces`, `--bad-home`, and `--bad-workspaces`.
The command refuses a failing good fixture and a passing bad fixture.
Run without `--write` first. Inspect the result, then use `--write` within the authorized policy checkout.
The evidence ledger retains the finding hash, task, and both fixture results.

For a template repair, preserve its real source in `spec-changes.tsv`.
Change the bound `specs/` file and its good and bad fixtures together.
For a new kind, change code and tests together. Do not disguise missing code as a new data row.
Run `python3 -B -m unittest discover -s base/tests`.
Run `base/lint_gate.py --mode release` before release.
Publish through the existing skill release process; this skill grants no new runtime or send permission.
No product-list edit belongs to this job. The central refresh job records final product hashes.
