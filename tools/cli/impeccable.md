---
type: "tool"
workspace: "system"
timestamp: "2026-10-23T12:31:53-04:00"
name: "impeccable"
what: "design guidance for AI coding agents"
kind: "cli"
use: "creator & content"
status: "chosen"
command: "impeccable"
---
# impeccable

impeccable is "design guidance for AI coding agents" (its makers' words). In plain words: it gives your agents design commands and a checker that finds common design faults on a page.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents run `detect` on templates and built pages before a design review.
- Agents read `audit` and `critique` output as a second view; your own design rules win.
- A `document` draft goes to a work folder; it never replaces your own `DESIGN.md`.
- Foxrun rules win over the agent lines that the engine prints. Workers never start workers.

**Install:** [impeccable](https://github.com/pbakaus/impeccable) · `git clone -b skill-v4.7.0 https://github.com/pbakaus/impeccable`

| Field | Value |
|---|---|
| Use | creator & content · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ☑️ chosen · skill 4.7.0, engine 0.1.16 · Foxrun does not install it; you install it |
| Where | Not on disk until you install it. The skill goes in `~/.agents/skills/impeccable`; the engine goes in `~/.impeccable/bin/`. |
| His yes | Installing it needs your yes. An update needs a new vet. Turning on its edit hook (`hooks on`) needs your yes. |
| Source | The tool: its README and `SKILL.md` at tag `skill-v4.7.0`, and `impeccable --help`. Foxrun's use: a design review. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | recommended · it reviews and audits design work, and writes a design system file. |

## Install

The skill is Apache-2.0. Add it through your own skill release, never by hand on the shelf.

| Step | Command | It prints |
|---|---|---|
| Install | `git clone -b skill-v4.7.0 https://github.com/pbakaus/impeccable` | — |
| Add it to your skills | `cp -R impeccable/.agents/skills/impeccable <your skill source>/skills/` | — |
| Release it | a commit on `main` in your skill source | the skill in `~/.agents/skills` |
| Check | `~/.agents/skills/impeccable/scripts/impeccable --version` | `4.7.0` |

## Use

Run each command from the project folder. The agent commands, such as `document`, `critique`, and `audit`, are in its `SKILL.md`.

| To | Run |
|---|---|
| Load the project's design context | `impeccable context` |
| Find design faults in files | `impeccable detect --json <file-or-folder>` |
| Find design faults on a page | `impeccable detect --json <url>` |
| Show the usage-data setting | `impeccable telemetry status` |

`impeccable` here is `~/.agents/skills/impeccable/scripts/impeccable`.

## Skills that need it

These skills name this tool. They do not work when it is not set up.

| Skill | What it does |
|---|---|
| `impeccable` | Use when the user wants to design, redesign, shape, critique, audit, polish, simplify, harden, animate, or otherwise imp … |

## Settings

| What | Where |
|---|---|
| Engine | `~/.impeccable/bin/<version>/impeccable` |
| Usage data | `~/.impeccable/config.json`; `"telemetry": false` turns it off. |
| Project settings | `.impeccable/config.json` in the project folder |

## Notes

- On first run, the launcher downloads the engine from the project's GitHub releases and checks its checksum.
- Usage data is on until you turn it off. A new design still asks impeccable.style for visual options.
- Never run `impeccable install` or `impeccable update`. They write the skill shelf outside your skill release.
- This page is a product page. To change it, copy it under a new name; the copy is yours.
- Your own notes on this tool go in `impeccable.local.md` beside this page; that page never ships.
