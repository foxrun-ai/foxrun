#!/usr/bin/env python3
"""Read-only Hermes MCP and external-skill probe."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import sys as _shared_sys
from pathlib import Path as _SharedPath
_shared_sys.path.insert(0, str(_SharedPath(__file__).resolve().parents[2]))
from base import simple_yaml as yaml, paths as system_paths
try:
    from .paths import roots, hermes_available
except ImportError:  # Direct command invocation.
    from paths import roots, hermes_available

FAIL_PATTERN = re.compile(r"\u2717|connection failed|all connection attempts failed|failed to connect", re.IGNORECASE)
AUTH_PATTERN = re.compile(
    r"oauth|login|unauthorized|\b401\b|not authenticated|no cached tokens|mcp login|oauth", re.IGNORECASE
)
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _root() -> Path:
    return roots()["repo"]


def _hermes_home() -> Path:
    return roots()["hermes"]


def _note(output: str, fallback: str) -> str:
    line = " ".join(output.strip().split())
    return (line or fallback).replace("|", "\\|")[:240]


def _mcp_entries(config: dict[str, Any]) -> list[tuple[str, bool]]:
    servers = config.get("mcp_servers") or {}
    entries: list[tuple[str, bool]] = []
    if isinstance(servers, dict):
        for name, settings in servers.items():
            if isinstance(settings, dict):
                enabled = settings.get("enabled") is True
            else:
                enabled = settings is True
            entries.append((str(name), enabled))
    elif isinstance(servers, list):
        for settings in servers:
            if isinstance(settings, dict) and settings.get("name"):
                entries.append((str(settings["name"]), settings.get("enabled") is True))
    return entries


def _probe_tool(
    profile: str,
    name: str,
    timeout: float,
    runner: Runner,
) -> dict[str, Any]:
    started = time.monotonic()
    command = ["hermes", "-p", profile, "mcp", "test", name]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        seconds = round(time.monotonic() - started, 3)
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        if completed.returncode == 0 and not FAIL_PATTERN.search(output):
            state = "ok"
            note = _note(output, "connected")
        elif AUTH_PATTERN.search(output):
            state = "not_connected"
            note = _note(output, "authentication is required")
        elif completed.returncode == 0:
            state = "failed"
            note = _note(output, "reported failure despite exit 0")
        else:
            state = "failed"
            note = _note(output, f"exit {completed.returncode}")
    except subprocess.TimeoutExpired:
        seconds = round(time.monotonic() - started, 3)
        state = "timeout"
        note = f"timed out after {timeout:g} seconds"
    except OSError as error:
        seconds = round(time.monotonic() - started, 3)
        state = "failed"
        note = _note(str(error), "could not start hermes")
    return {"tool": name, "state": state, "seconds": seconds, "note": note}


def _external_dirs(config: dict[str, Any]) -> list[dict[str, Any]]:
    skills = config.get("skills") or {}
    raw_dirs = skills.get("external_dirs", []) if isinstance(skills, dict) else []
    if isinstance(raw_dirs, str):
        raw_dirs = [raw_dirs]
    results = []
    for raw in raw_dirs or []:
        path = Path(os.path.expandvars(str(raw))).expanduser()
        exists = path.is_dir()
        count = sum(1 for item in path.rglob("SKILL.md") if item.is_file()) if exists else 0
        results.append({"path": str(path), "exists": exists, "skill_count": count})
    return results


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Tool probe: {result['profile']}",
        "",
        "| tool | state | seconds | note |",
        "|---|---|---:|---|",
    ]
    for item in result["tools"]:
        state = item["state"].replace("_", " ")
        lines.append(
            f"| {item['tool']} | {state} | {item['seconds']:.3f} | {item['note']} |"
        )
    disconnected = [item["tool"] for item in result["tools"] if item["state"] == "not_connected"]
    lines.extend(["", "## Connection claim", ""])
    if disconnected:
        lines.append(
            "These tools are **not connected** and are not claimed working: "
            + ", ".join(disconnected)
            + "."
        )
    else:
        lines.append("No tool is marked **not connected** in this probe.")
    lines.extend(["", "## External skill directories", ""])
    if not result["external_dirs"]:
        lines.append("No external skill directories are configured.")
    else:
        lines.extend(["| path | exists | SKILL.md count |", "|---|---|---:|"])
        for item in result["external_dirs"]:
            escaped_path = item["path"].replace("|", "\\|")
            lines.append(
                f"| {escaped_path} | {'yes' if item['exists'] else 'no'} | "
                f"{item['skill_count']} |"
            )
    return "\n".join(lines) + "\n"


def probe_profile(
    profile: str,
    *,
    timeout: float = 60,
    hermes_home: Path | None = None,
    agent_team_root: Path | None = None,
    runner: Runner = subprocess.run,
    now: dt.datetime | None = None,
    write_reports: bool = True,
) -> dict[str, Any]:
    home = Path(hermes_home) if hermes_home is not None else _hermes_home()
    root = Path(agent_team_root) if agent_team_root is not None else _root()
    config_path = home / "profiles" / profile / "config.yaml"
    if not config_path.is_file():
        identity_path = system_paths.resolve_seat(profile, home=root.parent, shipped_dir=root)
        if identity_path is None:
            raise FileNotFoundError(f"profile config not found: {config_path}")
        from agent_new import load_identity, MARKER
        identity = load_identity(profile, root)
        if identity.data["hermes_mode"] != "none" or "hermes" in identity.data["runtimes"]:
            raise FileNotFoundError(f"profile config not found: {config_path}")
        tools=[]
        for runtime,suffix in (("claude", ".md"), ("codex", ".toml")):
            if runtime not in identity.data["runtimes"]: continue
            cape=roots()["portfolio"]/("."+runtime)/"agents"/(profile+suffix)
            managed=cape.is_file() and MARKER in cape.read_text()
            tools.append({"tool":runtime,"state":"ok" if managed else "failed","seconds":0.0,
                          "note":"managed cape present; live runtime unverified" if managed else "managed cape missing"})
        return {"profile":profile,"checked_at":(now or dt.datetime.now(dt.timezone.utc)).isoformat(),
                "config":str(identity_path),"tools":tools,"external_dirs":[],"reports":{},
                "hermes":"Claude and Codex on day one; excluded runtime not declared.",
                "exit_code":4 if any(item["state"]=="failed" for item in tools) else 0}

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"profile config must be a mapping: {config_path}")

    tools = []
    for name, enabled in _mcp_entries(loaded):
        if enabled:
            tools.append(_probe_tool(profile, name, timeout, runner))
        else:
            tools.append(
                {"tool": name, "state": "disabled", "seconds": 0.0, "note": "disabled; not tested"}
            )
    checked_at = now or dt.datetime.now(dt.timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=dt.timezone.utc)
    checked_at = checked_at.astimezone(dt.timezone.utc)
    exit_code = 4 if any(item["state"] in {"failed", "timeout"} for item in tools) else 0
    result: dict[str, Any] = {
        "profile": profile,
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "config": str(config_path),
        "tools": tools,
        "external_dirs": _external_dirs(loaded),
        "exit_code": exit_code,
        "reports": {},
    }
    if write_reports:
        stamp = checked_at.strftime("%Y%m%dT%H%M%SZ")
        report_dir = root / "generated" / "probes"
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / f"tools-{profile}-{stamp}.json"
        md_path = report_dir / f"tools-{profile}-{stamp}.md"
        result["reports"] = {"json": str(json_path), "markdown": str(md_path)}
        json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        md_path.write_text(render_markdown(result), encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    print('Claude and Codex on day one.')
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
