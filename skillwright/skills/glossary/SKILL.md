---
name: glossary
description: "Sharpen and record the words of a project as you design: challenge fuzzy terms, test edge cases, write approved glossary rows through the checked writer, and offer an ADR for a hard trade-off. Use when a term is unclear or overloaded, when a model change names a new thing, or in grill docs mode."
kind: knowledge
---

# Glossary

This is the active job: you change the domain model, not only read it. To look a word up, run `python3 ~/.foxrun/foxrun.py glossary <term>`; that needs no skill.
`GLOSSARY.md` is a generated view of approved glossary rows. It is not an authored page.

## Steps

1. Read the owning workspace's `AGENTS.md` and `RESOLVER.md`. Stop if the workspace folder is absent.
   Done when: you know the owner, its words table, and its checked write command.
2. Challenge words as the person talks. When a word conflicts with the glossary, say so at once: "The glossary defines 'cancellation' as X, but you seem to mean Y. Which is it?" When a word is vague, propose one exact term: "Do you mean the Customer or the User?"
   Done when: each word in play has one meaning the person agreed.
3. Test the meaning with concrete scenarios. Invent edge cases that force a boundary. When the person says how something works, check the code. Name any contradiction.
   Done when: each scenario has an answer from the person or the code.
4. Write the row with the checked write command. For Foxrun words:

   ```bash
   python3 ~/.foxrun/base/words.py --home ~/.foxrun --portfolio ~/foxrun add --workspace system --group <group> --word <word> --meaning "<meaning>" --source "<ruling or task>"
   ```

   Use `change` to edit and `remove` to retire. `remove` needs workspace, group, word, and a nonblank `--source` reason or ruling. System words use `--workspace system`; a business's words use that business's workspace. The person defines the meaning.
   Done when: the command prints the exact row it wrote.
5. Then regenerate the glossary and read it. The writer rebuilds the glossary fed by that row. For another owner, run its declared generator, which must read the same approved row store. Read the generated result.
   Done when: the generated glossary shows the new meaning.
6. Offer an ADR only when all three hold: hard to reverse, surprising without context, and the result of a real trade-off. Record the ruling as a `work.py decision-add` row. Write the ADR in `<workspace>/notes/decisions/` with [ADR-FORMAT.md](ADR-FORMAT.md). Make that folder only for the first ADR.
   Done when: the ruling has its row, and the ADR exists when all three conditions held.

## Gotchas

- Never create or edit `GLOSSARY.md` by hand, even when the page is absent. If it is absent, resolve the row writer first; its generator makes the page.
- Stop before writing if the owner, words table, checked write command, or a compatible generator is missing. Do not fall back to direct SQL, a hand-edited TSV, or a Markdown glossary.
- A file name alone does not prove a generator is compatible.
- Keep implementation decisions in ADRs, not in glossary meanings.
- `scripts/check-glossary-rows --dry-run` checks that this skill still forbids direct glossary-file writes. It is read only.

Source: built from Matt Pocock's `domain-modeling` skill (MIT), rebuilt on Foxrun word rows.
