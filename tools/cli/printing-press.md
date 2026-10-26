---
type: tool
workspace: system
timestamp: 2026-10-18T15:37:45-04:00
name: printing-press
what: "Add-on: production command tool generator"
kind: cli
use: dev & repos
status: candidate
command: cli-printing-press
---
# printing-press

printing-press is "Describe your API. Get a production CLI." (its makers' words). In plain words: it builds and checks a typed command tool from a description of an online service.

**How Foxrun uses it.** This part is Foxrun's use, not the tool:

- Agents search its library for a tool before they build a new one.
- When a service has no command, agents use it to make one from the service's interface spec.
- Each custom tool pins the factory version that built it.
- Installing a tool or skill from its catalog needs your yes.

**Install:** [printing-press install](https://github.com/mvanhorn/cli-printing-press#readme) · `go install github.com/mvanhorn/cli-printing-press/v4/cmd/cli-printing-press@latest`

| Field | Value |
|---|---|
| Use | dev & repos · [all tools, by use](../CAPABILITIES.md) |
| Kind | cli |
| Status | ⬜ candidate · Foxrun does not install it |
| Where | Not on disk until you install it. `go install` puts it in your Go bin folder. |
| His yes | Installing it, connecting accounts, and paid service or model use need your yes. |
| Source | The tool: its README at `https://github.com/mvanhorn/cli-printing-press`. License not checked yet. |
| Owner | product · Foxrun ships this page. An update replaces it. |
| Why | recommended · it builds a command for a service an agent must reach. |

## Install

| Step | Command | It prints |
|---|---|---|
| Get Go | Go 1.26.5 or newer, from `https://go.dev/dl/` | — |
| Install | see the code block below | — |
| Check | `cli-printing-press --version` | `cli-printing-press` and the number |

```sh
go install \
  github.com/mvanhorn/cli-printing-press/v4/cmd/cli-printing-press@latest
```

## Use

| To | Run |
|---|---|
| Show commands | `cli-printing-press --help` |
| Generate a command project | `cli-printing-press generate` |
| Check generated code | `cli-printing-press shipcheck` |

## Skills that need it

No skill names this tool.

## Settings

| What | Where |
|---|---|
| Tool command | Your Go bin folder; `go env GOPATH` shows its parent. |
| Service access | Each service's own sign-in; never copy it to a page. |

## Notes

- Its license is not verified yet. Read the upstream license before you install it.
- Service and model use can cost money.
- This page is a product page. To change it, copy it under a new name; the copy is yours.
