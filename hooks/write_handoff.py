#!/usr/bin/env python3
"""Write a handoff when a runtime is about to compact a session (PreCompact hook).

Reads the hook JSON on stdin (session_id, transcript_path, cwd, trigger; Codex
also sends turn_id and model). Runs the read-only settlement check:

  python3 <system-home>/memory/handoff_check.py \
      --transcript <path> --settlements [--since <last handoff time>] [--db <tracker>]

over this session's transcript since its newest handoff (else since the start).
If a settlement turn by the person (the `name` in config/person.json) has no row
(decision, approval, or comment with his
words), the handoff lists it under `## Unpromoted` with its time and words, and
the script prints one warning line. Otherwise it writes the normal handoff by
the ruled shape. The path always comes from `handoff-path`.

Output: dirty -> stdout `{"systemMessage": "<warning>"}` (Codex shows it to the
user; Claude discards a PreCompact systemMessage, so in Claude the warning
reaches the session through the SessionStart `compact` hook, handoff-boot,
which prints this handoff). Clean -> empty stdout. Notes go to stderr.
Exit 0 always: a hook must never block a compaction. It never writes a
tracker row.
"""

import argparse
from datetime import datetime
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
os.environ.setdefault('FOXRUN_HOME', str(ROOT))
from base import paths, person
from base.tracker import local_path, tracker
BIN = paths.system_home() / 'skills/handoff/bin'
DEFAULT_CHECK = str(paths.system_home() / 'memory/handoff_check.py')
CHECK_TIMEOUT = 45
FALLBACK_WORKSPACE = "agent-os"
CLOSED = {"done", "accepted", "canceled"}
SUBJECT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
CREATED = re.compile(r"(?m)^\s*(T\d+)\s*$")
CREATE_COMMAND = re.compile(r"\b(?:work\.py|W)\s+create\b")


def load_boot():
    """Reuse handoff-boot's stdin, frontmatter, handoff listing, and seat logic."""
    sys.dont_write_bytecode = True  # never leave a __pycache__ in the published skill folder
    loader = SourceFileLoader("handoff_boot", str(BIN / "handoff-boot"))
    module = module_from_spec(spec_from_loader("handoff_boot", loader))
    loader.exec_module(module)
    return module


class QuietParser(argparse.ArgumentParser):
    """Bad flags print one line and exit 0, so the hook never blocks compaction."""

    def error(self, message):
        print(f"handoff-precompact: {message}", file=sys.stderr)
        sys.exit(0)


def build_parser():
    parser = QuietParser(
        prog="handoff-precompact",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="print what it would write; write nothing")
    parser.add_argument("--json", action="store_true", help="print a JSON report on stdout instead of the hook output")
    parser.add_argument("--seat", help="seat name; default: env FOXRUN_SEAT, then the seat of this session's newest handoff")
    parser.add_argument("--workspace", help="vault workspace folder name; default: from cwd")
    parser.add_argument("--cwd", help="working folder; default: stdin cwd, then the process folder")
    parser.add_argument("--vault", default=str(paths.portfolio()), help="portfolio root")
    parser.add_argument("--session", help="session id; default: stdin session_id")
    parser.add_argument("--transcript", help="transcript file; default: stdin transcript_path")
    parser.add_argument("--trigger", help="manual or auto; default: stdin trigger")
    parser.add_argument("--check", help=f"handoff_check.py path; default: env FOXRUN_HANDOFF_CHECK, then {DEFAULT_CHECK}")
    parser.add_argument("--db", action="append", help="tracker for the row lookup (repeatable); default: the check's own trackers")
    return parser


def export_metadata(database, vault):
    """Read the selected database's export, independent of the handoff folder."""
    tasks_export = Path(database).resolve().parent / "state" / "tasks.jsonl"
    if not tasks_export.is_file():
        return None
    folder = tasks_export.parent
    shown = folder.relative_to(vault) if folder.is_relative_to(vault) else folder
    stamp = datetime.fromtimestamp(tasks_export.stat().st_mtime).astimezone()
    return (str(shown) + "/", stamp.isoformat(timespec="seconds"))


def warn(text):
    print(f"handoff-precompact: {text}", file=sys.stderr)


def expand(value):
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def parse_time(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.astimezone()


def resolve_workspace(args, hook, vault):
    """Return (workspace name, reason). None when the session is outside the vault."""
    if args.workspace:
        return args.workspace.strip("/"), "flag"
    cwd = expand(args.cwd or hook.get("cwd") or os.getcwd())
    for base, root in ((cwd, vault), (cwd.resolve(), vault.resolve())):
        try:
            relative = base.relative_to(root)
        except ValueError:
            continue
        if relative.parts and (vault / relative.parts[0]).is_dir():
            return relative.parts[0], "cwd"
        return person.workspace(), "portfolio root: configured workspace"
    return None, f"cwd {cwd} is outside the vault"


def last_handoff(boot, folder, session):
    """Newest handoff in the folder whose frontmatter session equals this session."""
    if not session:
        return None, None
    for path, _subject in boot.handoffs_in([folder]):
        fields = boot.frontmatter(path)
        if fields.get("session") == session:
            since = parse_time(fields.get("timestamp"))
            if since is None:
                since = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
            return path, since
    return None, None


def created_task_ids(transcript):
    """Find task ids returned by work.py create calls in this session's transcript."""
    ids, calls = set(), set()
    if not transcript or not Path(transcript).is_file():
        return ids
    with Path(transcript).open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            message = row.get("message") or {}
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    args = block.get("input") or {}
                    command = args.get("command") or args.get("cmd") or "" if isinstance(args, dict) else ""
                    if isinstance(command, str) and CREATE_COMMAND.search(command):
                        calls.add(block.get("id"))
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                    output = block.get("content") or ""
                    if isinstance(output, str):
                        ids.update(CREATED.findall(output))
    return ids


def run_check(check, transcript, session, since, dbs):
    """Run the read-only settlement check. Return (report or None, command, error or None)."""
    command = [sys.executable, str(check)]
    if transcript:
        command += ["--transcript", str(transcript)]
    else:
        command += ["--session", str(session)]
    command.append("--settlements")
    if since is not None:
        command += ["--since", since.isoformat()]
    for db in dbs or []:
        command += ["--db", str(expand(db))]
    if not check.is_file():
        return None, command, f"check not found: {check}"
    try:
        done = subprocess.run(command, text=True, capture_output=True, timeout=CHECK_TIMEOUT,
                              stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, command, f"check did not run: {error.__class__.__name__}"
    try:
        report = json.loads(done.stdout)
    except ValueError:
        last = (done.stderr.strip().splitlines() or [f"exit {done.returncode}, no JSON"])[-1]
        return None, command, f"check failed: {last[:200]}"
    return (report, command, None) if isinstance(report, dict) else (None, command, "check printed no JSON object")


def tracker_rows(db, ids):
    """Read-only: statuses for the touched ids and the needs_me view."""
    statuses, needs = {}, []
    if not db.is_file():
        return statuses, needs, f"tracker not found: {db}"
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            task_ids = sorted(x for x in ids if x[:1] in "TP" or x.startswith("WS"))
            if task_ids:
                marks = ",".join("?" for _ in task_ids)
                for row in conn.execute(f"SELECT id, title, status FROM tasks WHERE id IN ({marks})", task_ids):
                    statuses[row[0]] = (row[1], row[2])
            try:
                needs = conn.execute("SELECT id, title, status FROM needs_me LIMIT 15").fetchall()
            except sqlite3.Error:
                needs = []
    except sqlite3.Error as error:
        return statuses, needs, f"tracker read failed: {error}"
    return statuses, needs, None


def short(text, limit=160):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def person_name():
    """The person's name from config/person.json, the way work.py reads it; else "the person"."""
    try:
        return person.display_name()
    except (person.PersonError, OSError, ValueError):
        return "the person"


def warning_line(count, where):
    noun = "settlement" if count == 1 else "settlements"
    verb = "has" if count == 1 else "have"
    return (f"Pre-compaction check: {count} {noun} by {person_name()} {verb} no row (decision, approval, or comment). "
            f"Listed under Unpromoted in {where}. Promote them before anything else.")


def render(ctx):
    """The handoff text: frontmatter, top lines, optional Unpromoted, then the seven sections."""
    now, ws, db = ctx["now"], ctx["workspace"], ctx["db"]
    report, unpromoted = ctx["report"], ctx["unpromoted"]
    who = person_name()
    front = ["---", "type: handoff", f"workspace: {ws}", f"timestamp: {now.isoformat(timespec='seconds')}",
             f"session: {ctx['session'] or 'unknown'}", f"agent: {ctx['agent']}"]
    if ctx["seat"]:
        front.append(f"seat: {ctx['seat']}")
    front.append("tags: [precompact]")
    if ctx["supersedes"]:
        front.append(f"supersedes: {ctx['supersedes']}")
    front.append("---")

    title = f"# {ctx['seat'] or 'Session'}: pre-compaction handoff"
    lines = [*front, "", title, "",
             f"Written by the pre-compaction hook (trigger: {ctx['trigger'] or 'unknown'}) at "
             f"{now.strftime('%Y-%m-%d %H:%M:%S %Z')}. Mechanical note: rows win over it."]
    if unpromoted:
        lines += ["", f"**{ctx['warning']}**"]
    if ctx["lead_handoff"]:
        lines += ["", f"Lead handoff: `{ctx['lead_handoff']}`."]
    if unpromoted:
        lines += ["", "## Unpromoted", "",
                  f"{who[:1].upper() + who[1:]} settled these in chat and no row holds his words. Promote each one first "
                  "(decision, approval, or comment with his words), then continue.", ""]
        for item in unpromoted:
            lines.append(f"- {item.get('local_time', 'unknown time')} (U{int(item.get('index', 0)):03d}): "
                         f"“{short(item.get('text', ''))}”")

    ids = ctx["open_ids"]
    id_list = ", ".join(f"'{x}'" for x in ids) if ids else "''"
    lines += ["", "## Boot Order", "",
              f"0. Boot Foxrun: `python3 ~/.foxrun/foxrun.py start --workspace {ws} --seat {ctx['seat'] or '<seat>'}`",
              f"1. Recheck first: task status and approvals may have changed since {now.isoformat(timespec='seconds')}.",
              f"   `sqlite3 -readonly {db} \"select * from needs_me\"`",
              f"   `sqlite3 -readonly {db} \"select id, subject_id, call, given_at from approvals order by given_at desc limit 10\"`",
              f"2. Open tasks from this session: `sqlite3 -readonly {db} \"select id, title, status from tasks where id in ({id_list}) and status not in ('done','accepted','canceled')\"`",
              f"   Latest decisions: `sqlite3 -readonly {db} \"select id, name, status, decided_on from decisions order by decided_on desc limit 10\"`",
              f"3. Contracts, in order: `{ws}/AGENTS.md`"
              + (f", then the hand-written handoff `{ctx['lead_handoff']}`" if ctx["lead_handoff"] else "")
              + "".join(f", then `{note}`" for note in ctx["earlier_notes"])
              + ", then this note."]
    if unpromoted:
        lines.append("4. Next action: promote each Unpromoted item into a row. The hook does not choose task work.")
    else:
        lines.append("4. Next action: the hook does not choose one. Take it from the open task rows in step 2"
                     + (f" or from `{ctx['previous']}`." if ctx["previous"] else "."))
    if ctx["agent_runtime"] == "codex":
        lines.append(f"5. Reboot prompt: `Read {ctx['path_hint']}. Run its Boot Order step 0, then step 1, then continue.`")

    lines += ["", "## State", "",
              f"- Session `{ctx['session'] or 'unknown'}`; transcript `{ctx['transcript'] or 'looked up by session'}`.",
              f"- Check window: since {ctx['since'].isoformat(timespec='seconds') if ctx['since'] else 'session start'}"
              + (f" (newest handoff of this session: `{ctx['previous']}`)." if ctx["previous"] else ".")]
    if report is not None:
        lines.append(f"- Settlement turns in the window: {report.get('settlements', 0)} of {report.get('turns', 0)} "
                     f"turns by {who}; with a row: {len(report.get('promoted', []))}; without a row: {len(unpromoted)}.")
        for item in report.get("promoted", []):
            lines.append(f"  - U{int(item.get('index', 0)):03d} → {item.get('row_kind')} `{item.get('row_id')}`"
                         + (f" on {item['task_id']}" if item.get("task_id") else ""))
    else:
        lines.append(f"- The settlement check did not run: {ctx['check_error']}. Unpromoted items are unknown.")
    lines += ["", "## Open Items", ""]
    lines += [f"- {x} · {short(ctx['statuses'][x][0], 100)}" for x in ids] or ["- None found among touched ids. Recheck with Boot Order step 1."]

    lines += ["", "## Context", "",
              "- The hook holds no judgment. The compaction summary may hold more; rows and this file win over it.",
              "- Settlement scoring is a word rule in `handoff_check.py --settlements` (approval words or ruling cues)."
              " It can miss a settlement or flag a plain instruction."]
    if ctx["tracker_error"]:
        lines.append(f"- {ctx['tracker_error']}.")

    lines += ["", "## Lessons", "", "none"]

    lines += ["", "## Snapshot", "", f"as of {now.isoformat(timespec='seconds')}", ""]
    lines.append("- Open task titles are in Open Items above; recheck live rows at boot.")

    lines += ["", "## Without The Database", ""]
    export = ctx["export"]
    if export:
        lines.append(f"- JSONL export: `{export[0]}`, exported {export[1]} (file time of `tasks.jsonl`).")
    else:
        lines.append("- No JSONL export found beside the tracker; treat any copy as historical.")
    lines.append("- Submit changes back as proposal lines, never direct writes.")
    return "\n".join(lines) + "\n"


def predicted_path(folder, subject, now):
    """Dry run only: the path handoff-path would reserve now, found without writing."""
    today = now.date().isoformat()
    number = 1
    while (folder.is_dir() and (any(folder.glob(f"{today}-{number:03d}-*.md"))
                                or (folder / f".{today}-{number:03d}.reserved").exists())):
        number += 1
    return folder / f"{today}-{number:03d}-{subject}.md"


def main(argv=None):
    args = build_parser().parse_args(argv)
    report_out = {"written": None, "would_write": None, "unpromoted": [], "warning": None}
    if not (BIN / "handoff-boot").is_file():
        # The handoff skill is not part of day one (T595); before_compact.py still asks for a handoff.
        return 0
    try:
        boot = load_boot()
        hook = boot.read_stdin(boot.stdin_timeout(args))
        if hook is None:
            warn("stdin is not a JSON object; no handoff written")
            return 0
        if isinstance(hook.get("data"), dict):
            hook = hook["data"]
        vault = expand(args.vault)
        workspace, ws_reason = resolve_workspace(args, hook, vault)
        if workspace is None:
            warn(f"{ws_reason}; no handoff written")
            return 0
        paths.workspace(workspace)
        ws_folder = local_path(vault, workspace)
        if not ws_folder.is_dir():
            warn(f"workspace folder {ws_folder} does not exist; no handoff written")
            return 0

        if hook.get("agent_id"):
            warn(f"subagent compaction: its user turns are a lead's prompt, not {person_name()}'s; no handoff written")
            return 0
        session = args.session or hook.get("session_id") or None
        transcript = args.transcript or hook.get("transcript_path") or None
        trigger = args.trigger or hook.get("trigger") or None
        runtime = ("hermes" if hook.get("hook_event_name") in ("pre_llm_call", "pre_auxiliary_call", "post_auxiliary_call")
                   else "codex" if ("turn_id" in hook or (transcript and Path(transcript).name.startswith("rollout-"))) else "claude")
        if not session and not transcript:
            warn("no session_id and no transcript_path; no handoff written")
            return 0

        folder = local_path(ws_folder, "history/handoffs")
        seat = args.seat or os.environ.get("FOXRUN_SEAT")
        if not seat:
            for candidate, _ in boot.handoffs_in([folder]):
                fields = boot.frontmatter(candidate)
                if fields.get("session") == session and fields.get("seat"):
                    seat = fields["seat"]
                    break
        if seat == "precompact" or (seat and not SUBJECT.fullmatch(seat)):
            seat = None  # the tag of an earlier unseated pre-compaction note is not a seat
        subject = f"{seat}-precompact" if seat else "precompact"

        previous, since = last_handoff(boot, folder, session)
        check = expand(args.check or os.environ.get("FOXRUN_HANDOFF_CHECK") or DEFAULT_CHECK)
        db = tracker(workspace)
        check_report, command, check_error = run_check(check, transcript, session, since, args.db or [str(db)])
        unpromoted = (check_report or {}).get("unpromoted", []) or []
        ids = sorted(x for x in set((check_report or {}).get("ids", [])) | created_task_ids(transcript)
                     if re.fullmatch(r"T\d+", x))
        statuses, needs, tracker_error = tracker_rows(db, ids)
        open_ids = [x for x in ids if x in statuses and statuses[x][1] not in CLOSED]
        export = export_metadata(db, vault)

        now = datetime.now().astimezone()  # stamp the note after the check, just before writing
        supersedes = None
        lead_handoff = None
        session_files = []  # this session's handoffs, newest first
        for candidate, _subject in boot.handoffs_in([folder]):
            fields = boot.frontmatter(candidate)
            if fields.get("session") != session:
                continue
            relative = str(candidate.relative_to(vault))
            precompact = boot.is_precompact(candidate, fields)
            session_files.append((relative, precompact))
            if precompact:
                if supersedes is None and candidate.name.startswith(now.date().isoformat()):
                    supersedes = relative
            elif lead_handoff is None:
                lead_handoff = relative
        # Boot sequence (g-handoff-boot-sequence): the hand-written handoff, then the
        # pre-compaction notes after it, oldest first. This note comes last.
        after_lead = []
        for relative, precompact in session_files:
            if relative == lead_handoff:
                break
            if precompact:
                after_lead.append(relative)
        earlier_notes = list(reversed(after_lead))

        path = predicted_path(folder, subject, now) if args.dry_run else None
        if not args.dry_run:
            local_path(ws_folder, "history").mkdir(exist_ok=True)
            reserved = subprocess.run([sys.executable, str(BIN / "handoff-path"), str(ws_folder), subject],
                                      text=True, capture_output=True, stdin=subprocess.DEVNULL, check=False)
            if reserved.returncode != 0 or not reserved.stdout.strip():
                warn(f"handoff-path failed: {(reserved.stderr.strip().splitlines() or ['no path'])[-1]}")
                return 0
            path = Path(reserved.stdout.strip().splitlines()[-1])
        where = str(path.relative_to(vault)) if path.is_relative_to(vault) else str(path)
        warning = warning_line(len(unpromoted), where) if unpromoted else None
        text = render({
            "now": now, "workspace": workspace, "db": str(db), "report": check_report,
            "unpromoted": unpromoted, "session": session, "agent": (check_report or {}).get("model") or runtime,
            "agent_runtime": runtime, "seat": seat, "supersedes": supersedes,
            "previous": str(previous.relative_to(vault)) if previous else None, "lead_handoff": lead_handoff,
            "earlier_notes": earlier_notes,
            "trigger": trigger, "warning": warning, "ids": ids, "open_ids": open_ids,
            "statuses": statuses, "needs": needs, "since": since,
            "transcript": transcript, "check_error": check_error, "tracker_error": tracker_error,
            "export": export, "path_hint": where,
        })
        report_out.update({"workspace": workspace, "workspace_from": ws_reason, "seat": seat, "session": session,
                           "since": since.isoformat() if since else None, "check_command": command,
                           "check_error": check_error, "unpromoted": unpromoted, "warning": warning,
                           "supersedes": supersedes, "lead_handoff": lead_handoff, "earlier_notes": earlier_notes,
                           "settlements": (check_report or {}).get("settlements"), "open_ids": open_ids})
        if args.dry_run:
            report_out["would_write"] = str(path)
        else:
            path.write_text(text, encoding="utf-8")
            report_out["written"] = str(path)

        if args.json:
            report_out["text"] = text if args.dry_run else None
            print(json.dumps(report_out, indent=2, ensure_ascii=False))
        elif args.dry_run:
            print(f"dry run: would write {path}")
            if warning:
                print(f"dry run: would warn: {warning}")
            print(f"check: {' '.join(command)}")
            print(text, end="")
        else:
            if warning:
                print(json.dumps({"systemMessage": warning}, ensure_ascii=False))
                warn(warning)
            else:
                warn(f"wrote {path}")
    except Exception as error:  # a hook must never block a compaction
        warn(f"{error.__class__.__name__}: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
