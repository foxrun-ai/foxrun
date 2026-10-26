---
name: grill
description: "Grill the person on a plan, decision, or idea, in rounds, until every branch is decided. Modes: rounds (default), one (one question at a time), docs (also writes glossary rows and ADRs). Use when the person says grill me, stress-test this, Q&A, ask me questions, or interview me."
kind: knowledge
---

# Grill

Interview the person until you both share one understanding. Map the talk as a design tree: each decision branches into the decisions that hang off it.
Facts are your job. Decisions are the person's job.

## Modes

| Mode | Say | What changes |
|---|---|---|
| `rounds` | `/grill` | Ask the whole frontier in one numbered round. The default. |
| `one` | `/grill one`, `Q&A`, `ask me questions` | Ask one question, wait, then ask the next. Use it on a phone or when answers reshape the next question. |
| `docs` | `/grill docs` | Run `rounds`, and run the `glossary` skill as words and trade-offs resolve. |

## Steps

1. Pick the mode from the person's words. When unsure, use `rounds`.
   Done when: the mode is named in your first line.
2. Build the frontier: every decision whose prerequisites are settled. A question that depends on another open question waits for a later round.
   Done when: no frontier question depends on an open one.
3. Find facts yourself. When a question needs a fact from files or tools, look it up, or send a subagent. Ask the rest of the frontier while it runs. Never ask the person for a fact you can find.
   Done when: every question you ask is a decision, not a lookup.
4. Ask the round. Number each question, give short context, the options, and your pick:

   ```
   **Q1 - <title>**: <context, the question, the options>

   My pick: <recommended answer>
   ```

   In `one` mode, ask only Q1. Offer the options as a tap choice when the runtime has one, and always allow a free answer.
   Done when: each question carries your pick.
5. Take the answers. Confirm each one in one line. Settled decisions move the frontier out. Recompute it and ask the next round.
   Done when: each answer is restated as a decision.
6. Stop when the frontier is empty: every branch visited, nothing left assumed. Give one summary of all decisions.
   Done when: the person confirms the summary.

## Gotchas

- Do not act on the plan until the person confirms the summary.
- File each ruling with `work.py decision-add` and each yes with `approval-add`, in the same turn.
- In `docs` mode, write glossary rows only through the `glossary` skill's checked writer. Never edit `GLOSSARY.md` by hand.
- Keep context lines short. The person may be on a phone.

Source: the design-tree method comes from Matt Pocock's `grilling` skill (MIT).
