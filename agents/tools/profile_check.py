#!/usr/bin/env python3
"""Nightly identity drift, tool, and cape check."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import sys as _shared_sys
from pathlib import Path as _SharedPath
_shared_sys.path.insert(0, str(_SharedPath(__file__).resolve().parents[2]))
from base import simple_yaml as yaml, paths as system_paths
try:
    from .paths import roots, hermes_available, tool_path
except ImportError:  # Direct command invocation.
    from paths import roots, hermes_available, tool_path

try:
    from .tool_probe import probe_profile
except ImportError:  # Direct command invocation.
    from tool_probe import probe_profile

Runner = Callable[..., subprocess.CompletedProcess[str]]
MODES = {"profile", "kanban"}
EXIT_CODES = {"green": 0, "yellow": 1, "red": 2}



def known_down_tools() -> set[str]:
    """Tools every client file lists under access.not_connected: expected off, never red.

    Client files live in the portfolio, one per workspace: <portfolio>/<workspace>/config/client.yaml.
    """
    out: set[str] = set()
    for path in sorted(_vault_root().glob("*/config/client.yaml")):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except Exception:
            continue
        for name in ((data.get("access") or {}).get("not_connected") or []):
            out.add(str(name))
    return out

def _root() -> Path:
    return roots()["repo"]


def _vault_root() -> Path:
    return roots()["portfolio"]


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    loaded = yaml.safe_load(text[4:end]) or {}
    return loaded if isinstance(loaded, dict) else {}


def _identities(root: Path, *, include_core: bool = False) -> list[dict[str, str]]:
    found = []
    names = {p.stem for folder in (root, root.parent / "profile/agents") for p in folder.glob("*.md")}
    for name in sorted(names):
        path = system_paths.resolve_seat(name, home=root.parent, shipped_dir=root)
        if path is None:
            continue
        data = _frontmatter(path)
        if not data.get("id") and data.get("hermes_mode") not in MODES:
            continue
        if not include_core and data.get("hermes_mode") not in MODES:
            continue
        identity = str(data.get("id") or path.stem)
        profile = data.get("hermes_profile") or identity
        found.append({"id": identity, "profile": str(profile), "source": str(path), "mode": data.get("hermes_mode"), "runtimes": data.get("runtimes")})
    return found


def _run_drift(identity: str, root: Path, runner: Runner) -> dict[str, Any]:
    command = [sys.executable, str(tool_path(root, "agent_new.py")), "diff", identity, "--json"]
    try:
        completed = runner(command, capture_output=True, text=True, check=False)
    except OSError as error:
        return {"state": "error", "exit_code": None, "note": str(error)}
    states = {0: "match", 2: "profile_missing", 3: "drift"}
    output = " ".join((completed.stdout or completed.stderr or "").strip().split())
    return {
        "state": states.get(completed.returncode, "error"),
        "exit_code": completed.returncode,
        "note": output[:240],
    }


def _cape(path: Path) -> dict[str, Any]:
    exists = path.is_file()
    managed = exists and "managed-by: agent-new" in path.read_text(encoding="utf-8")
    return {"path": str(path), "exists": exists, "managed": managed}


def _identity_result(
    identity: dict[str, str],
    root: Path,
    vault: Path,
    runner: Runner,
    probe_runner: Callable[..., dict[str, Any]],
    checked_at: dt.datetime,
    declared_runtimes_only: bool = False,
) -> dict[str, Any]:
    identity_id = identity["id"]
    core_only = identity.get("mode") not in MODES or (identity.get("runtimes") is not None and not hermes_available())
    if core_only:
        drift = {"state": "not_applicable", "exit_code": 0, "note": "Claude and Codex on day one."}
        tools = {"profile": identity["profile"], "tools": [], "external_dirs": []}
        probe_error = None
    else:
        drift = _run_drift(identity_id, root, runner)
        try:
            tools = probe_runner(identity["profile"], agent_team_root=root, now=checked_at)
            probe_error = None
        except Exception as error:
            tools = {"profile": identity["profile"], "tools": [], "external_dirs": []}
            probe_error = str(error)
    runtimes = (identity.get("runtimes") or ["claude", "codex"]) if declared_runtimes_only else ["claude", "codex"]
    capes = {runtime: _cape(vault / ("." + runtime) / "agents" / (identity_id + suffix))
             for runtime, suffix in (("claude", ".md"), ("codex", ".toml")) if runtime in runtimes}

    red: list[str] = []
    yellow: list[str] = []
    known_down = known_down_tools()
    if drift["state"] == "drift":
        red.append("drift")
    elif drift["state"] == "profile_missing":
        red.append("profile missing")
    elif drift["state"] == "error":
        yellow.append("drift check error")
    for item in tools.get("tools", []):
        if item.get("state") == "not_connected" or item.get("tool") in known_down:
            yellow.append(f"{item['tool']} not connected")
        elif item.get("state") in {"failed", "timeout"}:
            red.append(f"{item['tool']} {item['state']}")
    if probe_error:
        red.append("tool probe error")
    for item in tools.get("external_dirs", []):
        if not item.get("exists"):
            yellow.append("external skill directory missing")
    for runtime, cape in capes.items():
        if not cape["exists"]:
            red.append(f"{runtime} cape missing")
        elif not cape["managed"]:
            red.append(f"{runtime} cape unmanaged")
    state = "red" if red else "yellow" if yellow else "green"
    return {
        **identity,
        "state": state,
        "drift": drift,
        "tool_probe": tools,
        "probe_error": probe_error,
        "capes": capes,
        "reasons": red + yellow,
    }


def _default_target(root: Path) -> str:
    path = root / "execution" / "notifications.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    topics = loaded.get("topics", {})
    topic = topics.get(1) or topics.get("1") or {}
    target = topic.get("return")
    if not target:
        raise ValueError(f"topic 1 return is missing: {path}")
    return str(target)


def _parse_target(target: str) -> tuple[str, str]:
    match = re.fullmatch(r"telegram:([^:]+):(\d+)", target)
    if not match:
        raise ValueError(f"invalid Telegram target: {target}")
    return match.group(1), match.group(2)


def _resolve_target(target: str, runner: Runner, profile: str | None = None) -> str | None:
    chat, topic = _parse_target(target)
    if re.fullmatch(r"-?\d+", chat):
        return target
    if profile is None:
        config_path = _root() / "execution" / "notifications.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        profile = config.get("hermes_profile")
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("symbolic Telegram target requires a configured Hermes profile")
    completed = runner(
        ["hermes", "-p", profile, "send", "--list", "telegram"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    topic_pattern = re.compile(rf"\btopic\s+{re.escape(topic)}\b", re.IGNORECASE)
    for line in completed.stdout.splitlines():
        if not topic_pattern.search(line):
            continue
        ids = re.findall(r"(?<!\d)-?\d{5,}(?!\d)", line)
        if ids:
            return f"telegram:{ids[0]}:{topic}"
    return None


def _bounded(text: str) -> str:
    return text if len(text) <= 200 else text[:199] + "…"


def _alert_line(date: str, state: str, identities: list[dict[str, Any]]) -> str:
    parts = []
    for item in identities:
        if item["reasons"]:
            parts.append(f"{item['id']}: {', '.join(item['reasons'])}")
    return _bounded(f"agent-team check {date}: {state} — " + "; ".join(parts))


def _weekly_line(counts: dict[str, int]) -> str:
    return _bounded(
        "agent-team weekly: "
        f"{counts['profiles']} profiles checked, {counts['drift']} drift, "
        f"{counts['tool_failures']} tool failures, {counts['open']} open"
    )


def run_checks(
    *,
    send: bool = False,
    include_core: bool = False,
    declared_runtimes_only: bool = False,
    hermes_profile: str | None = None,
    target: str | None = None,
    agent_team_root: Path | None = None,
    vault_root: Path | None = None,
    runner: Runner = subprocess.run,
    probe_runner: Callable[..., dict[str, Any]] = probe_profile,
    utc_now: dt.datetime | None = None,
    local_now: dt.datetime | None = None,
) -> dict[str, Any]:
    root = Path(agent_team_root) if agent_team_root is not None else _root()
    vault = Path(vault_root) if vault_root is not None else _vault_root()
    checked_at = utc_now or dt.datetime.now(dt.timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=dt.timezone.utc)
    checked_at = checked_at.astimezone(dt.timezone.utc)
    local = local_now or dt.datetime.now().astimezone()
    identities = [
        _identity_result(item, root, vault, runner, probe_runner, checked_at, declared_runtimes_only)
        for item in _identities(root, include_core=include_core)
    ]
    if any(item["state"] == "red" for item in identities):
        state = "red"
    elif any(item["state"] == "yellow" for item in identities):
        state = "yellow"
    else:
        state = "green"
    counts = {
        "profiles": len(identities),
        "drift": sum(item["drift"]["state"] == "drift" for item in identities),
        "tool_failures": sum(
            tool.get("state") in {"failed", "timeout"}
            for item in identities
            for tool in item["tool_probe"].get("tools", [])
        ),
        "open": sum(len(item["reasons"]) for item in identities),
    }
    date = checked_at.date().isoformat()
    result: dict[str, Any] = {
        "date": date,
        "hermes": "available" if hermes_available() else "Claude and Codex on day one.",
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "state": state,
        "counts": counts,
        "identities": identities,
        "exit_code": EXIT_CODES[state],
        "send": {"requested": send, "resolved_target": None, "messages": []},
    }
    messages = []
    if state != "green":
        messages.append(_alert_line(date, state, identities))
    if local.weekday() == 6:
        messages.append(_weekly_line(counts))
    if send and messages:
        requested_target = target or _default_target(root)
        try:
            profile = hermes_profile
            if profile is None and not re.fullmatch(r"-?\d+", _parse_target(requested_target)[0]):
                config = yaml.safe_load((root / "execution" / "notifications.yaml").read_text()) or {}
                profile = config.get("hermes_profile")
            resolved = _resolve_target(requested_target, runner, profile)
        except (OSError, ValueError):
            resolved = None
        if not resolved:
            for line in messages:
                print(line)
            result["exit_code"] = 5
        else:
            result["send"]["resolved_target"] = resolved
            for line in messages:
                try:
                    completed = runner(
                        ["hermes", "send", "-t", resolved, line],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                except OSError:
                    completed = None
                sent = completed is not None and completed.returncode == 0
                result["send"]["messages"].append({"line": line, "sent": sent})
                if not sent:
                    print(line)
                    result["exit_code"] = 5
    report_dir = root / "generated" / "checks"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{date}.json"
    result["report"] = str(report_path)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--include-core", action="store_true", help="Also check identities without a Hermes profile")
    parser.add_argument("--declared-runtimes-only", action="store_true", help="Check only core runtimes named by each identity")
    parser.add_argument("--hermes-profile", help="Profile for symbolic Telegram targets; default comes from execution/notifications.yaml")
    parser.add_argument("--target")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    print('Claude and Codex on day one.')
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
