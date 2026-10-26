---
type: note
workspace: system
timestamp: 2026-10-23T22:07:53-04:00
name: foxrun-help
description: "Answer how Foxrun does something from its own pages: the nearest AGENTS.md first, then DOCUMENTATION.md, and name the file and section used. Use for /foxrun-help, when someone asks which Foxrun skill fits, or when someone asks how Foxrun does X, where X lives, or what a Foxrun folder is for."
kind: tool
argument-hint: "<question>"
---

# foxrun-help

Foxrun answers questions about itself from its own pages, not from memory.
The nearest `AGENTS.md` holds the rules for the folder you are in. `DOCUMENTATION.md` says what each installed folder and file is for.
`bin/ask-sources` finds those files in reading order and the lines that match. It reads only.

## Steps

1. **Find the sources.** Run `bin/ask-sources "<the question>" --cwd <the folder the person works in>`. Done when the JSON lists `sources` and `start_with`.
2. **Read before you answer.** Open `start_with` at the lines in its `hits`, and read the whole section around each hit. If those lines do not answer the question, read the next source in order. Done when one section answers the question, or every source is read.
3. **Answer.** Give the answer in a few lines. End with the file and section you used, as `Source: <path>, section <name>`. Done when the answer names its source.
4. **Say when the pages are silent.** If no source answers, say so, name the files you read, and say where the answer should live. Never fill the gap from memory. Done when the person knows the pages do not answer it.

5. **Route a "which skill?" question.** When the person asks which skill or flow fits a situation, read [references/skill-map.md](references/skill-map.md). Name one skill and its first command, and say why it fits in one line. Done when the person has one pick and its command.

## Gotchas

- An installed page in `~/.foxrun/` is a copy of the product. If it looks wrong, say so; do not edit it there.
- A rule the person ruled outranks a page. If the question touches a ruling, run `python3 ~/.foxrun/foxrun.py rulings <words>` and say which one wins.
- `hits` match words, not meaning. A source with no hits can still hold the answer under other words; read its headings before you call the pages silent.
