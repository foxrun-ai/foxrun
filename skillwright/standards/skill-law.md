# Skill law

## The name rule

Name an action with a verb. Name a knowledge skill with a noun.
Use a family prefix only to stop a collision or group a family.
Use only the words the name needs.

| Words | Shape | Use |
| --- | --- | --- |
| 1 | `<verb>` or `<noun>` | One clear skill, such as `ship` or `pdf`. |
| 2 | `<family>-<verb>` | A family with one clear object, such as `treasury-close`. |
| 2 | `<object>-<verb>` | Several objects in one owned group, such as `context-save`. |
| 3 | `<family>-<object>-<verb>` | A family with several objects, such as `phone-text-send`. |

A knowledge skill uses `<noun>` or `<family>-<noun>`.
Use lowercase letters, digits, and single dashes only.
Start with a letter. Keep the whole name at 64 characters or fewer.
Do not use a word `and`, `my`, or a version word such as `v2`.

Test every new name:

1. Say it to a friend with no context. Can they guess what it does?
2. Sort it with its siblings. Does it sit by skills that touch the same thing?
3. Use one word in each slot. Remove `and`, `my`, and version words.
4. Use the same word for the same thing across the family.

The phone family has `phone-text-send`, `phone-screen-read`, and `phone-text-read`.
Put the object before the verb, as in `phone-text-send`.
A global skill takes one word with no family prefix, such as `handoff`, `log`, `close`, or `capture`.
Only a global skill takes a one-word name.
This law applies when a skill is created or changed.
Existing skills and kit skills are exempt until the shelf cleanup.
Do not rename a skill.
`skillify check` warns about a changed skill whose name breaks this rule. It does not refuse or rename.
`new`, `from-session`, and `promote` refuse a new name that breaks it, unless `--name-override` gives a reason.

## The skill kinds

Every skill has a kind. The kind tells the agent how to use the skill.

| Kind | What it is | `skillify new --kind` adds |
| --- | --- | --- |
| `knowledge` | A page the agent reads. It has no code. | `## Steps` with a done check on each step, then `## Gotchas`. |
| `tool` | A `bin/` script the agent runs. | A `bin/<name>` stub, `## Steps`, and `## Gotchas`. |
| `driving` | Browser or phone steps. | `## Steps` with a read-back step before any send, `## Gotchas`, and `## Stop`. |

`--kind` defaults to `knowledge`.
`skillify new` writes the kind in the `kind` frontmatter field, such as `kind: tool`.
A mixed skill lists each kind, such as `kind: tool, driving`, and meets the checks of each kind.
There is no fourth kind.
A script turns a knowledge skill into a tool skill, so `--with-bin` adds `tool` to the kind.

Put each check in the step it proves. A done check says what you see when the step worked.
Use `## Gotchas` for traps that sit outside the steps.
When a correction changes a step, fix that step. Do not add the correction to `## Gotchas`.

A `bin/` script follows the script rules:

- It never prompts. It reads flags and files only.
- It answers `--help`.
- It writes JSON to stdout and notes to stderr.
- It takes `--dry-run` on any write, and a dry run writes nothing.

A driving skill reads back the exact text before any send.
Its `## Stop` section says: close only the tabs or apps you opened, and never send without the approved gate.

## Replay cases

Every skill ships one to three replay cases in `replays/`.
A replay case is one recorded scenario: an input and the end state it must reach.
`skillify check` runs the cases, so a skill proves it still works before it ships.
Each case is one JSON file, `replays/<case-name>.json`.
We use JSON because Python reads it with no extra library, in every runtime.

```json example
{
  "name": "reserve-first-path",
  "run": "dry-run",
  "input": "bin/handoff-path {tmp}/ws replay-probe",
  "setup": {"dirs": ["ws"]},
  "expect": {"exit": 0, "output_contains": ["{tmp}/ws/history/handoffs/"], "files": ["ws/history/handoffs/*-001-replay-probe.md"]}
}
```

| Field | Need | What it holds |
| --- | --- | --- |
| `name` | Required | Lowercase words joined by dashes. Use it as the file name. |
| `run` | Required | `dry-run` for a tool, `rehearsal` for a driving skill, `read` for knowledge. |
| `input` | Required | A command line for `dry-run` and a scripted `rehearsal`. A question for `read`. A task for a rehearsal with no script. |
| `setup` | Optional | `dirs` and `files` to make in the temporary folder first. |
| `note` | Optional | Why the case has this shape, in one line. |
| `expect` | Required | The end state: `exit`, `output_contains`, `files`, and `sent_text`. |

- `exit` is the exit code. It defaults to 0.
- `output_contains` lists text that stdout or stderr must contain. For `read`, the answer must contain it.
- `files` lists globs that must match a file in the temporary folder.
- `sent_text` is the exact text that would have gone. A `rehearsal` case needs it.
- `{tmp}` stands for the temporary folder, and `{skill}` for the skill folder.

How `check` runs each case:

- It makes a fresh temporary folder and sets `HOME` and the working folder to it. Nothing reaches the vault.
- `dry-run`: the command starts with a script in the skill, such as `bin/<name>`, and carries `--dry-run`. A script with no `--dry-run` runs only inside the temporary folder, and `check` notes it.
- `rehearsal` with a script: the command must carry `--rehearsal`, or `check` does not run it. The script does every step up to the send, stops before the send, and prints JSON with `would_send.text`. That text must equal `sent_text`.
- `read`, and `rehearsal` with no script: `check` lists them. `check --replay-agent claude` runs each one in a fresh `claude -p` session on the judgment tier's Claude model (`config/models.yaml`), with no tools. The case passes when the answer contains the expected text.
- A case that fails refuses every skill, new or existing.

A new or changed skill with no replay case is refused. An existing skill only gets a warning until the shelf cleanup.
`skillify new` writes one example case for each kind. Replace it with a real scenario.
Judgment, such as draft quality, goes to Jev, not to a replay case.
The gate runs on Claude and Codex. Hermes is not part of it.

## Writing rules

- Explain why. A reason lets the agent act well in a case the step does not name.
- Say what to do, not only what to avoid.
- Cut each line that does not change what the agent does.
- Do not restate `--help` or a config file. Point to it.

## The checks in `skillify check`

1. Trigger opener: the first 57 characters of `description` name the object and the verb and end on a word.
2. Catalog budget: `description` is 1024 characters or fewer. `check` prints its length and the shelf total.
3. Body size: `SKILL.md` is 500 lines or fewer. References sit one level deep, each with a when-to-read line.
4. Dead links: each relative file that `SKILL.md` names is in the skill folder.
5. Gotchas: a knowledge, tool, or driving skill has `## Steps`, a done check on each step, and `## Gotchas`.
6. Script rules: each `bin/` script of a tool skill answers `--help`, never prompts, and takes `--dry-run` on writes.
7. Writing rules: no check. Follow the writing rules above.
8. Replay cases: a new or changed skill has one to three cases in `replays/`, and every case passes.

Check 4 skips example code blocks, placeholder paths such as `<name>` or `{name}`, and paths under run or output folders such as `runs/` or `outputs/`.
A missing or unknown `kind` skips checks 5 and 6.
Checks 2, 4, and 8 refuse a new or changed skill. A failed replay case refuses any skill. Every other finding warns.
Existing skills and kit skills only get warnings until the shelf cleanup.

## The file shape

`skillify new` makes a folder with `SKILL.md` and `replays/`.
It adds `bin/` for a tool skill or `--with-bin`, and `tests/` for `--with-tests`.
`skillify from-session` also sets `status: draft` until `check` passes.
`skillify promote` checks the name, then copies the source skill folder.

| File or folder | Need | What it holds |
| --- | --- | --- |
| `SKILL.md` | Required | `name`, `description`, and `kind` frontmatter, then the skill sections. |
| `bin/<name>` | Tool skills | A script stub that follows the script rules. |
| `replays/<case-name>.json` | Required | One to three replay cases. `new` writes one example case for each kind. |
| `tests/__init__.py`, `tests/test_<name>.py` | Optional | A test stub from `new --with-tests`. |
| `references/` | Optional | Reference files you add; `new` does not make this folder. |
| Other source files | Optional | Files copied with `promote`; `new` does not make them. |

## What "skillify" means

The Dojo `skillify` is the one door that makes a skill.
`new` makes a skill from a description or text.
`from-session` makes a draft from successful tool steps.
`promote` brings a Hermes skill into the Dojo.
`check` validates a skill before it moves on.
The old gstack and gbrain skillify copies retired in commit `d1a9eef`.
A skill made elsewhere meets this law when `promote` or `check` brings it into the Dojo.
After merge, `skill-ship` ships the checked skill.
