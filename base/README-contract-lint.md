---
type: doc
workspace: system
timestamp: 2026-09-20T05:02:00-04:00
---

# Contract lint

`contract_lint.py` checks explicitly selected contracts without changing them.
It reports each finding with its file, line, rule, target, state, and evidence.
The recognized filenames and policies live in `contract-lint-rules.json`.
The legacy 80-line threshold is configurable. It does not define an approved screen size.

```sh
python3 ~/.foxrun/base/contract_lint.py \
  --rules ~/.foxrun/base/contract-lint-rules.json \
  --vault-root ~/foxrun \
  --workspace ~/foxrun/<workspace>
```

Use repeated `--path` arguments instead of `--workspace` for selected files.
Add `--recursive` to include nested contracts. `--all` scans every active contract below the supplied vault root.
Both scans skip hidden folders, history, drafts, protected paths, and symlinks.
The daily workspace check includes nested contracts when lint is enabled.
Archive paths, secret-like names, and symlink boundaries are refused.

## What the lint reports

The default prints one finding per line: file, line, rule, target, state, and evidence.
A finding is something wrong: a path that is not on disk, a command or a skill that does not exist, a stale name, a banned word, a broken policy.
Text the lint could not check is not a finding. It never changes the exit code.
The lint counts that text on the last line. Add `--unchecked` to list it.
Use `--json` for the full report: `findings`, `unchecked`, and every reference with its state. `--text` also selects the default output.

## How the lint reads a line

`LINT-GRAMMAR.md` is the exact list of forms the lint checks, each with a line it flags and a line it does not.
A miss inside that grammar is a defect. Text outside it is not checked.
The lint cuts each line into pieces and decides once what each piece is. No piece is read twice.
After the findings it prints one line for each file: `file: unchecked instructions: N`.
N counts the sentences that hold an instruction verb and match no form of the grammar. The count never fails the lint.

- **Paths.** In backticks or in plain text. A path starts with `~/`, `./`, `../`, or `/`, or has a folder before the name, or ends with a slash or a known file ending. Dots inside a name are part of the name.
- **Plain names.** A plain word with no folder, such as SKILL.md or docs/, is a name, not a path. Right after `Read` or `Open`, a plain file name is a file pointer and is checked. Plain words joined by a slash, such as and/or, are prose. Write a path in backticks.
- **Placeholders.** Text in angle brackets, such as `<workspace>/AGENTS.md`, is a placeholder. It is not checked. Use angle brackets for a file that is not on disk yet.
- **Commands.** Inline code is a command when it starts with `$ `, or when a flag, a placeholder, a quoted value, or a script path follows a lowercase first word. Inline code right after the word `Run` is always a command. The whole first word is the command: `python3.99` is not `python3`. A list of plain words in backticks is not a command.
- **Run lines.** A plain line that starts with Run names a command when a flag or a script path follows the name, or when the name ends the sentence and holds a digit, dot, hyphen, underscore, or plus. `Run the daily check.` is prose.
- **Skill names.** `$name` and `/name`, in backticks or plain. A slash inside a path is never a skill. `/tmp` and other system folders are paths.
- **Code fences.** Lines in `sh`, `bash`, `zsh`, and `shell` fences are checked as commands. Every other fence is inert.
- **Banned words.** Whole words, any letter case, on every line outside a code fence. Quotation marks do not hide a banned word. One exception: in double quotes after `Never say` or another prohibition cue of the rule file, the line bans the word.

Two rules cover paths that are absent on purpose. Both live in the rule file.

- A path in backticks that is missing under the heading `What Is Not Built Yet` or `File homes` may be absent: the first names what is not built, the second names the homes of new files. The lint lists it as not checked. A link, an import, a script, or a plain path under those headings is checked as anywhere else. Outside those sections the same path is checked again.
- Paths in backticks listed right after `Do not create` or `Never create` must stay absent. One that is on disk is a finding.

A bare file name in backticks resolves beside the contract, at the workspace root, or at the Portfolio root.
In the Portfolio contract it also resolves at the root of any workspace folder.
A target in a protected folder, outside the declared roots, or with a glob is not checked.
The checker never executes document text.
Active Markdown under `docs/specs/` receives approval coverage and frontmatter checks.
With an approval source, a contract with no exact approval binding is a finding. Without one, approval is not checked.
Drafts, `.new` documents, and history stay outside discovery.
`fleet` comes from its stale-reference note. The guide forbids `strategy-pack` framing.
A contract names a workspace by its current folder name, never by a retired name.
The machine contract forbids the two listed praise phrases.
Existing size and tool policies remain unchanged. This command adds no approval gate.

## Lint a file where it will live

A template or a draft holds paths written for the place it installs to.
`--as` lints one `--path` file as if it sat at that place. The file may have any name and may sit outside the vault.

```sh
python3 ~/.foxrun/base/contract_lint.py \
  --rules ~/.foxrun/base/contract-lint-rules.json \
  --vault-root ~/foxrun \
  --path /absolute/path/draft-agents.md \
  --as cedar-shop/AGENTS.md
```

The runtime global files sit in protected folders, so a direct `--path` is refused.
`--as` lints each one in place, as the global contract it points to:

```sh
python3 ~/.foxrun/base/contract_lint.py --rules ~/.foxrun/base/contract-lint-rules.json \
  --vault-root ~/.foxrun --path ~/.codex/AGENTS.md --as profile/AGENTS.md
python3 ~/.foxrun/base/contract_lint.py --rules ~/.foxrun/base/contract-lint-rules.json \
  --vault-root ~/.foxrun --path ~/.claude/CLAUDE.md --as CLAUDE.md
```

## Judgment pass

Three checks need judgment: a contradiction, a filler sentence, a label that is not an approved word and is not explained.
They run only with `--judgment`. The flag is off by default. No exact check calls a model.
With the flag, the lint writes one request per section, runs the Jev runner once, and reports each yes with file and line.

```sh
python3 ~/.foxrun/base/contract_lint.py \
  --rules ~/.foxrun/base/contract-lint-rules.json \
  --vault-root /absolute/path/vault --workspace /absolute/path/vault/workspace \
  --judgment --judgment-command "node /absolute/path/jev/scripts/jev.mjs" \
  --judgment-dir /absolute/path/outside/the/vault \
  --judgment-words /absolute/path/vault/workspace/GLOSSARY.md \
  --judgment-database /absolute/path/data.db
```

`--judgment-dir` must exist, sit outside the vault, and hold no earlier request. Nothing is overwritten.
`--judgment-words` names each file of approved words: its bold terms and its headings are the word list.
`tests/contract_judgment_stub.py` stands in for the runner in tests. It calls no model.

## Roots, commands, and fences

`--skill-root` declares each permitted skill shelf. Symlinked skills remain uncheckable.
`--command-inventory` accepts `{"executables":["python3","rg"]}`; otherwise executable names use PATH.
Commands are never executed. Unsupported syntax remains visible as uncheckable.
Literal command script arguments receive separate path checks.
Shell fences labeled `sh`, `bash`, `zsh`, or `shell` support inert, single-line literal command and script-path checks.
Any dollar-sign form, control syntax, operators, continuations, heredocs, and malformed shell lines remain uncheckable.
Only direct executable paths and the first literal script argument to a supported interpreter or source command become path requirements.
Arguments to `echo` and `printf` remain prose. Interpreter option forms such as `python3 -c` remain uncheckable.
The `source` and `.` builtins remain availability-uncheckable, while their literal script path is checked.
Other fenced languages and arbitrary bare inline names remain uncheckable.
One-line Markdown reference definitions support full, collapsed, and defined shortcut links.
Duplicate definitions and explicit unresolved full or collapsed references remain uncheckable.
Undefined shortcut syntax cannot be separated safely from ordinary bracketed prose, so it is ignored.
External URLs and same-document anchors from reference definitions are outside local pointer checks.
The report includes the parser limits. A clean subset does not prove complete contract coverage.

Approval evidence is optional and read-only. Its JSON shape is:

```json
{"approvals":[{"file":"workspace/AGENTS.md","sha256":"<64 lowercase hexadecimal characters>","approval":"<existing approval reference>"}]}
```

The caller must supply verified canonical approval evidence.
The checker matches the exact file and bytes; it cannot authenticate an approval or create one.
Without an approval source, coverage is not checked. With one, a contract with no exact binding is a finding.
An arbitrary approval marker does not grant approval.

`--output` saves a private report outside the vault. The parent directory must already exist.
Existing reports are preserved with one `.new` alternative; a second conflict fails.
Exit codes: `0` means no findings, `1` means findings, and `2` means a failed scan.

## Existing checker integration

The base checker accepts `--contract-lint-rules` and `--contract-lint-vault-root`.
The daily checker accepts `--contract-lint-rules` alongside its existing `--vault` argument.
Both accept prefixed skill-root, command-inventory, and approval-source options.
The daily check selects this rule file by default. Its normal invocation includes lint.
No live schedule changes belong to this package.
The daily checker adds lint findings after continuity reconciliation.
`schema_contract.py` retains its existing authority. Notification remains explicitly opt-in.

```sh
python3 -m unittest discover -s base/tests -t base -p "test_contract_*.py" -v
```

`test_contract_lint_table.py` is the table: each row is one line of contract text with its exact expected result.

Run it from the root of your Foxrun source checkout, the folder that holds `install.py`.
Daily-check tests also require two pinned packages: `python3 -m pip install PyYAML==6.0.3 pytest==9.0.2`.
The exact checks are complete without a model. The judgment pass and scheduled activation need their own yes.
