---
type: doc
workspace: system
timestamp: 2026-10-05T07:10:00-04:00
tags: [contracts]
---

# Contract lint grammar

`contract_lint.py` checks the forms on this page and nothing else. A miss inside a form is a defect. Text outside every form is not checked.
Each form has one piece of text the lint flags (`+`) and one piece close to it that the lint does not flag (`-`).
`test_contract_lint_grammar.py` holds the same forms as data and generates the cases: each piece alone on a line, at the start of a sentence, in mid-sentence, in a list item, in a block quote, in a table cell, and after every instruction verb of the rule file.
The lint must flag the `+` piece in every place the form names and nothing else. A test fails when this page and that data differ.

The fixture behind the examples: `docs/ok.md`, `docs/tool.py`, `ok.md`, `tool.py`, and `built/` are on disk. `python3` and `rg` are commands. `fixture-skill` is on the skill shelf. Nothing named missing exists.

## Line forms

### G1 A path in backticks

Inline code that is one unbroken piece and starts with `~/`, `./`, `../`, or `/`, or ends with a slash, or ends with a known file ending. Dots inside a name are part of the name. Inline code with a slash and none of these signals counts only when it is on disk.

```text
Where: any place on a line outside a code fence
+ `docs/missing.md`
- `true/false`
```

### G2 A plain path with a folder

A plain word that has a folder before the name and a known file ending, or that starts with `./` or `../`, or that has two parts or more and a trailing slash.

```text
Where: any place on a line outside a code fence
+ docs/missing.md
- and/or
```

### G3 A plain file name right after Read or Open

The plain word right after `Read` or `Open`, any letter case, when it is a file name with a known file ending.

```text
Where: any place on a line outside a code fence
+ Read missing.md
- the missing.md file
also + Read: missing.md
also + Read : missing.md
also + **Read** missing.md
also + Read **missing.md**
also + Read *missing.md*
also + read missing.md
also + Open missing.md
also + open missing.md
```

### G4 A Markdown link or reference

`[text](target)`, `[text][label]`, and `[label]` with a one-line definition. The target is checked. A web address is not. An image and a link inside inline code are inert.

```text
Where: any place on a line outside a code fence
+ [gone](docs/missing.md)
- ![alt](docs/missing.png)
```

### G5 A wikilink

`[[folder/note]]` and `![[folder/note]]`. A note with the same name wins over a folder. A wikilink with no folder is not checked.

```text
Where: any place on a line outside a code fence
+ [[docs/missing]]
- [[Missing Note]]
```

### G6 A Claude import

A plain word that is `@` and a path: a whole line, or a word in a sentence.

```text
Where: any place on a line outside a code fence
+ @docs/missing.md
- person@example.com
```

### G7 A command in backticks

Inline code that starts with `$ `, or where a flag, a placeholder, a quoted value, or a script path follows a lowercase first word. The whole first word is the command, dots included. A script path after it is checked too.

Right after `Run` the `-` piece is flagged: there it is a command (G8 or G9).

```text
Where: any place on a line outside a code fence
+ `$ absent --version`
- `agents home index log`
```

### G8 A command in backticks right after Run

Inline code right after the word `Run`, any letter case. The first word is the command, even with plain subcommands. A path there is checked as a script.

```text
Where: any place on a line outside a code fence
+ Run `fixture-missing-command status`
- try `fixture-missing-command status`
also + Run **`fixture-missing-command status`**
also + Run *`fixture-missing-command status`*
also + Run: `fixture-missing-command status`
also + Run : `fixture-missing-command status`
also + **Run** `fixture-missing-command status`
also + run `fixture-missing-command status`
also + RUN `fixture-missing-command status`
```

### G9 A plain Run phrase at the start of a line

`Run name` as the first words of a line, after a list or quote marker if there is one. The name is a command when it holds a digit, dot, hyphen, underscore, or plus, or is an interpreter name (`bash`, `node`, `perl`, `python`, `python3`, `ruby`, `sh`, `zsh`), and a flag or a script path follows it or it ends the sentence.

```text
Where: only alone on a line, at the start of a line, in a list item, in a block quote
+ Run python3.99 tool.py
- Run the daily check
```

### G10 A line in a shell fence

A whole line inside a fence labeled `sh`, `bash`, `zsh`, or `shell`. The first word is the command. Every other fence is inert.

```text
Where: a whole line inside a shell fence
+ missing-fence-command --now
- python3 docs/tool.py
```

### G11 A skill name with its prefix

`$name` or `/name`, in backticks or plain. A slash inside a path is never a skill. `/tmp` and other system folders are paths.

```text
Where: any place on a line outside a code fence
+ /missing-skill
- $5
```

### G12 A stale name

A name from `stale_names` in the rule file, written as `$name`, `/name`, or alone in backticks.

Right after `Run` the `-` piece is flagged: there it is a command (G8 or G9).

```text
Where: any place on a line outside a code fence
+ $fx-log
- fx-log
```

### G13 A banned word

A word from `banned_words`, as a whole word, any letter case. Quotation marks do not hide it. One exception: inside double quotes after a phrase from `banned_word_prohibition_cues` on the same line, the line bans the word.

```text
Where: any place on a line outside a code fence
+ fleet
- Never say "fleet"
```

### G14 A reference under a declared-absent heading

Under a heading from `declared_absent_headings`, a missing path in backticks may be absent and is listed as not checked. Every link, import, script, and plain path there is checked as anywhere else. The rule holds for that section only.

The examples stand under the heading `File homes`.

Right after `Run` the `-` piece is flagged: there it is a command (G8 or G9).

```text
Where: any place on a line outside a code fence
+ [routing rules](docs/missing.md)
- `docs/adr/`
```

### G15 A path that must stay absent

Paths in backticks listed right after a phrase from `absent_path_cues`. One that is on disk is a finding.

```text
Where: any place on a line outside a code fence
+ Do not create `built/`
- Do not create `plans/`
```

## Words the forms use

- **Known file ending, plain text:** `md`, `py`, `sh`, `sql`, `json`, `jsonl`, `toml`, `yaml`, `yml`, `sqlite`.
- **Known file ending, in backticks:** the same, and `txt`, `csv`, `html`, `css`, `db`, `plist`, `png`, `jpg`, `svg`, `pdf`. With a folder before the name also `js`, `mjs`, `ts`, `rb`, `pl`.
- **Right after:** the cue word is the plain word directly before, with nothing between them but colons and emphasis marks (`*`, `_`), with or without spaces. A code span or any other word between them ends it: in ``Run the `x` command`` the code is not right after Run.
- **Finding:** something wrong. It fails the lint. **Not checked:** it never fails the lint; `--unchecked` lists it.
- **Command exists:** it is in the command inventory when one is given, else on PATH. **Skill exists:** `name/SKILL.md` is on a declared skill shelf.

## File rules

These apply to a whole file. `test_contract_lint.py` and the check `policy` hold their cases.

| Rule | Flagged | Not flagged |
|---|---|---|
| No status in frontmatter | `status: draft` in the frontmatter of `AGENTS.md` | `type: agents` |
| Size | `AGENTS.md` with 81 lines | `AGENTS.md` with 80 lines |
| No tool list | `soul.md` with a `## Tools` list | `CAPABILITIES.md` with a `## Tools` list |
| Required contract | a workspace with no `AGENTS.md` | a workspace with no `soul.md` |
| Approval, when an approval source is given | a contract with no exact approval binding | a contract with its binding |

## Where a path is looked for

- A path that starts with `./` or `../`: from the folder of the contract.
- Any other path: beside the contract, then at the workspace root, then at the Portfolio root.
- A bare file name in the Portfolio contract: also at the root of any workspace folder.
- A path with a trailing slash must be a folder.

## Unchecked instructions

The lint prints one line for each file: `file: unchecked instructions: N`.
An instruction sentence is a sentence of a line outside code fences, frontmatter, and reference definitions that holds a word of `instruction_verbs` (rule file) as a plain word outside backticks and outside link text; a sentence ends at a period, exclamation mark, or question mark that is followed by a space and is outside backticks, or at the end of the line.
N counts the instruction sentences from which the lint pulls no reference (G1 to G12, G14, G15) and in which it finds no banned word (G13).
A reference counts even when its target cannot be checked. The count never fails the lint. `--unchecked` lists each sentence with its line.

## Outside the grammar, not checked

- A command in plain words with no backticks, such as `Run git status.` Only G9 reads a plain Run phrase.
- A plain Run phrase that is not the first words of a line: in mid-sentence, in a table cell, or after another word.
- A plain Run phrase whose name is a plain word, such as `Run make --jobs 2` or `Run the tool.py file`.
- A command in backticks with only plain words, such as `git status`, unless it stands right after Run (G8).
- A plain file name with no folder, such as SKILL.md, unless it stands right after Read or Open (G3).
- Plain words joined by a slash, such as and/or, and a plain folder name of one part, such as docs/.
- A bare name in backticks, such as `herdr` or `log`: it may be a skill, a command, a table, or a field.
- Text in angle brackets, such as `<workspace>/AGENTS.md`: a placeholder.
- A path outside the declared roots, such as `~/.foxrun/agents`, and a path in a protected folder, such as `archive/`.
- A path with a glob, such as `docs/*.md`.
- A wikilink with no folder, such as `[[Note]]`.
- Shell syntax that is not one literal command: pipes, redirects, `$(...)`, control words, builtins.
- A banned word inside a code fence.
- A web address, an image, and any fence that is not a shell fence.
- Meaning: a contradiction, a filler sentence, an unexplained label. Those belong to the judgment pass (`--judgment`).
