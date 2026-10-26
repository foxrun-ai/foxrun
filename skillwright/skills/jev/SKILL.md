---
name: jev
description: "Run typed Jev judgments through OpenRouter, then log them: a choice, a score, or a yes or no, stored in the tracker. Use only when the person names Jev, or when another loaded skill calls this skill. Add-on: needs Node.js 22.18 or later and your own OpenRouter account and credit."
kind: knowledge
---

# Jev

Jev is TypeSafe's fast judgment model. It answers typed Choice, Score, or boolean questions about bounded state with probabilities, not prose.
Use it for classification, routing, scoring, ranking, extraction choices, and checks. Keep exact rules, math, permissions, and final actions in code. A probability is not proof.

Run only after the person names Jev, or after another loaded skill calls it. Never route work to Jev on your own. Each run spends OpenRouter credit.

Read [references/input-schema.md](references/input-schema.md) for the request and storage fields.
Read [references/typesafe-guide.md](references/typesafe-guide.md) when you design questions or an app around Jev. It is TypeSafe's own guide, MIT, vendored from `https://github.com/typesafe-ai/skills` (plugin 0.5.7, commit `65a39f393687675ce170e6094757de20370365b9`); its license is `references/typesafe-LICENSE`.

## Setup

- The Add-on page is `~/.foxrun/tools/service/jev.md`. Follow its Install and Check rows.
- The runner reads the OpenRouter key through `agent-secret-read` on your command path, with the reference `op://Foxrun/OpenRouter/credential`. Set `JEV_SECRET_TOOL` or `JEV_SECRET_REF` to use another reader or reference. Never print or save the key.

## Steps

1. Write one JSON request with a stable `request_id`, a clear `use_case`, the question-set version, and the state-schema version. Chunk long state and keep source ids in each chunk.
   Done when: the file parses as JSON.
2. Set `storage.database` to the tracker as an absolute path, such as `$HOME/.foxrun/data.db`. Record every run unless the person asks for an unrecorded one.
   Done when: the request names the tracker, or the person's words for an unrecorded run.
3. Run it from the skill folder:

   ```bash
   node scripts/jev.mjs request.json
   node scripts/jev.mjs --progress <run folder>/progress.jsonl --concurrency 2 batch.json
   node scripts/jev.mjs --progress <run folder>/progress.jsonl --resume batch.json
   ```

   A batch is `action: "batch"` with a `requests` array. Defaults: concurrency 2 (1 to 32), max attempts 4 (1 to 10). Keep the progress file in a run folder you own.
   Done when: stdout prints one JSON object with `ok`, or a batch summary with success, failure, retry, rate-limit, skip, and wall-time counts.
4. Report the judgment with its probability, the `request_id`, and the stored run.
   Done when: the answer names the run and does not claim more than the probability says.

## Gotchas

- A store you own needs its tables first: `touch` the file, then send `{"action":"migrate","database":"<absolute path>"}`. An `evaluate` call never makes tables. Stop if the migration fails.
- A reused `request_id` with changed input fails with `request_id_conflict`. Use a new id.
- Raw state goes to OpenRouter but is not stored. The record keeps a SHA-256 hash, metadata, answers, time, tokens, and cost only when OpenRouter supplies it. Unknown cost stays `unknown`.
- Quality starts `unchecked`. Add feedback only with a durable evidence path. Do not run routine comparisons with other models.
- A returned model alias does not name the model version.
