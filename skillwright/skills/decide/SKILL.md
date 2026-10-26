---
name: decide
description: "Decide one choice through a door check and one resolver: two-way door, the 4-step, the algorithm, inversion, hell yes or no, and kill criteria. Use when an agent or the person must decide, size the rigor, stop something, or say no."
kind: knowledge
---

# Decide

One router, five resolvers, six frameworks. The door check sets the speed. One resolver makes the call. Every run ends in the output contract below.
To record a ruling the person already made, use `work.py decision-add`, not this skill.

## Steps

1. State the decision in one line. Name the options. Split facts from assumptions.
   Done when: the line, the options, and the two lists are written.
2. Run the door check in `frameworks/two-way-door.md`. A two-way door: decide now with about 70% of the facts. A one-way door: slow down, cap the downside, and ask the person when a gate in `~/.foxrun/config/gates.md` applies.
   Done when: the door and the speed are named.
3. Pick one resolver by the kind of decision:

   | The decision is... | Resolver | File |
   |---|---|---|
   | a problem someone brought | the 4-step | `frameworks/four-step.md` |
   | build, cut, or automate a process, tool, or system | the algorithm | `frameworks/algorithm.md` |
   | a plan about to be committed, or a stuck choice | inversion and pre-mortem | `frameworks/inversion.md` |
   | an opportunity, invite, deal, or commitment | hell yes or no | `frameworks/hell-yes.md` |
   | something that runs: start it, keep it, or stop it | kill criteria | `frameworks/kill-criteria.md` |

   Done when: one resolver file is open.
4. Answer the resolver's questions in order, one line each.
   Done when: each question has its line.
5. Report with the output contract.
   Done when: every field is filled, and the next step is one action with an owner.

## Output contract

- Decision:
- Door: two-way / one-way
- Resolver:
- Facts / assumptions:
- Risk accepted (what breaks):
- Next step + owner:
- Kill criteria (only if something now runs):

Keep it to one screen, decision first, in plain words.

## Chaining

- door check -> any resolver
- 4-step -> the algorithm, when the answer is "build or cut something"
- inversion -> hell yes or no, when the choice is still open after the failure scan
- any resolver -> kill criteria, when the decision starts something that runs

## Gotchas

- Chain a second resolver only when the first one names it. One resolver per decision is the default.
- This skill never widens a gate. Money, sends, deletes, and production changes still go to the person.
- Each framework file names its source. Cite it when the person asks why.
