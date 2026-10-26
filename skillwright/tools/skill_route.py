#!/usr/bin/env python3
"""Plan, stage, verify, apply, and roll back runtime skill parity."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import stat
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path


EXCLUDED_PARTS = {
    ".git",
    ".cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


def absolute_env(name: str, default: str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.environ.get(name, default))))


def source_manifest_path(root: Path) -> Path:
    """Use the renamed manifest, or the current authoring manifest."""
    for name in ("shipped.yaml", "distribution.yaml"):
        candidate = root / "manifests" / name
        if candidate.is_file():
            return candidate
    return root / "manifests" / "shipped.yaml"


DOJO = absolute_env("SKILLS_DOJO_ROOT", "~/.foxrun/skillwright")
STATE = absolute_env("SKILL_STATE_ROOT", "~/.foxrun/skillwright/skill-state")
ACTIVE = absolute_env("SKILLS_ACTIVE_PATH", "~/.foxrun/skills")
CLAUDE = absolute_env("SKILLS_CLAUDE_ROOT", "~/.claude/skills")
LOCK = absolute_env("SKILLS_LOCK_PATH", str(STATE / "lifecycle.lock"))
DIST = source_manifest_path(DOJO)
CLAUDE_STATE = STATE / "claude-state.json"


@contextmanager
def lifecycle_lock():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"skill lifecycle lock is busy: {LOCK}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def digest_tree(path: Path) -> tuple[str, int]:
    records = []
    for current_root, dirs, files in os.walk(path, followlinks=False):
        root = Path(current_root)
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_PARTS)
        for name in sorted(files):
            candidate = root / name
            relative = candidate.relative_to(path)
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode):
                payload = os.readlink(candidate).encode("utf-8", "surrogateescape")
                mode = "120000"
            elif stat.S_ISREG(info.st_mode):
                payload = candidate.read_bytes()
                mode = "100755" if info.st_mode & stat.S_IXUSR else "100644"
            else:
                continue
            records.append(
                (
                    relative.as_posix(),
                    mode,
                    hashlib.sha256(payload).hexdigest(),
                )
            )
    digest = hashlib.sha256()
    for relative, mode, content_hash in sorted(records):
        digest.update(relative.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(mode.encode("ascii"))
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), len(records)


def within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def snapshot_entry(path: Path) -> dict | None:
    if path.is_symlink():
        target_text = os.readlink(path)
        target = (path.parent / target_text).resolve(strict=False)
        if not path.exists():
            ownership = "broken_link"
        elif within(target, ACTIVE.resolve(strict=False)):
            ownership = "shared_link"
        else:
            ownership = "external_link"
        return {
            "kind": "symlink",
            "ownership": ownership,
            "target": target_text,
            "resolved_target": str(target),
            "resolves": path.exists(),
        }
    if path.is_dir():
        digest, count = digest_tree(path)
        return {
            "kind": "directory",
            "ownership": "physical_copy",
            "digest": digest,
            "file_count": count,
        }
    if path.exists():
        return {"kind": "file", "ownership": "unmanaged_file"}
    return None


def equivalent_before(expected: dict | None, current: dict | None) -> bool:
    if expected is None or current is None:
        return expected is current
    if expected.get("kind") != current.get("kind"):
        return False
    if expected["kind"] == "symlink":
        return expected.get("target") == current.get("target")
    if expected["kind"] == "directory":
        return (
            expected.get("digest") == current.get("digest")
            and expected.get("file_count") == current.get("file_count")
        )
    return expected == current


def matches_applied_link(name: str, entry: dict, current: dict | None) -> bool:
    if entry.get("claude_action") not in {
        "create_link",
        "repair_link",
        "replace_physical_with_link",
        "retarget_link",
    }:
        return False
    if current is None or current.get("ownership") != "shared_link":
        return False
    target = Path(entry.get("claude_target", str(ACTIVE / name)))
    return current.get("resolved_target") == str(target.resolve(strict=False))


def verify_baseline(distribution: dict) -> set[str]:
    drift = []
    applied = set()
    for name, entry in distribution["skills"].items():
        if entry.get("source") == "host_specific":
            continue
        expected = entry.get("claude_before")
        current = snapshot_entry(CLAUDE / name)
        if equivalent_before(expected, current):
            continue
        if matches_applied_link(name, entry, current):
            applied.add(name)
            continue
        drift.append(name)
    for name, expected in distribution.get("unmanaged_claude", {}).items():
        if expected.get("ownership") == "app_owned":
            # The Claude app owns this folder and rewrites it at any time, so the
            # manifest pins no content. It must still be a real folder.
            path = CLAUDE / name
            if path.is_symlink() or not path.is_dir():
                drift.append(name)
            continue
        current = snapshot_entry(CLAUDE / name)
        if not equivalent_before(expected, current):
            drift.append(name)
    for name, entry in distribution.get("excluded", {}).items():
        expected = entry.get("claude_before")
        current = snapshot_entry(CLAUDE / name)
        if not equivalent_before(expected, current):
            drift.append(name)
    if drift:
        raise RuntimeError("Claude entry drift: " + ", ".join(sorted(drift)))
    return applied


def ensure_candidate(distribution: dict, candidate: Path) -> None:
    missing = []
    for name, entry in distribution["skills"].items():
        if entry["source"] == "host_specific":
            continue
        if not (candidate / name / "SKILL.md").is_file():
            missing.append(name)
    if missing:
        raise RuntimeError("candidate missing skills: " + ", ".join(sorted(missing)))
    present_excluded = [
        name
        for name in distribution.get("excluded", {})
        if (candidate / name).exists() or (candidate / name).is_symlink()
    ]
    if present_excluded:
        raise RuntimeError("candidate contains excluded skills: " + ", ".join(present_excluded))


def snapshot_dry_run(distribution: dict, candidate: Path) -> int:
    from skill_scoped import validate_record
    record = validate_record(sys.modules[__name__], candidate)
    if record != distribution:
        raise RuntimeError("Snapshot candidate and shipped record differ. Stop.")
    actions = Counter()
    blocked = []
    for name in sorted(distribution["skills"]):
        target = CLAUDE / name
        root_link = CLAUDE.is_symlink() and CLAUDE.resolve() == ACTIVE.resolve()
        stable = (root_link or target.is_symlink()) and target.is_dir() and target.resolve() == (ACTIVE / name).resolve()
        if stable:
            actions["keep_link"] += 1
        else:
            actions["hold"] += 1
            blocked.append({"name": name, "reason": "Snapshot has no reviewed Claude ownership baseline. Preserve this entry; use a reviewed route plan."})
    print(json.dumps(dict(candidate=str(candidate), actions=dict(actions), changes=[],
                         approval_required_changes=[], preserved_physical=[],
                         excluded=distribution.get("excluded", {}), unmanaged_preserved=[],
                         blocked=blocked, ownership_baseline="absent; no ownership decisions inferred"),
                     indent=2, sort_keys=True))
    return 0


def require_parity_baseline(distribution: dict) -> None:
    if distribution.get("version") == 3:
        raise RuntimeError("Version 3 parity mutation is on hold: no reviewed Claude ownership baseline. Use scoped ship for existing shelf routes.")


def dry_run(args: argparse.Namespace) -> int:
    # `ship --dry-run` passes the manifest it just made. The committed one is as
    # old as the last ship, and the Claude root may have changed since.
    distribution = load_json(
        Path(args.distribution).expanduser().resolve() if args.distribution else DIST
    )
    candidate = Path(args.candidate).expanduser().resolve()
    if distribution.get("version") == 3:
        return snapshot_dry_run(distribution, candidate)
    ensure_candidate(distribution, candidate)
    applied = verify_baseline(distribution)
    actions = Counter(
        "keep_link" if name in applied else entry["claude_action"]
        for name, entry in distribution["skills"].items()
    )
    changes = [
        {"name": name, "action": entry["claude_action"]}
        for name, entry in sorted(distribution["skills"].items())
        if name not in applied
        if entry["claude_action"]
        not in {"keep_link", "preserve_host_specific", "preserve_physical"}
    ]
    approval_required = [
        {
            "name": name,
            "action": entry["claude_action"],
            "decision": entry["parity_decision"],
        }
        for name, entry in sorted(distribution["skills"].items())
        if name not in applied
        if entry.get("parity_decision", {}).get("approval_required")
        and entry["claude_action"] != "keep_link"
    ]
    preserved_physical = sorted(
        name
        for name, entry in distribution["skills"].items()
        if entry["claude_action"] in {"preserve_physical", "preserve_host_specific"}
    )
    preserved_physical.extend(
        sorted(
            name
            for name, entry in distribution.get("excluded", {}).items()
            if entry["claude_action"] == "preserve_physical"
        )
    )
    print(
        json.dumps(
            {
                "candidate": str(candidate),
                "actions": dict(sorted(actions.items())),
                "changes": changes,
                "approval_required_changes": approval_required,
                "preserved_physical": sorted(preserved_physical),
                "excluded": distribution.get("excluded", {}),
                "unmanaged_preserved": sorted(distribution.get("unmanaged_claude", {})),
                "blocked": distribution.get("blocked", []),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def prepare(args: argparse.Namespace) -> int:
    distribution = load_json(DIST)
    require_parity_baseline(distribution)
    candidate = Path(args.candidate).expanduser().resolve()
    output = Path(args.output).expanduser().resolve(strict=False)
    ensure_candidate(distribution, candidate)
    verify_baseline(distribution)
    if output.exists() or output.is_symlink():
        raise RuntimeError(f"sandbox already exists: {output}")
    output.mkdir(parents=True)
    try:
        for name, entry in distribution["skills"].items():
            if entry["source"] == "host_specific":
                source = entry.get("claude_source")
                if source:
                    os.symlink(Path(source).resolve(strict=False), output / name)
                continue
            if entry["claude_action"] == "preserve_physical":
                os.symlink(CLAUDE / name, output / name)
                continue
            os.symlink(candidate / name, output / name)
        for name, entry in distribution.get("excluded", {}).items():
            if entry["claude_action"] == "preserve_physical":
                os.symlink(CLAUDE / name, output / name)
        for name in distribution.get("unmanaged_claude", {}):
            source = CLAUDE / name
            if source.exists() or source.is_symlink():
                os.symlink(source, output / name)
        write_json(
            output / ".parity-mirror.json",
            {"candidate": str(candidate), "source": str(CLAUDE)},
        )
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise
    print(output)
    return 0


def check(args: argparse.Namespace) -> int:
    required = args.required or []
    allowed_broken = set()
    if args.runtime in {"codex", "hermes"}:
        if not args.candidate:
            raise RuntimeError("Codex check requires --candidate")
        root = Path(args.candidate).expanduser().resolve()
    else:
        if not args.sandbox:
            raise RuntimeError("Claude check requires --sandbox")
        root = Path(args.sandbox).expanduser().resolve(strict=False)
        distribution = load_json(DIST)
        allowed_broken = {
            name
            for name, entry in distribution.get("unmanaged_claude", {}).items()
            if entry.get("ownership") == "broken_link"
            and equivalent_before(entry, snapshot_entry(root / name))
        }
    missing = [name for name in required if not (root / name / "SKILL.md").is_file()]
    broken = [
        path.name
        for path in root.iterdir()
        if path.is_symlink() and not path.exists() and path.name not in allowed_broken
    ]
    if missing or broken:
        raise RuntimeError(f"parity failure; missing={sorted(missing)} broken={sorted(broken)}")
    print(f"ok runtime={args.runtime} required={len(required)} root={root}")
    return 0


def apply(args: argparse.Namespace) -> int:
    distribution = load_json(DIST)
    require_parity_baseline(distribution)
    candidate = Path(args.candidate).expanduser().resolve()
    archive = Path(args.archive).expanduser().resolve(strict=False)
    ensure_candidate(distribution, candidate)
    if not ACTIVE.is_symlink() or ACTIVE.resolve(strict=False) != candidate:
        raise RuntimeError("candidate is not the active shared release")
    required_decisions = {
        name
        for name, entry in distribution["skills"].items()
        if entry.get("parity_decision", {}).get("approval_required")
        and entry["claude_action"] != "keep_link"
    }
    approved_decisions = set(args.approve_parity_decision or [])
    if approved_decisions != required_decisions:
        raise RuntimeError(
            "Claude parity decisions require exact approval; "
            f"required={sorted(required_decisions)} approved={sorted(approved_decisions)}"
        )
    with lifecycle_lock():
        verify_baseline(distribution)
        if archive.exists() or archive.is_symlink():
            raise RuntimeError(f"Claude archive already exists: {archive}")
        archive.mkdir(parents=True)
        changed = []
        try:
            for name, entry in sorted(distribution["skills"].items()):
                action = entry["claude_action"]
                if action in {"keep_link", "preserve_host_specific", "preserve_physical"}:
                    continue
                path = CLAUDE / name
                before = snapshot_entry(path)
                if path.is_symlink():
                    path.unlink()
                elif path.exists():
                    os.rename(path, archive / name)
                temporary = CLAUDE / f".{name}.next-{os.getpid()}"
                os.symlink(ACTIVE / name, temporary)
                os.replace(temporary, path)
                if not (path / "SKILL.md").is_file():
                    raise RuntimeError(f"Claude link readback failed: {name}")
                changed.append({"name": name, "before": before})
            write_json(
                CLAUDE_STATE,
                {
                    "version": 1,
                    "candidate": str(candidate),
                    "archive": str(archive),
                    "changed": changed,
                },
            )
        except Exception:
            restore(changed, archive)
            raise
    print(f"applied {len(changed)} Claude changes")
    return 0


def restore(changed: list[dict], archive: Path) -> None:
    for record in reversed(changed):
        name = record["name"]
        before = record["before"]
        path = CLAUDE / name
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            raise RuntimeError(f"refusing to overwrite unexpected Claude entry: {name}")
        if before is None:
            continue
        if before["kind"] == "directory":
            os.rename(archive / name, path)
        elif before["kind"] == "symlink":
            os.symlink(before["target"], path)
        else:
            raise RuntimeError(f"unsupported Claude rollback entry: {name}")


def rollback(_args: argparse.Namespace) -> int:
    with lifecycle_lock():
        if not CLAUDE_STATE.is_file():
            raise RuntimeError("no Claude parity state is available")
        state = load_json(CLAUDE_STATE)
        restore(state["changed"], Path(state["archive"]))
        write_json(
            CLAUDE_STATE,
            {"version": 1, "rolled_back": True, "restored": len(state["changed"])},
        )
    print(f"restored {len(state['changed'])} Claude entries")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    dry = commands.add_parser("dry-run")
    dry.add_argument("--candidate", required=True)
    dry.add_argument(
        "--distribution",
        help="read this distribution manifest instead of the resolved source manifest",
    )
    dry.set_defaults(handler=dry_run)
    prep = commands.add_parser("prepare")
    prep.add_argument("--candidate", required=True)
    prep.add_argument("--output", required=True)
    prep.set_defaults(handler=prepare)
    check_parser = commands.add_parser("check")
    check_parser.add_argument(
        "--runtime", choices=("hermes", "codex", "claude"), required=True
    )
    check_parser.add_argument("--candidate")
    check_parser.add_argument("--sandbox")
    check_parser.add_argument("--required", action="append")
    check_parser.set_defaults(handler=check)
    apply_parser = commands.add_parser("apply")
    apply_parser.add_argument("--candidate", required=True)
    apply_parser.add_argument("--archive", required=True)
    apply_parser.add_argument("--approve-parity-decision", action="append")
    apply_parser.set_defaults(handler=apply)
    rollback_parser = commands.add_parser("rollback")
    rollback_parser.set_defaults(handler=rollback)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        return args.handler(args)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"skill_route.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
