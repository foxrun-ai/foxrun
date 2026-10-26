---
name: runtime-session-search
description: "Find a past agent session by words or id in Claude, Codex, or Hermes (every profile), read its final reply, and return the native session id so orchestrate can resume it. Use when the person asks what happened before, what was tried before, how a problem was worked across sessions, where a session went, what an agent last said, or wants to pick up old work. Reads the runtimes' own session files directly, read-only; needs no hosted pane."
kind: tool
---

# runtime-session-search

`bin/runtime-session-search` reads the session files each runtime keeps under the home folder and prints JSON.
Summarize the JSON for the person; never paste it raw.
It needs no other skill. The store readers ship beside it in `lib/session_stores.py`.

| Verb | What it does |
|---|---|
| `find "<words or id>" [--runtime claude\|codex\|hermes] [--since 90d\|all] [--limit 15]` | Hits across Claude JSONL, Codex rollouts, and Hermes `state.db` (main and every profile). Ids rank above words. Each hit carries `session_id`, `store`, `profile`, `when`, `cwd`, `attach_or_resume_cmd`, `read_with`, `orchestrate_with`. |
| `read <exact-native-id> [--runtime …] [--profile …]` | The last user message and the final assistant reply, 8 KB or 120 lines at most. Reasoning and tool payloads stay out. `resume_with` is included. |
| `check-memex` | Whether memex passes the exact capability check and its index is fresh. |

## Steps

1. Run `find` with the person's words, or with the id they gave. Done when the status is `found`, `not_found`, or `choice_required`.
2. On `choice_required`, show the choices and ask for the runtime or the exact id. Done when one id is left.
3. Run `read <id>` with `--runtime` (and `--profile` for Hermes) from the hit. Done when the status is `read` or `no_reply`.
4. Tell the person what the session last said, and give the `resume_with` command or hand the id to `orchestrate`. Done when they have the id and the next command.

Question mode: when the person asks a question about past work ("what did we try for the login bug?") rather than for one session:

5. Turn the question into two or three short word searches, and run `find` for each, with `--since all` if the work may be older than 90 days. Done when you hold the hits from every search.
6. Run `read` on the three to five best hits, newest first. Done when each read is `read` or `no_reply`.
7. Answer the question in a few lines. Name the session id and date behind each claim, and say what you did not find. Done when every claim cites a session id.

## Laws

- Native files are truth: `~/.claude/projects`, `~/.codex/sessions`, `~/.hermes/state.db`, and `~/.hermes/profiles/*/state.db`, read-only. `--stores-root` (or `RUNTIME_SESSION_SEARCH_STORES`) points at another home folder.
- memex is a speed layer only when `check-memex` passes and its index is not older than the newest transcript by a day. Otherwise the built-in readers run. memex is optional; the skill works without it.
- Missing or ambiguous matches stay explicit: `not_found`, `choice_required` (several ids match a prefix, or several stores hold the id), `no_reply`. Never guess; ask for the exact id or runtime.
- Saved text never proves task success (`task_success: not_inferred`).
- Search is separate from cleanup: this skill never closes, resumes, or spawns. Hand the id to `orchestrate` (`--session-id`) for more work, or to `herdr resume <id>` when the herdr skill is on the shelf.

## Gotchas

- A runtime that is not installed has no folder. Its store is skipped and `adapter_notes` says so; that is not an error.
- `--since` defaults to 90 days for word searches. Use `--since all` for older work. An id search ignores the window.
- A Codex thread that the Codex app owns resumes with `codex exec fork`, not `codex exec resume`.
