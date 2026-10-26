#!/usr/bin/env python3
"""Run the agent-team evidence eval."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import sys as _shared_sys
from pathlib import Path as _SharedPath
_shared_sys.path.insert(0, str(_SharedPath(__file__).resolve().parents[2]))
from base import simple_yaml as yaml

try:
    from .paths import roots, hermes_available, tool_path
except ImportError:  # pragma: no cover
    from paths import roots, hermes_available, tool_path


Runner = Callable[..., subprocess.CompletedProcess[str]]
MARKER = "managed-by: agent-new"
CAPE_PATHS = {
    "claude": (".claude", ".md"),
    "codex": (".codex", ".toml"),
}


def _run(
    runner: Runner,
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
) -> tuple[int, str, str]:
    try:
        completed = runner(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return (
            int(completed.returncode),
            str(completed.stdout or ""),
            str(completed.stderr or ""),
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout:g} seconds"
    except OSError as error:
        return 127, "", str(error)


def _one_line(text: str, fallback: str = "no output") -> str:
    value = " ".join(text.strip().split()) or fallback
    return value.replace("|", "\\|")[:300]


def _json(stdout: str) -> dict[str, Any]:
    loaded = json.loads(stdout)
    if not isinstance(loaded, dict):
        raise ValueError("JSON output is not an object")
    return loaded


def _runtimes(row: dict[str, Any]) -> list[str]:
    raw = row.get("runtimes", [])
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _rerun_command(*, live: bool, tools: bool, check: bool, as_json: bool) -> str:
    command = [sys.executable, str(Path(__file__).resolve())]
    if live:
        command.append("--live")
    if tools:
        command.append("--tools")
    if check:
        command.append("--check")
    if as_json:
        command.append("--json")
    return shlex.join(command)


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "| step | ok | seconds | detail |",
        "|---|---|---:|---|",
    ]
    for item in result["steps"]:
        detail = str(item["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {item['name']} | {'yes' if item['ok'] else 'no'} | "
            f"{item['seconds']:.3f} | {detail} |"
        )
    lines.extend(
        [
            "",
            f"Verdict: {result['verdict']}",
            "",
            f"Rerun: `{result['rerun']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run_eval(
    *,
    live: bool = False,
    tools: bool = False,
    check: bool = False,
    probe_target: str | None = None,
    as_json: bool = False,
    runner: Runner = subprocess.run,
    root_map: dict[str, Path] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    resolved = root_map or roots()
    repo = Path(resolved["repo"])
    vault = Path(resolved["vault"])
    system = Path(resolved.get("system", Path(resolved["repo"]).parent))
    shelf = Path(resolved["shelf"])
    checked_at = now or dt.datetime.now(dt.timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=dt.timezone.utc)
    checked_at = checked_at.astimezone(dt.timezone.utc)
    steps: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []

    def record(name: str, action: Callable[[], tuple[bool, str]]) -> None:
        started = time.monotonic()
        try:
            ok, detail = action()
        except Exception as error:  # The eval records every failed step and continues.
            ok, detail = False, f"{type(error).__name__}: {error}"
        steps.append(
            {
                "name": name,
                "ok": bool(ok),
                "seconds": round(time.monotonic() - started, 3),
                "detail": _one_line(str(detail)),
            }
        )

    def unit_tests() -> tuple[bool, str]:
        code, stdout, stderr = _run(
            runner,
            [sys.executable, "-m", "unittest", "discover", "-s", str(repo / "tests")],
            cwd=repo,
            timeout=600,
        )
        output = stdout + stderr
        match = re.search(r"Ran (\d+) tests?", output)
        if code == 0 and match:
            return True, f"{match.group(1)} passed"
        return False, _one_line(output, f"unittest exit {code}")

    record("unit tests", unit_tests)

    def identity_list() -> tuple[bool, str]:
        code, stdout, stderr = _run(
            runner,
            [sys.executable, str(tool_path(repo, "agent_new.py")), "list", "--json"],
            cwd=repo,
            timeout=60,
        )
        if code != 0:
            return False, f"agent-new list exit {code}: {_one_line(stdout + stderr)}"
        payload = _json(stdout)
        found = payload.get("identities")
        if not isinstance(found, list):
            return False, "agent-new list returned no identities list"
        identities.extend(item for item in found if isinstance(item, dict))
        count = len(identities)
        return count >= 7, f"{count} identities"

    record("identity list", identity_list)

    def profile_drift() -> tuple[bool, str]:
        if runner is subprocess.run and not hermes_available():
            return True, "Claude and Codex on day one."
        if not identities:
            return False, "identity list unavailable"
        profiles = [
            row for row in identities if row.get("hermes_mode") in {"profile", "kanban"}
        ]
        failed = []
        for row in profiles:
            identity = str(row.get("id", "unknown"))
            code, stdout, stderr = _run(
                runner,
                [sys.executable, str(tool_path(repo, "agent_new.py")), "diff", identity, "--json"],
                cwd=repo,
                timeout=90,
            )
            if code != 0:
                failed.append(f"{identity} (exit {code}: {_one_line(stdout + stderr)})")
        if failed:
            return False, f"{len(profiles) - len(failed)}/{len(profiles)} profiles match; failed: {', '.join(failed)}"
        return True, f"{len(profiles)}/{len(profiles)} profiles match"

    record("profile drift", profile_drift)

    def managed_capes() -> tuple[bool, str]:
        if not identities:
            return False, "identity list unavailable"
        failures = []
        checked = 0
        for row in identities:
            identity = str(row.get("id", "unknown"))
            for runtime in _runtimes(row):
                if runtime not in CAPE_PATHS:
                    continue
                directory, suffix = CAPE_PATHS[runtime]
                # Capes render where agent_new.render_identity writes them since 4a024f1 (T740):
                # system seats under runs/generated/agents/<runtime>/, workspace seats under <workspace>/team/<runtime>/.
                name = f"{identity}{suffix}"
                candidates = [system / "runs/generated/agents" / runtime / name] + sorted(vault.glob(f"*/team/{runtime}/{name}"))
                path = next((item for item in candidates if item.is_file()), candidates[0])
                checked += 1
                if not path.is_file():
                    failures.append(f"{identity}/{runtime} missing")
                elif MARKER not in path.read_text(encoding="utf-8", errors="replace"):
                    failures.append(f"{identity}/{runtime} unmanaged")
        if failures:
            return False, f"{checked - len(failures)}/{checked} capes managed; failed: {', '.join(failures)}"
        return True, f"{checked}/{checked} capes managed"

    record("managed capes", managed_capes)

    def skill_pin() -> tuple[bool, str]:
        path = repo / "execution" / "skills.yaml"
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            return False, f"skill registry is invalid: {path}"
        if not loaded.get("release"):
            return False, "skill release pin is missing"
        release = str(loaded["release"])
        try:
            shelf_release = Path(os.readlink(shelf)).name
        except OSError as error:
            return True, f"WARN: cannot read shelf symlink {shelf}: {error}"
        if release != shelf_release:
            return True, f"WARN: pin {release} differs from shelf {shelf_release}"
        return True, f"pin matches shelf {release}"

    record("skill pin", skill_pin)

    if live:
        def live_probes() -> tuple[bool, str]:
            if not identities:
                return False, "identity list unavailable"

            def probe(row: dict[str, Any]) -> tuple[int, str, str, dict[str, Any] | None]:
                identity = str(row.get("id", "unknown"))
                code, stdout, stderr = _run(
                    runner,
                    [sys.executable, str(tool_path(repo, "agent_new.py")), "probe", identity, "--json"],
                    cwd=repo,
                    timeout=360,
                )
                try:
                    payload = _json(stdout)
                except (json.JSONDecodeError, ValueError):
                    payload = None
                return code, stdout, stderr, payload

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                future_rows = [(row, pool.submit(probe, row)) for row in identities]
                results = [(row, future.result()) for row, future in future_rows]

            total = 0
            passed = 0
            failures = []
            for row, (code, stdout, stderr, payload) in results:
                identity = str(row.get("id", "unknown"))
                expected = _runtimes(row)
                total += len(expected)
                if payload is None or not isinstance(payload.get("results"), list):
                    failures.append(f"{identity}/invalid-json")
                    continue
                runtime_results = {
                    str(item.get("runtime")): item
                    for item in payload["results"]
                    if isinstance(item, dict) and item.get("runtime")
                }
                for runtime in expected:
                    item = runtime_results.get(runtime)
                    if item and item.get("ok") is True:
                        passed += 1
                    else:
                        failures.append(f"{identity}/{runtime}")
                if code != 0 and not any(value.startswith(f"{identity}/") for value in failures):
                    failures.append(f"{identity}/exit-{code}")
                if code != 0 and payload is None:
                    failures[-1] += f":{_one_line(stdout + stderr)}"
            if failures:
                return False, f"{passed}/{total} runtimes ok; failed: {', '.join(failures)}"
            return True, f"{passed}/{total} runtimes ok"

        record("live probes", live_probes)

    if tools:
        def tool_probe() -> tuple[bool, str]:
            target = probe_target
            if target is None:
                config_path = repo / "execution" / "notifications.yaml"
                config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                target = config.get("probe_target")
            if not isinstance(target, str) or not target.strip():
                return False, "tool probe target is missing; set --probe-target or execution/notifications.yaml probe_target"
            code, stdout, stderr = _run(
                runner,
                [sys.executable, str(tool_path(repo, "tool_probe.py")), target, "--json"],
                cwd=repo,
                timeout=600,
            )
            payload = _json(stdout)
            found = payload.get("tools")
            if not isinstance(found, list):
                return False, "tool probe returned no tools list"
            failed = [
                str(item.get("tool"))
                for item in found
                if isinstance(item, dict) and item.get("state") in {"failed", "timeout"}
            ]
            if failed:
                return False, f"failed or timed out: {', '.join(failed)}"
            return True, f"{len(found)} tools checked; no failures or timeouts (exit {code})"

        record("tool probe", tool_probe)

    if check:
        def profile_check() -> tuple[bool, str]:
            code, stdout, stderr = _run(
                runner,
                [sys.executable, str(tool_path(repo, "profile_check.py")), "--json"],
                cwd=repo,
                timeout=900,
            )
            payload = _json(stdout)
            state = str(payload.get("state", "missing"))
            return state != "red", f"state {state}; exit {code}"

        record("profile check", profile_check)

    verdict = "PASS" if all(item["ok"] for item in steps) else "FAIL"
    stamp = checked_at.strftime("%Y%m%dT%H%M%SZ")
    report_dir = resolved.get("state", repo / "generated") / "evals" / "agents"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"{stamp}.json"
    markdown_path = report_dir / f"{stamp}.md"
    result: dict[str, Any] = {
        "hermes": "available" if hermes_available() else "Claude and Codex on day one.",
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "verdict": verdict,
        "steps": steps,
        "rerun": _rerun_command(live=live, tools=tools, check=check, as_json=as_json),
        "reports": {"json": str(json_path), "markdown": str(markdown_path)},
    }
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--tools", action="store_true")
    parser.add_argument("--probe-target", help="Identity to probe; default comes from execution/notifications.yaml probe_target")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_eval(
        live=args.live,
        tools=args.tools,
        probe_target=args.probe_target,
        check=args.check,
        as_json=args.as_json,
    )
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_markdown(result), end="")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
