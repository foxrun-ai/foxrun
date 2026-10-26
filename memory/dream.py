#!/usr/bin/env python3
"""The memory job: a code half first, then a model half that only proposes.

  dream.py run      the whole night: the code half, then the model half
  dream.py code     the code half only; needs no model
  dream.py report   show the report of the last night

The code half has six steps, in this order:
  kept     link frozen replies into topic notes, or file an inbox task
  state    build STATE.md in the system home and in each workspace
  index    build index.md in each workspace and at the top of the portfolio, in the shape of base/templates/index.md
  daily    write the page of the last full day in each workspace, with day, week, and month counts
  backup   write the tables of the system database into state/, and of each workspace database into backups/jsonl/<workspace>/
  checks   run the checks; every finding becomes its own bug row; nothing is fixed
The model half selects tool-free inference from config/models.yaml and only writes a proposals file.
With no configured model transport, the model half records skipped: no model and the job still passes.
Each call leaves its own folder: runs/nightly/<date>-dream/, then -2, -3, with manifest.json, steps.jsonl, report.md.
"""

from __future__ import annotations

# With no FOXRUN_HOME set, the job works on the home this file is in. The launcher has the same rule.
import os as _home_os
from pathlib import Path as _HomePath
_home_os.environ.setdefault('FOXRUN_HOME', str(_HomePath(__file__).resolve().parents[1]))

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_sys.path.insert(0, str(_FoxPath(__file__).resolve().parent / '..'))
from base import paths as _fox_paths

import argparse
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

import handoff_check as hc
import state as pages


HOME = Path.home()
WORKSPACE_ROOT = _fox_paths.portfolio() / _fox_person.workspace('system')
JEV = Path(os.environ['FOXRUN_JEV_RUNNER']).expanduser() if os.environ.get('FOXRUN_JEV_RUNNER') else None
TASK_ID = re.compile(r"(?<![\w-])T\d+(?![\w-])")
WORKER_BRIEF = re.compile(r"(?is)^# Brief:.*?\bYou are\b.{0,120}\bworker\b")
ROLE_BRIEF = re.compile(r"(?is)^Workspace:.*?\bYou are\s+(?:an?\s+)?[\w -]+\b(?:worker|lead|agent|reviewer|architect|builder|operator)\b")
SYNTHETIC_CONTEXT = re.compile(
    r"^(?:Here is a list of plugins that are available but not installed\.|# AGENTS\.md instructions for )")
RUN_BY = "session-nightly"
TIME_BUDGET_SECONDS = 20 * 60


@dataclass
class Config:
    tracker: Path = _fox_paths.database()
    other_tracker: Path = (_fox_paths.database())
    receipt_root: Path = WORKSPACE_ROOT
    output_root: Path = WORKSPACE_ROOT / "history/outputs/nightly"
    state_file: Path = (_fox_paths.state() / 'session-nightly/state.json')
    scratch_dir: Path = (_fox_paths.state() / 'session-nightly')
    claude_root: Path = HOME / ".claude/projects"
    codex_root: Path = HOME / ".codex/sessions"
    dry_run: bool = False
    rerun: bool = False
    since: datetime | None = None
    now: datetime | None = None
    budget_seconds: int = TIME_BUDGET_SECONDS


def readonly(path: Path) -> sqlite3.Connection:
    return _fox_person.connect(f"file:{path}?mode=ro", uri=True)


def parse_time(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("time needs a UTC offset")
    return stamp


def dream_task():
    return os.environ.get('FOXRUN_DREAM_TASK') or _fox_person.configuration().get('dream_task', 'dream-review')


def last_success(tracker: Path) -> datetime | None:
    with closing(readonly(tracker)) as db:
        row = db.execute(
            'SELECT note,ended_at FROM runs WHERE subject_type=? AND subject_id=? AND "by"=? AND result=? ORDER BY ended_at DESC LIMIT 1',
            ("task", dream_task(), RUN_BY, "pass"),
        ).fetchone()
    if not row:
        return None
    match = re.search(r"(?:^|\n)scan_end=([^\n]+)", row[0] or "")
    return parse_time(match.group(1)) if match else parse_time(row[1]) - timedelta(minutes=30)


def existing_run(tracker: Path, date: str) -> tuple[str, str | None] | None:
    with closing(readonly(tracker)) as db:
        rows = db.execute(
            'SELECT id,result,started_at FROM runs WHERE subject_type=? AND subject_id=? AND "by"=? ORDER BY started_at DESC',
            ("task", dream_task(), RUN_BY),
        ).fetchall()
    for run_id, result, started_at in rows:
        if parse_time(started_at).astimezone(hc.LOCAL_ZONE).date().isoformat() == date:
            return run_id, result
    return None


def session_activity(path: Path, cutoff: datetime, deadline: float) -> bool:
    """Use transcript timestamps, since file modification time alone can be misleading."""
    if path.stat().st_mtime <= cutoff.timestamp():
        return False
    latest = None
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if time.monotonic() >= deadline:
                raise TimeoutError("session scan exceeded the time budget")
            try:
                stamp = json.loads(line).get("timestamp")
                if isinstance(stamp, str):
                    moment = parse_time(stamp)
                    if latest is None or moment > latest:
                        latest = moment
            except (ValueError, TypeError):
                continue
    return bool(latest and latest > cutoff)


def recent_sessions(cfg: Config, cutoff: datetime, deadline: float) -> list[Path]:
    paths = list(cfg.claude_root.glob("*/*.jsonl"))
    paths.extend(cfg.codex_root.rglob("rollout-*.jsonl"))
    return [path for path in sorted(paths) if path.is_file() and session_activity(path, cutoff, deadline)
            and not automated_session(path)]


def automated_session(path: Path) -> bool:
    run_root = _fox_paths.runs()
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            entrypoint = str(row.get("entrypoint", ""))
            source = payload.get("source")
            cwd = row.get("cwd") or payload.get("cwd")
            if entrypoint or source or cwd:
                if entrypoint.startswith("sdk-") or source == "codex_exec":
                    return True
                if not isinstance(cwd, str):
                    return False
                project = Path(cwd).expanduser().resolve(strict=False)
                return project == run_root or run_root in project.parents
    return False


def task_target(turn: dict, data: hc.Extract, valid_tasks: set[str], rows: list[tuple],
                run_tasks: set[str]) -> str:
    def first_open(ids):
        return next((task for task in ids if task in valid_tasks), None)

    direct = first_open(TASK_ID.findall(turn["text"]) + TASK_ID.findall(turn.get("assistant_before", "")))
    if direct:
        return direct
    moment = parse_time(turn["timestamp"])
    comments = sorted((row for row in rows if row[0] == "comment" and row[2] in valid_tasks
                       and row[7] is not None and moment <= row[7] <= moment + timedelta(minutes=30)),
                      key=lambda row: row[7] - moment)
    if comments:
        return comments[0][2]
    in_run = first_open(sorted(run_tasks))
    if in_run:
        return in_run
    position = next((i for i, item in enumerate(data.person) if item["index"] == turn["index"]), 0)
    nearby = data.person[max(0, position - 10):position + 11]
    counts = Counter(task for item in nearby for task in TASK_ID.findall(item["text"]) if task in valid_tasks)
    if counts:
        return counts.most_common(1)[0][0]
    return dream_task()


def actionable_turn(text: str) -> bool:
    """Keep concrete instructions inside questions; leave exploratory questions out."""
    if text.count("?") < 2:
        return True
    if re.search(r"\b(?:approved|run it|send it|the rule is|from now on)\b", text, re.I):
        return True
    if re.search(r"\bwe need to\b", text, re.I) and not re.search(r"\bmaybe\s+we need to\b", text, re.I):
        return True
    return False


def candidates_for(data: hc.Extract, report: dict, valid_tasks: set[str], rows: list[tuple],
                   run_tasks: set[str], drops: list[dict] | None = None) -> list[dict]:
    by_index = {turn["index"]: turn for turn in data.person}
    candidates = []
    for kind, items in (("unpromoted", report["unpromoted"]),
                        ("warning", report["warnings"]),
                        ("date mismatch", report["date_mismatch"])):
        for item in items:
            turn = by_index[item["index"]]
            if not turn["timestamp"]:
                raise ValueError("candidate turn has no timestamp")
            if not actionable_turn(turn["text"]):
                if drops is not None:
                    drops.append({"session": data.session, "timestamp": turn["timestamp"],
                                  "text": turn["text"], "reason": "question-heavy turn without a concrete ruling"})
                continue
            candidates.append({
                "key": f"{data.session}|{turn['timestamp']}",
                "session": data.session,
                "source": data.source,
                "kind": kind,
                "timestamp": turn["timestamp"],
                "local_time": parse_time(turn["timestamp"]).astimezone(hc.LOCAL_ZONE).isoformat(timespec="milliseconds"),
                "text": turn["text"],
                "assistant_before": turn.get("assistant_before", ""),
                "task": task_target(turn, data, valid_tasks, rows, run_tasks),
            })
    return candidates


def person_turns_only(data: hc.Extract) -> None:
    f"""A delegated worker brief is a user role message, but not {_fox_person.display_name()}'s words."""
    data.person = [turn for turn in data.person
                   if not WORKER_BRIEF.search(turn["text"][:500])
                   and not ROLE_BRIEF.search(turn["text"][:200])
                   and not SYNTHETIC_CONTEXT.search(turn["text"])]


def jev_batch(cfg: Config, items: list[dict], deadline: float) -> tuple[dict[str, float], float | None, str | None]:
    if not items:
        return {}, 0.0, None
    requests = []
    date = (cfg.now or datetime.now().astimezone()).astimezone(hc.LOCAL_ZONE).date().isoformat()
    for item in items:
        state = {
            "assistant_turn_before": item["assistant_before"][-3000:],
            "person_turn": item["text"][:3000],
        }
        request_source = json.dumps({"key": item["key"], "state": state, "version": "v4"},
                                    sort_keys=True, ensure_ascii=False)
        request = {
            "action": "evaluate",
            "request_id": "session-nightly-v4-" + date + "-" + hashlib.sha256(request_source.encode()).hexdigest()[:24],
            "use_case": f"session-nightly {_fox_person.display_name()} decision capture",
            "request_schema_version": "1",
            "question_set_version": "session-nightly-v4",
            "state_schema_version": "person-turn-v1",
            "state": state,
            "questions": {"keep": {
                "type": "boolean",
                "instructions": (f"Does {_fox_person.display_name()}'s turn settle a decision or standing rule that must outlive "
                                 "this session? Answer true for a choice between options, a rule for the "
                                 "future, a definition, or approval of a named plan or list. Answer false "
                                 "for a one-time go-ahead done at the time, such as 'run it', 'send it', "
                                 "'yes', 'go', 'do it', or 'ship it'. Also answer false for questions, "
                                 "praise, acknowledgements, requests to show work, and plans to discuss later."),
            }},
        }
        requests.append(request)
    if cfg.dry_run:
        schema = os.environ.get('FOXRUN_JEV_SCHEMA')
        if not schema or not Path(schema).expanduser().is_file():
            return {}, 0.0, 'Set FOXRUN_JEV_SCHEMA to the optional runner schema for dry-run storage'
        with tempfile.TemporaryDirectory(prefix="session-nightly-jev-") as folder:
            database = Path(folder) / "jev.sqlite"
            with _fox_person.connect(database) as db:
                db.executescript((Path(schema).expanduser()).read_text())
            for request in requests:
                request["request_id"] += "-" + uuid.uuid4().hex[:8]
                request["storage"] = {"database": str(database), "required": True}
            return run_jev_batch(requests, items, Path(folder) / "progress.jsonl", deadline)
    cfg.scratch_dir.mkdir(parents=True, exist_ok=True)
    for request in requests:
        request["storage"] = {"database": str(cfg.tracker), "required": True}
    return run_jev_batch(requests, items, cfg.scratch_dir / f"{date}-progress.jsonl", deadline)


def run_jev_batch(requests: list[dict], items: list[dict], progress: Path,
                  deadline: float) -> tuple[dict[str, float], float | None, str | None]:
    command = [os.environ.get("FOXRUN_NODE", "node"), str(JEV), "--progress", str(progress),
               "--concurrency", "2", "--resume"]
    try:
        completed = subprocess.run(command, input=json.dumps({"action": "batch", "requests": requests}),
                                   text=True, capture_output=True, timeout=max(1, deadline - time.monotonic()))
    except (OSError, subprocess.TimeoutExpired):
        return {}, None, "Jev not run"
    try:
        scores = {}
        costs = {}
        wanted = {request["request_id"] for request in requests}
        for line in progress.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not row.get("ok") or row.get("request_id") not in wanted:
                continue
            result = row["result"]
            answer = result["answers"]["keep"]
            score = answer["probability"]
            if not isinstance(score, (int, float)) or not 0 <= score <= 1:
                raise ValueError("invalid Jev probability")
            scores[row["request_id"]] = float(score)
            cost = result.get("provider_cost", {}).get("amount")
            if isinstance(cost, (int, float)):
                costs[row["request_id"]] = float(cost)
        mapped = {item["key"]: scores[request["request_id"]]
                  for item, request in zip(items, requests) if request["request_id"] in scores}
        missing = len(items) - len(mapped)
        return mapped, sum(costs.values()) if len(costs) == len(items) else None, (
            f"Jev failed for {missing} item(s)" if missing else None)
    except (KeyError, ValueError, TypeError, OSError, json.JSONDecodeError):
        return {}, None, "Jev not run"


def bug_fields(problem: str, when: str, want: str, so: str, context: str, where: str) -> tuple[str, ...]:
    """Every bug carries the six fields (T718); a filed check names its own."""
    return ("--problem", problem, "--job-when", when, "--job-want", want, "--job-so", so,
            "--body", "Fixes the defect the check found", "--acceptance", "The check that filed this bug passes",
            "--context", context or "Filed by the nightly check", "--where", where)


def call_work(cfg: Config, *arguments: str) -> str:
    command = [sys.executable, str((Path(__file__).resolve().parent / '../work/work.py')),
               "--db", str(cfg.tracker), "--receipt-root", str(cfg.receipt_root), *arguments]
    result = subprocess.run(command, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"work.py {arguments[0]} failed: {result.stderr.strip()[:300]}")
    return result.stdout.strip()


def already_flagged(tracker: Path, item: dict) -> bool:
    prefix = f"Flag: unpromoted {_fox_person.display_name()} words, {item['session'][:13]} {item['local_time']}:"
    with closing(readonly(tracker)) as db:
        return bool(db.execute("SELECT 1 FROM comments WHERE subject_type='task' AND author=? AND body LIKE ? LIMIT 1",
                               (RUN_BY, prefix + "%")).fetchone())


def replace_text(path: Path, text: str, mode: int = 0o600) -> None:
    """Write path in one step through a new private temporary file beside it (0600, O_EXCL).
    A link planted at a temporary name is never followed (T750 F07). The finished file gets mode."""
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_text(path, json.dumps(state, indent=2, sort_keys=True) + "\n")


def short_words(text: str) -> str:
    return " ".join(text.split()[:40])


def evidence_text(summary: dict, items: list[dict]) -> str:
    lines = ["---", "type: receipt", 'workspace: ' + _fox_person.workspace('system'),
             f"timestamp: {summary['started_at']}", "agent: session-nightly", "tags: [nightly]",
             "---", "", "# Nightly session check", "", f"Date: {summary['date']}",
             f"Since: {summary['since']}", f"Scan end: {summary['scan_end']}",
             f"Sessions scanned: {summary['sessions']}",
             f"Settlements: {summary['settlements']}", f"Recorded: {summary['recorded']}",
             f"Flagged: {summary['flagged']}", f"Question drops: {len(summary['question_drops'])}",
             f"Jev cost USD: {summary['cost']}", "",
             "## Items", ""]
    for item in items:
        score = item.get("score")
        label = "Jev not run" if score is None else f"{score:.3f}"
        lines.append(f"- {item['session'][:13]} {item['local_time']} · {item['kind']} · "
                     f"{item['task']} · {label} · {'flag' if item['keep'] else 'drop'}"
                     f"{' (Jev unsure)' if item.get('unsure') else ''} · {short_words(item['text'])}")
    lines.extend(["", "## Pre-Jev drops", ""])
    for item in summary["question_drops"]:
        lines.append(f"- {item['session'][:13]} {item['timestamp']} · {item['reason']} · {short_words(item['text'])}")
    if not summary["question_drops"]:
        lines.append("- None")
    lines.extend(["", "## Failures", ""])
    lines.extend(f"- {failure}" for failure in summary["failures"])
    if not summary["failures"]:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def task_context(trackers: tuple[Path, ...]) -> tuple[set[str], list[tuple[str, str]]]:
    open_tasks, sessions = set(), []
    for tracker in trackers:
        with closing(readonly(tracker)) as db:
            open_tasks.update(row[0] for row in db.execute(
                "SELECT id FROM tasks WHERE lower(coalesce(status,'')) NOT IN ('done','accepted','canceled','cancelled','superseded')"))
            sessions.extend((row[0], row[1]) for row in db.execute(
                "SELECT subject_id,session FROM runs WHERE subject_type='task' AND session IS NOT NULL"))
    return open_tasks, sessions


def run_nightly(cfg: Config, *, jev_fn=jev_batch, work_fn=call_work) -> dict:
    now = cfg.now or datetime.now().astimezone()
    date = now.astimezone(hc.LOCAL_ZONE).date().isoformat()
    deadline = time.monotonic() + cfg.budget_seconds
    scan_end = now - timedelta(minutes=30)
    cutoff = scan_end - timedelta(hours=24)
    summary = {"date": date, "started_at": now.isoformat(), "scan_end": scan_end.isoformat(),
               "since": cutoff.isoformat(), "sessions": 0,
               "settlements": 0, "recorded": 0, "items": 0, "flagged": 0,
               "cost": "unknown", "failures": [], "candidates": [], "question_drops": [], "run": None}
    items = []
    try:
        prior = last_success(cfg.tracker)
        if cfg.since:
            cutoff = cfg.since
        elif prior:
            cutoff = max(scan_end - timedelta(days=7), prior)
        summary["since"] = cutoff.isoformat()
        if not cfg.dry_run:
            prior_run = existing_run(cfg.tracker, date)
            if prior_run and prior_run[1] is not None and not cfg.rerun:
                summary["run"] = prior_run[0]
                summary["already_ran"] = True
                if prior_run[1] != "pass":
                    summary["failures"].append("tonight's run already ended fail")
                return summary
            summary["run"] = (prior_run[0] if prior_run and prior_run[1] is None else
                              work_fn(cfg, "run-start", dream_task(), "--by", RUN_BY,
                                      "--model", "jev + handoff-check", "--runtime", "python",
                                      "--session", f"session-nightly-{date}",
                                      "--note", f"scan_end={scan_end.isoformat()}"))
        paths = recent_sessions(cfg, cutoff, deadline)
        summary["sessions"] = len(paths)
        trackers = tuple(path for path in (cfg.tracker, cfg.other_tracker) if path.is_file())
        rows = hc.row_bodies(trackers)
        valid_tasks, session_runs = task_context(trackers)
        for path in paths:
            if time.monotonic() >= deadline:
                raise TimeoutError("nightly check exceeded the time budget")
            data = hc.parse(path, scan_end)
            person_turns_only(data)
            # Turn scanning ends 30 minutes ago; later capture rows can still record those turns.
            report = hc.settlements_report(data, trackers, cutoff, rows=rows)
            summary["settlements"] += report["settlements"]
            summary["recorded"] += len(report["promoted"])
            run_tasks = {task for task, session in session_runs if data.session in session or session in data.session}
            items.extend(candidates_for(data, report, valid_tasks, rows, run_tasks,
                                        summary["question_drops"]))
        # Resumed transcripts can repeat one turn. The durable key is session plus turn time.
        items = list({item["key"]: item for item in items}.values())
        summary["question_drops"] = list({(item["session"], item["timestamp"]): item
                                          for item in summary["question_drops"]}.values())
        summary["items"] = len(items)
        scores, cost, jev_failure = jev_fn(cfg, items, deadline)
        summary["cost"] = round(cost, 6) if cost is not None else "unknown"
        if jev_failure:
            summary["failures"].append(jev_failure)
        state = json.loads(cfg.state_file.read_text()) if cfg.state_file.is_file() else {"flagged": {}}
        flagged = state.setdefault("flagged", {})
        for item in items:
            if time.monotonic() >= deadline:
                raise TimeoutError("nightly check exceeded the time budget")
            score = scores.get(item["key"])
            item["score"] = score
            item["keep"] = score is None or score >= 0.4
            item["unsure"] = score is not None and 0.4 <= score < 0.6
            if not item["keep"]:
                continue
            item["would_flag"] = item["key"] not in flagged and not already_flagged(cfg.tracker, item)
            if not cfg.dry_run and item["would_flag"]:
                score_text = "not run" if score is None else f"{score:.3f}"
                body = (f"unpromoted {_fox_person.display_name()} words, {item['session'][:13]} {item['local_time']}: "
                        f"{short_words(item['text'])} (Jev {score_text})"
                        f"{' Jev unsure' if item['unsure'] else ''}")
                work_fn(cfg, "comment", item["task"], body, "--flag", "--by", RUN_BY)
                flagged[item["key"]] = {"task": item["task"], "at": now.isoformat()}
                save_state(cfg.state_file, state)
            if item["would_flag"]:
                summary["flagged"] += 1
        if not cfg.dry_run:
            save_state(cfg.state_file, state)
        summary["candidates"] = [{key: item[key] for key in
                                  ("session", "timestamp", "kind", "task", "score", "keep", "would_flag", "text", "unsure")
                                  if key in item} for item in items]
    except Exception as error:
        summary["failures"].append(f"{type(error).__name__}: {str(error)[:200]}")
    if not cfg.dry_run:
        try:
            cfg.output_root.mkdir(parents=True, exist_ok=True)
            suffix = f"-{summary['run']}" if cfg.rerun and summary["run"] else ""
            evidence = cfg.output_root / f"{date}-session-check{suffix}.md"
            evidence.write_text(evidence_text(summary, items), encoding="utf-8")
            relative = evidence.relative_to(cfg.receipt_root).as_posix()
            if summary["run"] is None:
                summary["run"] = work_fn(cfg, "run-start", dream_task(), "--by", RUN_BY,
                                         "--model", "jev + handoff-check", "--runtime", "python",
                                         "--session", f"session-nightly-{date}",
                                         "--note", f"scan_end={scan_end.isoformat()}")
            work_fn(cfg, "run-end", summary["run"], "--result",
                    "fail" if summary["failures"] else "pass", "--evidence", relative)
        except Exception as error:
            summary["failures"].append(f"receipt: {type(error).__name__}: {str(error)[:200]}")
        if summary["failures"]:
            bug_id = "B-session-nightly-" + date.replace("-", "")
            try:
                with closing(readonly(cfg.tracker)) as db:
                    exists = db.execute("SELECT 1 FROM bugs WHERE id=?", (bug_id,)).fetchone()
                if not exists:
                    work_fn(cfg, "bug-open", "--id", bug_id, "--title", "Nightly session check failed",
                            "--description", "; ".join(summary["failures"])[:500],
                            "--capability", "session-nightly", "--by", RUN_BY, *bug_fields(
                                "The nightly session check failed, so last night's sessions are not checked.",
                                "a nightly session check fails", "the failure named and fixed",
                                "the next night's check passes", "; ".join(summary["failures"])[:500],
                                str(cfg.receipt_root)))
            except Exception as error:
                summary["failures"].append(f"bug row: {type(error).__name__}: {str(error)[:200]}")
    return summary


# ---------------------------------------------------------------- the code half and the report

STEP_SECONDS = 15 * 60
DAY_ROWS = 25   # rows in one table of a day page; the rest is one line
BUG_BY = "dream"
BUG_ROWS_A_CALL = 50   # new bug rows in one call; a finding over the limit is filed by a later call


def run_command(home: Path, *arguments: str, runner=subprocess.run) -> tuple[int, str, str]:
    """Run one installed command in the home. Returns (exit code, all it printed to stdout, its last line)."""
    script = home / arguments[0]
    if not script.is_file() or script.is_symlink():
        raise FileNotFoundError("the command is not installed: " + arguments[0])
    environment = dict(os.environ, FOXRUN_HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    done = runner([sys.executable, "-B", str(script), *arguments[1:]], cwd=str(home), env=environment,
                  text=True, capture_output=True, timeout=STEP_SECONDS)
    lines = (done.stderr or done.stdout or "").strip().splitlines()
    return done.returncode, done.stdout or "", (lines[-1][:200] if lines else "exit " + str(done.returncode))


def command(home: Path, *arguments: str) -> tuple[bool, str]:
    """For a command where only pass or fail matters: (exit code was 0, its last line)."""
    code, _, last = run_command(home, *arguments)
    return code == 0, last


def step_state(home: Path, now: datetime) -> tuple[str, str]:
    ok, last = command(home, "memory/state.py", "build", "--all")
    return ("pass" if ok else "fail"), last


def step_index(home: Path, now: datetime) -> tuple[str, str]:
    """index.md in each workspace and at the top of the portfolio, in the shape of base/templates/index.md (T697)."""
    ok, last = command(home, "base/page_indexes.py", "--portfolio", str(_fox_paths.portfolio()), "--system-home", str(home),
                       "--as-of", now.strftime("%Y-%m-%d"), "--kind", "index")
    return ("pass" if ok else "fail"), last


def day_of(value) -> str | None:
    moment, _ = pages.parse_when(value)
    return moment.astimezone().strftime("%Y-%m-%d") if moment is not None else None


def day_rows(database: Path, workspace: str, own: bool, first: str) -> dict:
    """The event rows of one workspace from one day on, each with its local day."""
    rows = {"changes": [], "comments": [], "runs": [], "tasks": [], "decisions": []}
    if not database.is_file():
        return rows
    default = pages.default_workspace()
    with pages.closing(pages.readonly(database)) as db:
        if not pages.has(db, "tasks"):
            return rows
        tags = "tags" if "tags" in pages.columns(db, "tasks") else "NULL"
        tasks = {row["id"]: dict(row) for row in db.execute("SELECT id,title,created_on,parent," + tags + " AS tags FROM tasks")}
        mine = {key for key, row in tasks.items() if own or pages.in_workspace(row, workspace, default)}
        rows["tasks"] = [(day_of(tasks[key]["created_on"]), key, tasks[key]["title"]) for key in mine
                         if tasks[key]["parent"] is None and (tasks[key]["created_on"] or "")[:10] >= first]
        if pages.has(db, "activity"):
            wanted = "old_value" if "old_value" in pages.columns(db, "activity") else "NULL"
            rows["changes"] = [(day_of(row[4]), row[0], (tasks.get(row[0]) or {}).get("title"), row[1], row[2], row[3])
                               for row in db.execute(
                                   "SELECT subject_id,field," + wanted + ",new_value,at FROM activity WHERE subject_type='task' "
                                   "AND substr(coalesce(at,''),1,10)>=? ORDER BY id", (first,)) if row[0] in mine]
        if pages.has(db, "comments"):
            rows["comments"] = [(day_of(row[1]), row[0]) for row in db.execute(
                "SELECT subject_id,at FROM comments WHERE subject_type='task' AND substr(coalesce(at,''),1,10)>=?", (first,))
                if row[0] in mine]
        owners = {} if own else pages.owners_of(db, default)
        if pages.has(db, "runs"):
            names = pages.columns(db, "runs")
            pick = ",".join(('"by"' if name == "by" else name) if name in names else "NULL"
                            for name in ("id", "subject_id", "by", "result", "started_at", "subject_type"))
            # A run on a task counts for the workspace of that task. A run that names no task counts for the default workspace.
            rows["runs"] = [(day_of(row[4]), row[0], row[1], row[2], row[3]) for row in db.execute(
                "SELECT " + pick + " FROM runs WHERE substr(coalesce(started_at,''),1,10)>=? ORDER BY started_at", (first,))
                if own or pages.belongs(row[5], row[1], owners, workspace, default)]
        if pages.has(db, "decisions"):
            tags = "tags" if "tags" in pages.columns(db, "decisions") else "NULL"
            rows["decisions"] = [(day_of(row[2]), row[0], row[1]) for row in db.execute(
                "SELECT name,status,decided_on," + tags + " FROM decisions WHERE substr(coalesce(decided_on,''),1,10)>=?", (first,))
                if own or pages.in_workspace({"tags": row[3]}, workspace, default)]
    return rows


def day_page(workspace: str, day: str, rows: dict, now: datetime, folder: Path, database: Path) -> str | None:
    """The page of one day, or None when no event row has that day. Week and month counts come from the same rows."""
    labels = (("Task changes", "changes"), ("Comments", "comments"), ("Runs", "runs"), ("New tasks", "tasks"), ("Decisions", "decisions"))
    today = [sum(1 for row in rows[key] if row[0] == day) for _, key in labels]
    if not any(today):
        return None
    limit = datetime.strptime(day, "%Y-%m-%d")

    def within(key, days):
        first = (limit - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        return sum(1 for row in rows[key] if row[0] is not None and first <= row[0] <= day)
    lines = ["---", "type: daily", "workspace: " + workspace, "timestamp: " + now.replace(microsecond=0).isoformat(), "---",
             "# Day: " + day, "",
             "Code made this page from the event rows of this day in " + pages.page_link(folder, database, "data.db") +
             ". It is frozen. Change a row, not this page.", ""]
    lines += pages.count_block([(label.upper(), count) for (label, _), count in zip(labels, today)] +
                               [("MADE", now.strftime("%Y-%m-%d %H:%M"))])
    lines += ["", "## Counts", "", "| Count | This day | 7 days | 30 days |", "|---|---|---|---|"]
    lines += ["| " + label + " | " + str(count) + " | " + str(within(key, 7)) + " | " + str(within(key, 30)) + " |"
              for (label, key), count in zip(labels, today)]
    status = [row for row in rows["changes"] if row[0] == day and row[3] == "status"]
    if status:
        lines += ["", "## Status changes", "", "| Task | Title | From | To |", "|---|---|---|---|"]
        lines += ["| " + str(row[1]) + " | " + pages.clean(row[2], 60) + " | " + pages.clean(row[4] or "—", 20) + " | " + pages.clean(row[5], 20) + " |"
                  for row in status[:DAY_ROWS]]
        if len(status) > DAY_ROWS:
            lines += ["", str(len(status) - DAY_ROWS) + " more status changes are in the rows."]
    runs = [row for row in rows["runs"] if row[0] == day]
    if runs:
        lines += ["", "## Runs", "", "| Run | Task | By | Result |", "|---|---|---|---|"]
        lines += ["| " + pages.clean(row[1], 40) + " | " + pages.clean(row[2] or "—", 12) + " | " + pages.clean(row[3] or "—", 24) + " | " +
                  pages.clean(row[4] or "not ended", 30) + " |" for row in runs[:DAY_ROWS]]
        if len(runs) > DAY_ROWS:
            lines += ["", str(len(runs) - DAY_ROWS) + " more runs are in the rows."]
    made = [row for row in rows["tasks"] if row[0] == day]
    if made:
        lines += ["", "## New tasks", "", "| Task | Title |", "|---|---|"]
        lines += ["| " + row[1] + " | " + pages.clean(row[2], 70) + " |" for row in made[:DAY_ROWS]]
        if len(made) > DAY_ROWS:
            lines += ["", str(len(made) - DAY_ROWS) + " more new tasks are in the rows."]
    ruled = [row for row in rows["decisions"] if row[0] == day]
    if ruled:
        lines += ["", "## Decisions", "", "| Decision | Status |", "|---|---|"]
        lines += ["| " + pages.clean(row[1], 70) + " | " + pages.clean(row[2], 12) + " |" for row in ruled[:DAY_ROWS]]
        if len(ruled) > DAY_ROWS:
            lines += ["", str(len(ruled) - DAY_ROWS) + " more decisions are in the rows."]
    return "\n".join(lines) + "\n"


def step_daily(home: Path, now: datetime) -> tuple[str, str]:
    """Write history/daily/<day>.md in each workspace for the last full day. A page that exists is frozen and is kept."""
    day = (now.astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")
    first = (now.astimezone() - timedelta(days=32)).strftime("%Y-%m-%d")
    written, kept, empty = [], 0, 0
    for workspace in pages.workspaces():
        folder = _fox_paths.portfolio() / workspace
        target = folder / "history/daily" / (day + ".md")
        if target.exists():
            kept += 1
            continue
        database = pages.tracker(workspace)
        text = day_page(workspace, day, day_rows(database, workspace, database.parent != home, first), now, target.parent, database)
        if text is None:
            empty += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        replace_text(target, text, 0o644)
        written.append(workspace)
    return "pass", f"day {day}: {len(written)} written ({', '.join(written) or 'none'}), {kept} kept, {empty} with no event row"


def step_backup(home: Path, now: datetime) -> tuple[str, str]:
    """The system database into state/, then each workspace that has its own database into backups/jsonl/<workspace>/."""
    targets = [(home / "data.db", home / "state")]
    targets += [(_fox_paths.portfolio() / name / "data.db", home / "backups/jsonl" / name) for name in pages.workspaces()
                if (_fox_paths.portfolio() / name / "data.db").is_file()]
    failed = []
    for database, folder in targets:
        ok, last = command(home, "base/backup.py", "run", str(database), "--output-dir", str(folder))
        if not ok:
            failed.append(database.parent.name + ": " + last)
    return ("fail" if failed else "pass"), ("; ".join(failed) if failed else str(len(targets)) + " databases written (system to state, workspaces to backups/jsonl)")


def direct_writes(database: Path) -> list[str]:
    """Tasks whose status is not the status of their newest status change: a write that left no activity row."""
    if not database.is_file():
        return []
    with pages.closing(pages.readonly(database)) as db:
        if not pages.has(db, "tasks") or not pages.has(db, "activity"):
            return []
        return [row[0] for row in db.execute(
            "SELECT t.id FROM tasks t WHERE EXISTS (SELECT 1 FROM activity a WHERE a.subject_type='task' AND a.subject_id=t.id AND a.field='status') "
            "AND t.status != (SELECT a.new_value FROM activity a WHERE a.subject_type='task' AND a.subject_id=t.id AND a.field='status' "
            "ORDER BY a.id DESC LIMIT 1) ORDER BY t.id")]


def finding_text(item) -> str:
    """One finding as one line. The two checkers give a map for each finding."""
    if isinstance(item, dict):
        if {"category", "subject", "detail"} <= set(item):
            return f"{item['category']}: {item.get('file', '')}:{item.get('line', '')}: {item['subject']}: {item['detail']}"
        if {"id", "statement"} <= set(item):
            return f"{item['id']} [{item.get('status', '')}] {item.get('word', '')}: {item['statement']}"
        return json.dumps(item, sort_keys=True, ensure_ascii=False)
    return str(item)


def checker_findings(home: Path, *arguments: str) -> list[str]:
    """Every finding of one checker, read from its --json list. No line is dropped.

    Exit 0 with an empty list means no finding. Exit 1 with a list means findings.
    Anything else means the check did not run: the caller reports it and files nothing for it.
    """
    code, printed, last = run_command(home, *arguments, "--json")
    if code not in (0, 1):
        raise RuntimeError("exit " + str(code) + ": " + last)
    try:
        found = json.loads(printed)
    except ValueError:
        raise RuntimeError("it did not print a JSON list of findings")
    if not isinstance(found, list) or (code == 1) != bool(found):
        raise RuntimeError("exit " + str(code) + " does not fit what it printed")
    return [finding_text(item) for item in found]


def step_checks(home: Path, now: datetime) -> tuple[str, str]:
    """Run each check. Each finding becomes one bug row. A check that cannot run fails the step. Nothing is fixed.

    The id of a bug row comes from the check and the text of the finding, so the same finding
    is one row, however many nights it is found.
    """
    receipt_root = _fox_paths.portfolio() / _fox_person.workspace("system")
    findings, could_not = [], []
    checks = (("blueprints", ("base/check_blueprints.py",)),
              ("replaces", ("decisions/lint_replaces.py", "--db", str(home / "data.db"), "--receipt-root", str(receipt_root))))
    for name, arguments in checks:
        try:
            findings += [(name, text) for text in checker_findings(home, *arguments)]
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            could_not.append(name + ": " + str(error)[:160])
    databases = [("system", home / "data.db")] + [(name, _fox_paths.portfolio() / name / "data.db") for name in pages.workspaces()
                                                    if (_fox_paths.portfolio() / name / "data.db").is_file()]
    for name, database in databases:
        try:
            findings += [("direct-write-" + name, "task " + task + " in the " + name + " database has a status with no activity row")
                         for task in direct_writes(database)]
        except sqlite3.Error as error:
            could_not.append("direct-write-" + name + ": " + str(error)[:160])
    filed, known, over = 0, 0, 0
    for name, text in findings:
        bug_id = "B-dream-" + name + "-" + hashlib.sha256((name + "|" + text).encode("utf-8")).hexdigest()[:10]
        try:
            with closing(pages.readonly(home / "data.db")) as db:
                exists = pages.has(db, "bugs") and db.execute("SELECT 1 FROM bugs WHERE id=?", (bug_id,)).fetchone()
            if exists:
                known += 1
            elif filed >= BUG_ROWS_A_CALL:
                over += 1
            else:
                ok, last = command(home, "work/work.py", "--db", str(home / "data.db"), "--receipt-root", str(receipt_root),
                                   "bug-open", "--id", bug_id, "--title", ("Dream check " + name + ": " + text)[:120],
                                   "--description", text[:500], "--capability", "dream", "--by", BUG_BY, *bug_fields(
                                       "A dream check found a defect: " + text[:300], "a dream check finds " + name,
                                       "the defect fixed at its source", "the check passes again", text[:500],
                                       str(receipt_root)))
                if not ok:
                    raise RuntimeError(last)
                filed += 1
        except (OSError, RuntimeError, sqlite3.Error, subprocess.TimeoutExpired) as error:
            could_not.append("bug row " + bug_id + ": " + str(error)[:120])
    detail = (f"{len(checks) + len(databases)} checks, {len(findings)} findings, {filed} new bug rows, {known} filed before" +
              (f", {over} not filed in this call (the limit is {BUG_ROWS_A_CALL})" if over else ""))
    if findings:
        detail += ": " + "; ".join(name + " (" + text[:70] + ")" for name, text in findings[:6]) + \
            ("; and " + str(len(findings) - 6) + " more" if len(findings) > 6 else "")
    if could_not:
        return "fail", detail + ". Could not: " + "; ".join(could_not)
    return "pass", detail


def step_kept(home, now):
    from memory.kept import link_all
    linked, inbox = link_all(now)
    return 'pass', '{} topic links, {} inbox rows'.format(linked, inbox)


# Each step is one fixed piece of work. The order is the order of the night.
CODE_STEPS = (
    ("kept", "Link frozen kept replies into topics; send replies without topics to inbox", step_kept),
    ("state", "Build STATE.md in the system home and in each workspace", step_state),
    ("index", "Build index.md in each workspace and at the top of the portfolio, in the shape of its template", step_index),
    ("daily", "Write the page of the last full day in each workspace, with day, week, and month counts", step_daily),
    ("backup", "Write the tables of the system database into state, and of each workspace database into backups/jsonl", step_backup),
    ("checks", "Run the checks. Each finding becomes one bug row. Nothing is fixed", step_checks),
)
# Named in the night design and not a step yet. The report prints this list, so nothing is hidden.
LATER = (
    ("draft wiki pages", "memory/compile.py takes named sources and writes pages with no draft status; "
                         "no list of sources is in the database the tools read (memory_sources is not built)"),
    ("direct-write check for other tables", "only tasks keep a status row in activity; the other tables have no change row to compare with"),
)


def new_run_folder(home: Path, date: str) -> Path:
    """A folder of its own for each call: nightly/<date>-dream, then <date>-dream-2, and so on (T755).
    No call writes into an older one, and a number taken at the top of runs/ before the move stays taken."""
    parent = home / "runs" / "nightly"
    parent.mkdir(parents=True, exist_ok=True)
    folder, number = parent / (date + "-dream"), 1
    while True:
        try:
            if (home / "runs" / folder.name).exists():
                raise FileExistsError(folder.name)
            folder.mkdir()      # only one caller can make this folder
            return folder
        except FileExistsError:
            number += 1
            folder = parent / (date + "-dream-" + str(number))


class NightBusy(RuntimeError):
    """Another memory job holds this home, or left its lock behind. Exit code 3."""


class NightLock:
    """One memory job at a time in one home: the file runs/.dream.lock, made so that only one caller can make it.

    A lock that is there is never removed here. The caller stops at once and says who holds it.
    """

    def __init__(self, home: Path):
        self.file, self.held = home / "runs" / ".dream.lock", False

    def __enter__(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(str(self.file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise NightBusy(self.who())
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({"pid": os.getpid(), "at": datetime.now().astimezone().isoformat(timespec="seconds")}) + "\n")
        self.held = True
        return self

    def __exit__(self, *error):
        if self.held:
            try:
                os.unlink(str(self.file))
            except OSError:
                pass
        return False

    def who(self) -> str:
        try:
            owner = json.loads(self.file.read_text(encoding="utf-8"))
            pid, since = int(owner["pid"]), owner.get("at", "an unknown time")
            os.kill(pid, 0)
        except ProcessLookupError:
            return (f"the memory job has a stale lock: process {pid} made it at {since} and is gone. Nothing was changed, "
                    f"and the lock was not removed. Read the newest dream folder in runs/, then remove {self.file} by hand")
        except (OSError, ValueError, KeyError, TypeError):
            return f"the memory job is locked and its lock can not be checked: {self.file}. Nothing was changed"
        return f"another memory job runs in this home now (process {pid}, since {since}). Nothing was changed"


def code_half(home: Path, folder: Path | None, dry_run: bool = False, steps=None, now: datetime | None = None) -> list[dict]:
    """Run each step in order. A failed step does not stop the next one."""
    now = now or datetime.now().astimezone()
    results = []
    for name, purpose, work in (steps or CODE_STEPS):
        row = {"half": "code", "step": name, "purpose": purpose, "started_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        began = time.monotonic()
        if dry_run:
            row.update(result="not run", detail="dry run")
        else:
            try:
                result, detail = work(home, now)
                row.update(result=result, detail=detail)
            except Exception as error:
                row.update(result="fail", detail=(str(error) if isinstance(error, FileNotFoundError) else type(error).__name__ + ": " + str(error))[:200])
        row["seconds"] = round(time.monotonic() - began, 1)
        results.append(row)
        if folder is not None:
            with (folder / "steps.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
    return results


def report_text(date: str, word: str, folder: Path, home: Path, steps: list[dict], model: dict) -> str:
    """model: {'state': 'ran'|'failed'|'skipped'|'not asked', 'line': one sentence, 'failures': [...]}."""
    passed = sum(1 for step in steps if step["result"] == "pass")
    failures = [step["step"] + ": " + step["detail"] for step in steps if step["result"] == "fail"]
    failures += list(model.get("failures", []))
    made = datetime.now().astimezone()
    lines = ["---", "type: output", "workspace: system", "timestamp: " + made.isoformat(timespec="seconds"), "---",
             "# Dream report: " + date, "",
             "The memory job wrote this page. It shows what this call ran and what failed.", "",
             "```",
             "WORD         " + word,
             "CODE HALF    " + str(passed) + " of " + str(len(steps)) + " steps passed",
             "MODEL HALF   " + model["state"],
             "FAILURES     " + str(len(failures)),
             "MADE         " + made.strftime("%Y-%m-%d %H:%M"),
             "```", "", "## Code half", "", "| Step | Result | Seconds | What it found |", "|---|---|---|---|"]
    lines += ["| " + step["step"] + " | " + step["result"] + " | " + str(step["seconds"]) + " | " +
              str(step["detail"]).replace("|", "/") + " |" for step in steps]
    lines += ["", "## Model half", "", model["line"], "", "## Failures", ""]
    lines += ["- " + failure for failure in failures] or ["- None"]
    lines += ["", "## Not a step yet", ""]
    lines += ["- " + name + ": " + why + "." for name, why in LATER]
    lines += ["", "Run folder: `" + os.path.relpath(str(folder), str(home)) + "`"]
    return "\n".join(lines) + "\n"


def last_report(home: Path) -> Path | None:
    """The report of the newest whole night (the word run). With none, the newest report of any call."""
    def number(folder: Path) -> tuple:
        date, _, rest = folder.name.partition("-dream")
        return date, int(rest[1:]) if rest[1:].isdigit() else 1
    from memory.runs import nightly_folders
    folders = sorted((p for p in nightly_folders(home, "*-dream*") if (p / "report.md").is_file()), key=number, reverse=True)
    for folder in folders:
        try:
            if json.loads((folder / "manifest.json").read_text(encoding="utf-8")).get("word") == "run":
                return folder / "report.md"
        except (OSError, ValueError):
            continue
    return folders[0] / "report.md" if folders else None


def night(args, home: Path) -> int:
    """run and code: the code half, then the model half when it is asked for and a runner is set."""
    date = datetime.now().astimezone(hc.LOCAL_ZONE).date().isoformat()
    folder = None
    if not args.dry_run:
        folder = new_run_folder(home, date)
        (folder / "manifest.json").write_text(json.dumps({
            "job": "dream", "word": args.command, "date": date, "home": str(home),
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "code_steps": [step[0] for step in CODE_STEPS], "later": [name for name, _ in LATER]},
            indent=2, sort_keys=True) + "\n", encoding="utf-8")
    steps = code_half(home, folder, args.dry_run)
    for step in steps:
        print("code " + step["step"] + ": " + step["result"] + " (" + str(step["detail"]) + ")")
    model = {"state": "not asked", "line": "The word `code` runs the code half only.", "failures": []}
    if args.command == "run":
        from memory.model_proposals import model_half
        model = model_half(home, date, steps, dry_run=args.dry_run)
        print("model half: " + model["state"] + "; " + model["line"])
    if folder is not None:
        (folder / "report.md").write_text(report_text(date, args.command, folder, home, steps, model), encoding="utf-8")
        print("report: " + str(folder / "report.md"))
    if args.json:
        print(json.dumps({"code_half": steps, "model_half": model}, indent=2))
    failed = any(step["result"] == "fail" for step in steps) or bool(model["failures"])
    if folder is not None:
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        manifest.update(finished_at=datetime.now().astimezone().isoformat(timespec='seconds'),
                        result='fail' if failed else 'pass', model=model['state'],
                        code_half={'state': 'fail' if any(step['result']=='fail' for step in steps) else 'pass',
                                   'steps': [{'step': step['step'], 'result': step['result']} for step in steps]},
                        model_half=model)
        pages.write_once(folder / 'manifest.json', json.dumps(manifest, indent=2) + '\n')
        # The check owns health.json. Calling it here also covers a manual dream run.
        from memory.health import check_health
        check_health()
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', nargs='?', choices=('run', 'code', 'report'), default='run',
                        help='run: the whole night. code: the code half only. report: show the report of the last whole night.')
    parser.add_argument("--dry-run", action="store_true",
                        help="list the steps and configured model; run neither half and write nothing")
    parser.add_argument("--rerun", action="store_true", help="start another model run on the same local day")
    parser.add_argument("--since", type=parse_time, help="earliest session time, with UTC offset")
    parser.add_argument("--json", action="store_true", help="print the machine-readable summary of the model half")
    args = parser.parse_args(argv)
    home = _fox_paths.system_home()
    if args.command == 'report':
        report = last_report(home)
        if report is None:
            print("No dream report yet. Run: python3 memory/dream.py run", file=sys.stderr)
            return 1
        sys.stdout.write(report.read_text(encoding="utf-8"))
        return 0
    if args.dry_run:
        return night(args, home)        # a dry run reads only: it takes no lock and makes no folder
    try:
        with NightLock(home):
            return night(args, home)
    except NightBusy as error:
        print("FAIL dream " + args.command + ": " + str(error), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
