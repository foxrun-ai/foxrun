#!/usr/bin/env python3
"""Independently check the nightly launchd job and alert on a stopped, stale, or failed job."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import schedule


def newest_receipt(root: Path) -> tuple[datetime | None, dict]:
    """Return the time and the body of the newest nightly receipt."""
    latest, body = None, {}
    runs = root / "runs"
    if not runs.is_dir() or runs.is_symlink():
        return None, {}
    # T755: receipts live in runs/nightly/; older ones at the top of runs/ still count.
    for path in list(runs.glob("nightly/*-nightly/receipt.json")) + list(runs.glob("*-nightly/receipt.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
            value = datetime.strptime(data.get("at"), "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if latest is None or value > latest:
            latest, body = value, data
    return latest, body


def last_receipt(root: Path) -> datetime | None:
    return newest_receipt(root)[0]


def failed_steps(receipt: dict) -> list:
    """Name the failed steps of a nightly receipt; a nonzero exit with no named step counts too."""
    steps = receipt.get("steps") if isinstance(receipt.get("steps"), dict) else {}
    failed = sorted(name for name, step in steps.items() if isinstance(step, dict) and step.get("failed"))
    code = receipt.get("exit")
    if not failed and isinstance(code, int) and code != 0:
        failed = ["exit %d" % code]
    return failed


def window_seconds(root: Path) -> int:
    clock = schedule.clock(root)
    expected = clock.get("StartInterval", 86400)
    return expected + max(60, min(7200, expected // 12))


def inspect(root: Path, label: str, *, now: datetime | None = None, runner=subprocess.run) -> dict:
    now = now or datetime.now(timezone.utc)
    command = [schedule.launchctl(), "print", "gui/%d/%s" % (os.getuid(), label)]
    try:
        result = runner(command, capture_output=True, text=True, timeout=10)
        launchctl_exit = result.returncode
    except (OSError, subprocess.TimeoutExpired):
        launchctl_exit = 127
    loaded = launchctl_exit == 0
    latest, receipt = newest_receipt(root)
    failed = failed_steps(receipt)
    if latest is None:
        # The job gets one window after install before a missing receipt is stale.
        job = Path.home() / "Library/LaunchAgents" / (label + ".plist")
        starting = datetime.fromtimestamp(job.stat().st_mtime, timezone.utc) if job.is_file() else now
        age = max(0, int((now - starting).total_seconds()))
    else:
        age = max(0, int((now - latest).total_seconds()))
    window = window_seconds(root)
    return {"scheduler_loaded": loaded, "launchctl_exit": launchctl_exit,
            "last_receipt_at": latest.isoformat() if latest else None,
            "receipt_age_seconds": age, "window_seconds": window,
            "last_exit": receipt.get("exit"), "failed_steps": failed,
            "alarm": not loaded or age >= window or bool(failed)}


def check(root: Path, label: str = schedule.LABEL, *, now: datetime | None = None,
          runner=subprocess.run, notifier=subprocess.run) -> dict:
    root = root.expanduser().resolve()
    now = now or datetime.now(timezone.utc)
    state = inspect(root, label, now=now, runner=runner)
    runs = root / "runs"
    runs.mkdir(exist_ok=True)
    state_file = runs / "nightly-watchdog-state.json"
    if state_file.is_symlink():
        raise ValueError("watchdog state must not be a link")
    previous = json.loads(state_file.read_text()) if state_file.is_file() else {}
    if not state["scheduler_loaded"]:
        signature = "stopped"
    elif state["receipt_age_seconds"] >= state["window_seconds"]:
        signature = "stale"
    else:
        signature = "failed" if state["failed_steps"] else "healthy"
    notified = False
    if state["alarm"] and (previous.get("signature") != signature or previous.get("delivered") is not True):
        stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        folder = runs / "nightly" / (stamp + "-nightly-watchdog")
        folder.parent.mkdir(exist_ok=True)
        folder.mkdir(mode=0o700)
        title = "Foxrun memory job failed" if signature == "failed" else "Foxrun memory job stopped"
        command = ["/usr/bin/osascript", "-e",
                   'display notification "Open the nightly watchdog receipt." with title "%s"' % title]
        try:
            result = notifier(command, capture_output=True, text=True, timeout=10)
            delivered = result.returncode == 0
            detail = (result.stderr or "").strip()[:200]
        except (OSError, subprocess.TimeoutExpired) as error:
            delivered = False
            detail = type(error).__name__ + ": " + str(error)[:160]
        alert = {"mode": "live", "source": "nightly-watchdog", "channel": "macOS",
                 "delivered": delivered, "checked_at": now.isoformat(), "label": label,
                 "while_scheduler_dead": not state["scheduler_loaded"],
                 "detail": detail, **state}
        (folder / "alert.json").write_text(json.dumps(alert, indent=2) + "\n")
        (folder / "receipt.json").write_text(json.dumps({"owner": "keeper", "at": stamp,
            "alert": str(folder / "alert.json"), "status": signature}, indent=2) + "\n")
        notified = delivered
    if previous.get("signature") != signature or state["alarm"] and previous.get("delivered") is not True:
        # A new private temporary file, never a fixed name a planted link could hold.
        schedule.replace_bytes(state_file, (json.dumps({"signature": signature, "checked_at": now.isoformat(),
                               "delivered": notified if state["alarm"] else False}, indent=2) + "\n").encode())
    return {**state, "status": signature, "notified": notified}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("FOXRUN_HOME") or Path(__file__).resolve().parents[1]))
    parser.add_argument("--label", default=schedule.LABEL)
    args = parser.parse_args(argv)
    try:
        row = check(args.home, args.label)
        print(json.dumps(row, sort_keys=True))
        return 0
    except (OSError, ValueError) as error:
        print("FAIL watchdog: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
