---
type: doc
workspace: system
timestamp: 2026-10-19T19:35:51-04:00
---
# Agent Contracts test

`contract_test.py` gives one model command only selected contract files and fifteen fixed questions.
Five questions cover each layer: root, workspace, and runtime.
The answer key stays outside model input. Scoring compares exact option IDs.
The supplied key covers Foxrun. Other workspaces need their own fixed questions and answer key.

Claude and Codex on day one.
The practice test checks this protocol only. Runtime labels do not prove native runtime behavior.
An adapter reads stdin and writes `{"answers":{"question-id":"option-id"}}` to stdout.
Select a command that makes one fresh inference call. It must load no memory or other files.
The runtime name records the caller's adapter. It does not prove native runtime behavior.
The supplied model command runs in an empty directory with a clean HOME and no inherited credentials.
This mode neither discovers credentials nor starts a native agent.

```sh
python3 contract_test.py --root /absolute/vault --workspace foxrun \
  --contract agents/soul.md --contract profile/AGENTS.md --contract foxrun/AGENTS.md \
  --contract CLAUDE.md --contract foxrun/CLAUDE.md \
  --questions /absolute/contract-test-questions.json \
  --answer-key /absolute/contract-test-answers.json \
  --runtime Codex --model-command '["/absolute/approved-model-adapter"]' \
  --run-dir /absolute/private-test-runs
```

Each run retains request, response, and score files. It never overwrites an earlier run.
Exit 0 means every answer matches. Exit 1 means an answer differs. Exit 2 means the run failed.
`tests/contract_test_stub.py` proves this protocol without a model call.
A stub score is never evidence that an agent understands the contracts.
Record each real model score separately. Preserve the selected contract hashes with that score.

## Native baseline

Claude and Codex on day one.
Supply `--fresh-root` for empty native test folders. Each folder starts with only the selected contract copies.
`--layer workspace` selects five workspace questions. The Cedar Shop question and answer files cover that workspace's current contract.
Native calls set `FOXRUN_NO_SESSION_LOG=1`. Codex uses read-only mode and ephemeral sessions.
Claude disables tools, session persistence, and extra customizations.
An operating-system guard permits writes only inside the fresh folder.
Codex also ignores user configuration and rules. Claude uses safe mode and a single turn.
The harness retains questions, answers, command records, errors, and scores outside that folder.
Startup failures have no score. They must not count as failed knowledge answers or successful runtime coverage.
These scores measure today's contract text. They do not prove native load behavior for files omitted from the input.
