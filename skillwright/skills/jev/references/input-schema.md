# Jev runner input

The runner accepts one JSON object from a file or stdin. It writes one JSON object to stdout. It never echoes raw state in errors.

## Batch

```json
{
  "action": "batch",
  "requests": [
    {"action": "evaluate", "request_id": "item-1", "use_case": "example", "request_schema_version": "1", "question_set_version": "v1", "state_schema_version": "v1", "state": {"item": "one"}, "questions": {"yes": {"type": "boolean", "instructions": "Does it fit?"}}},
    {"action": "evaluate", "request_id": "item-2", "use_case": "example", "request_schema_version": "1", "question_set_version": "v1", "state_schema_version": "v1", "state": {"item": "two"}, "questions": {"yes": {"type": "boolean", "instructions": "Does it fit?"}}}
  ]
}
```

Run `node scripts/jev.mjs --progress /absolute/path/progress.jsonl --concurrency 2 --max-attempts 4 batch.json`. All items must have distinct, stable `request_id` values. Defaults are 2 workers and 4 attempts. The progress file appends one line for each finished request. Each line has `request_id`, `ok`, `attempts`, `rate_limited`, and either `result` or a safe `error`. The stdout summary has `ok`, `failed`, `skipped`, `retried`, `rate_limited`, and `wall_time_ms`. The command exits 1 if any request fails. `retried` counts extra attempts. `rate_limited` counts rate-limited attempts. Use `--resume` with the same progress file to skip IDs already marked successful. Do not reuse an ID for changed input.

On HTTP 429, the runner waits at least Retry-After plus up to 499 ms of jitter. It also retries `provider_failed` and timeouts with exponential backoff. A stored failed run with matching input can be reclaimed by batch retry with the same ID. Batch ends after at most `--max-attempts` per item. Provider answer validation reports a fixed `error.check` name, with no provider state. Tiny probability overruns up to `1e-6` are clamped to `[0, 1]`.

## Evaluate

```json
{
  "action": "evaluate",
  "request_id": "stable-caller-id",
  "use_case": "support escalation classification",
  "request_schema_version": "1",
  "question_set_version": "support-v1",
  "state_schema_version": "ticket-v2",
  "state": {"ticket": "bounded state supplied by the caller"},
  "questions": {
    "route": {
      "type": "choice",
      "instructions": "Which route best fits the ticket?",
      "criteria": {
        "billing": "Payment or invoice problem",
        "technical": "Product behavior problem"
      }
    },
    "urgency": {
      "type": "score",
      "instructions": "How urgent is the ticket?",
      "criteria": ["Routine", "Time-sensitive", "Immediate risk"]
    },
    "needs_human": {
      "type": "boolean",
      "instructions": "Does this ticket need a person now?"
    }
  },
  "output_ref": "optional caller-owned artifact reference",
  "storage": {
    "database": "/absolute/path/to/home/.foxrun/data.db",
    "required": true
  }
}
```

Choice `criteria` is a nonempty object. Score `criteria` contains at least two ordered levels. Boolean `criteria` is optional and can describe `true` and `false`. The runner sends boolean questions to OpenRouter as `noul` and maps returned `{ "noul": p }` answers to `{ "type": "boolean", "probability": p }`. It preserves `confidence` when OpenRouter supplies it.

The OpenRouter model is fixed to `~typesafe/jev-latest`. A completed matching request returns the stored result. A reused ID with different input fails. A failed stored run needs batch retry; a single evaluation still reports `previous_run_failed`.

Split long inputs before calling Jev. Keep source IDs in each chunk. `model.returned` is the model name supplied by OpenRouter. `model.version` stays `null` unless OpenRouter supplies one.

If `storage.required` is `false`, a storage failure does not discard a completed model result. The output marks recording as failed. Use this only when an unrecorded result is acceptable.

## Add feedback

Feedback is append-only. A review does not count without evidence. Use `fit` and `rationale` to record whether Jev suited this job and why.

```json
{
  "action": "feedback",
  "database": "/absolute/path/to/agent-os.sqlite",
  "request_id": "stable-caller-id",
  "kind": "review",
  "assessment": "accepted",
  "fit": "fit",
  "rationale": "The typed answer was sufficient for this bounded route decision.",
  "evidence_ref": "/absolute/path/to/review-evidence",
  "note": "Optional short note without raw sensitive state"
}
```

`kind` is `review`, `correction`, or `outcome`. `assessment` is `accepted`, `rejected`, `mixed`, or `informational`. Optional `fit` is `fit`, `uncertain`, or `not_fit`. When `fit` is present, include a short `rationale`.

## Apply the additive schema

Migration is a separate, reviewable action. It never runs during evaluation.

```json
{
  "action": "migrate",
  "database": "/absolute/path/to/isolated-or-approved-agent-os.sqlite"
}
```

The migration source is [agent-os-migration.sql](agent-os-migration.sql). Test it on an isolated database before any approved live application.
