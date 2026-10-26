---
name: tldr
description: "Compress messy notes, reports, plans, sessions, research, or agent output into a short readout the person can scan on a phone. Variants: exec, meeting, report, handoff, simple, brutal. Use when the person asks for a TLDR, TL;DR, readout, quick scan, executive summary, or a high-signal top section."
kind: knowledge
---

# TLDR

This is signal compression, not a general summary. Keep what matters, cut process talk, split facts from guesses, and make the next move plain.

## Steps

1. Pick the variant from the person's words. With no variant, use the default.
   Done when: you named the variant to yourself.
2. Find what survives, in this order: what changed, what is done, what is blocked, what the person must decide or send, the next action, and the evidence someone would ask for. Cut the rest.
   Done when: each kept line answers one of those six.
3. Write the readout in the variant's shape. Put anything the person must do in the first one or two lines.
   Done when: it fits one phone screen, unless the person asked for more detail.
4. Check the words: exact names, dates, amounts, owners, links, and paths are unchanged. Pending work says pending. An unsent or unapproved outside action says so.
   Done when: nothing staged reads as done.

## Variants

| Say | Shape |
|---|---|
| `/tldr` | **TLDR**: Done or decided · In progress · Blocked or needs you · Next. 3 to 6 bullets. |
| `/tldr exec` | Status · Business impact · Risk · Decision or next move. |
| `/tldr meeting` | Goal · Ready to report · Needs decision · Ask. |
| `/tldr report` | Finding · Recommendation · Caveat · Evidence. |
| `/tldr handoff` | Objective · Current state · Blockers · Next action · Files or links. |
| `/tldr simple` | **Right now** (short facts) · **Simple version** (one or two plain sentences) · **My call** (the pick). Use it for a plan or a decision, not a status report. |
| `/tldr brutal` | Five bullets at most. No background unless it stops a wrong conclusion. |

Add an **Evidence** section only when it helps: `- <source or path> - what it proves.`

## Gotchas

- Start with the answer, not the context. Use bold labels, one scan mark per line at most, and no nested bullets by default.
- "TLDR" has levels. When the person asks for more detail, expand into short grouped sections. Do not repeat the short shape.
- When the person just gave new inputs and asks for a TLDR, sum up those inputs first: specs, links, files, limits. Do not drift back to older context.
- Use plain status words: Done, Staged, Drafted, Sent, Posted, Blocked, Waiting on <who>, Needs check. Avoid "handled", "addressed", "looked into", and "worked on".
- Mark a guess as a guess when accuracy matters.
- Never paste sensitive data from screenshots, emails, receipts, credentials, or customer records.
- When the person says "hold" or is still sending pieces, say you got it and wait.
