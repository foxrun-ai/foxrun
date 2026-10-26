#!/usr/bin/env python3
"""Build and verify a content-addressed shared-skill recovery manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from skill_catalog import authored_skills, load_policy, policy_path_for


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


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        input=input_bytes,
        capture_output=True,
    ).stdout


def digest_records(records: list[tuple[str, str, str]]) -> str:
    digest = hashlib.sha256()
    for path, mode, content_hash in sorted(records):
        digest.update(path.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(mode.encode("ascii"))
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def git_ref_skills(repo: Path, ref: str) -> dict[str, dict]:
    raw = git(repo, "ls-tree", "-r", "-z", "--full-tree", ref)
    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    has_skill: set[str] = set()
    nested = any(b"\tskills/" in item and item.endswith(b"/SKILL.md") for item in raw.split(b"\0"))
    for item in raw.split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, object_type, oid = metadata.decode("ascii").split()
        if object_type != "blob":
            continue
        path = raw_path.decode("utf-8", "surrogateescape")
        if nested:
            if not path.startswith("skills/"):
                continue
            path = path[len("skills/"):]
        if "/" not in path:
            continue
        skill, relative = path.split("/", 1)
        content_hash = hashlib.sha256(git(repo, "cat-file", "blob", oid)).hexdigest()
        grouped[skill].append((relative, mode, content_hash))
        if relative == "SKILL.md":
            has_skill.add(skill)

    return {
        name: {
            "digest": digest_records(grouped[name]),
            "file_count": len(grouped[name]),
            "kind": "git_tree",
        }
        for name in sorted(has_skill)
    }


def excluded(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in EXCLUDED_PARTS for part in relative.parts)


def filesystem_digest(path: Path) -> tuple[str, int]:
    records: list[tuple[str, str, str]] = []
    for current_root, dirs, files in os.walk(path, followlinks=False):
        root = Path(current_root)
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in EXCLUDED_PARTS and not excluded(root / name, path)
        )
        for name in sorted(files):
            candidate = root / name
            if excluded(candidate, path):
                continue
            relative = candidate.relative_to(path).as_posix()
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode):
                payload = os.readlink(candidate).encode("utf-8", "surrogateescape")
                mode = "120000"
            elif stat.S_ISREG(info.st_mode):
                payload = candidate.read_bytes()
                mode = "100755" if info.st_mode & stat.S_IXUSR else "100644"
            else:
                continue
            records.append((relative, mode, hashlib.sha256(payload).hexdigest()))
    return digest_records(records), len(records)


def filesystem_skills(root: Path) -> dict[str, dict]:
    result = {}
    if not root.exists():
        return result
    for path in sorted(root.iterdir(), key=lambda value: value.name):
        if path.name.startswith(".") or path.is_symlink() or not path.is_dir():
            continue
        if not (path / "SKILL.md").is_file():
            continue
        digest, count = filesystem_digest(path)
        entry = {"digest": digest, "file_count": count, "kind": "filesystem"}
        if (path / ".git").exists():
            entry["kind"] = "nested_git"
            try:
                entry["git_head"] = git(path, "rev-parse", "HEAD").decode().strip()
                entry["git_dirty"] = bool(
                    git(path, "status", "--porcelain", "--untracked-files=all").strip()
                )
            except subprocess.CalledProcessError:
                entry["git_head"] = None
                entry["git_dirty"] = True
        result[path.name] = entry
    return result


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def claude_entries(
    root: Path, active: Path, app_owned: frozenset[str] = frozenset()
) -> tuple[dict[str, dict], dict[str, dict]]:
    entries = {}
    physical_skills = {}
    if not root.exists():
        return entries, physical_skills
    active_resolved = active.resolve(strict=False)
    for path in sorted(root.iterdir(), key=lambda value: value.name):
        if path.is_symlink():
            target_text = os.readlink(path)
            target = (path.parent / target_text).resolve(strict=False)
            if not path.exists():
                ownership = "broken_link"
            elif is_within(target, active_resolved):
                ownership = "shared_link"
            else:
                ownership = "external_link"
            entries[path.name] = {
                "kind": "symlink",
                "ownership": ownership,
                "target": target_text,
                "resolved_target": str(target),
                "resolves": path.exists(),
            }
            continue
        if path.is_dir():
            if path.name in app_owned:
                # The Claude app owns this folder and rewrites it at any time.
                # Record that it is there. Pin no content.
                entries[path.name] = {"kind": "directory", "ownership": "app_owned"}
                continue
            digest, count = filesystem_digest(path)
            entries[path.name] = {
                "kind": "directory",
                "ownership": "physical_copy",
                "digest": digest,
                "file_count": count,
            }
            if (path / "SKILL.md").is_file():
                physical_skills[path.name] = {
                    "digest": digest,
                    "file_count": count,
                    "kind": "claude_physical",
                }
            continue
        entries[path.name] = {"kind": "file", "ownership": "unmanaged_file"}
    return entries, physical_skills


def build(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser().resolve()
    active = Path(args.active).expanduser().resolve()
    claude = Path(args.claude).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    sources: dict[str, dict[str, dict]] = {}
    ref_commits = {}
    for ref in args.ref:
        source = f"git:{ref}"
        sources[source] = git_ref_skills(repo, ref)
        ref_commits[ref] = git(repo, "rev-parse", ref).decode().strip()
    sources["active-shelf"] = filesystem_skills(active)
    claude_map, claude_physical = claude_entries(claude, active)
    sources["claude-physical"] = claude_physical
    if args.candidate:
        sources["candidate"] = filesystem_skills(
            authored_skills(Path(args.candidate).expanduser().resolve())
        )

    variants: dict[str, list[dict]] = defaultdict(list)
    for source, skills in sources.items():
        for name, metadata in skills.items():
            variants[name].append({"source": source, **metadata})

    skills = {}
    for name, rows in sorted(variants.items()):
        unique_digests = sorted({row["digest"] for row in rows})
        skills[name] = {
            "conflict": len(unique_digests) > 1,
            "resolution": None,
            "unique_digests": unique_digests,
            "variants": sorted(rows, key=lambda row: row["source"]),
        }

    manifest = {
        "version": 1,
        "repo": str(repo),
        "active_shelf": str(active),
        "claude_root": str(claude),
        "refs": ref_commits,
        "skills": skills,
        "claude_entries": claude_map,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    print(f"skills={len(skills)}")
    print(f"conflicts={sum(1 for item in skills.values() if item['conflict'])}")
    return 0


def verify(args: argparse.Namespace) -> int:
    manifest = json.loads(Path(args.manifest).expanduser().read_text(encoding="utf-8"))
    unresolved = []
    invalid = []
    for name, entry in manifest.get("skills", {}).items():
        if not entry.get("conflict"):
            continue
        resolution = entry.get("resolution")
        if not resolution:
            unresolved.append(name)
            continue
        sources = {variant["source"] for variant in entry.get("variants", [])}
        mode = resolution.get("mode", "selected")
        if mode == "host_specific":
            selected = set(resolution.get("selected_sources", []))
            if len(selected) < 2 or not selected.issubset(sources):
                invalid.append(name)
        elif resolution.get("selected_source") not in sources:
            invalid.append(name)
    if unresolved:
        print("unresolved conflicts: " + ", ".join(sorted(unresolved)), file=sys.stderr)
    if invalid:
        print("invalid resolutions: " + ", ".join(sorted(invalid)), file=sys.stderr)
    return 1 if unresolved or invalid else 0


def resolve(args: argparse.Namespace) -> int:
    source = Path(args.manifest).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    manifest = json.loads(source.read_text(encoding="utf-8"))
    host_specific = set(args.host_specific or [])
    unresolved = []

    for name, entry in manifest.get("skills", {}).items():
        if not entry.get("conflict"):
            continue
        sources = {variant["source"] for variant in entry.get("variants", [])}
        if name in host_specific:
            selected = [
                candidate
                for candidate in ("active-shelf", "claude-physical")
                if candidate in sources
            ]
            entry["resolution"] = {
                "mode": "host_specific",
                "selected_sources": selected,
                "rationale": "Preserve divergent host-owned working copies.",
            }
        elif "candidate" in sources:
            entry["resolution"] = {
                "mode": "selected",
                "selected_source": "candidate",
                "rationale": (
                    "Use the reviewed three-way Git reconciliation; original "
                    "variants remain reachable from recovery refs and snapshots."
                ),
            }
        else:
            unresolved.append(name)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    print(f"unresolved={len(unresolved)}")
    if unresolved:
        print("unresolved conflicts: " + ", ".join(sorted(unresolved)), file=sys.stderr)
        return 1
    return 0


def distribution(args: argparse.Namespace) -> int:
    candidate = Path(args.candidate).expanduser().resolve()
    active = Path(os.path.abspath(os.path.expanduser(args.active)))
    claude = Path(args.claude).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    policy_path = (
        Path(args.policy).expanduser().resolve()
        if args.policy
        else policy_path_for(candidate)
    )
    policy, policy_digest = load_policy(policy_path, candidate)
    publish = set(policy["publish"])
    excluded = policy["exclude"]
    preserve_physical = set(policy["claude_preserve_physical"])
    approval_required = policy["claude_approval_required"]
    host_specific = policy["host_specific"]
    app_owned = frozenset(policy.get("claude_app_owned", {}))

    candidate_skills = filesystem_skills(authored_skills(candidate))
    claude_map, _ = claude_entries(claude, active, app_owned)
    names = publish | set(host_specific)
    skills = {}
    blocked = []

    for name in sorted(names):
        current = claude_map.get(name)
        if name in host_specific:
            host_policy = host_specific[name]
            codex_source = str(
                Path(host_policy["codex_source"]).expanduser().resolve(strict=False)
            )
            if current is not None and current.get("ownership") != "physical_copy":
                raise RuntimeError(f"host-specific Claude skill is not physical: {name}")
            skills[name] = {
                "source": "host_specific",
                "policy_class": "host_specific",
                "codex_source": codex_source,
                "claude_source": host_policy.get("claude_source"),
                "claude_action": "preserve_host_specific",
                "claude_before": current,
                "managed": False,
            }
            continue

        desired_target = str(active / name)
        desired_resolved_target = str((active / name).resolve(strict=False))
        if name in preserve_physical:
            if current is None or current.get("ownership") != "physical_copy":
                raise RuntimeError(f"preserved Claude skill is not physical: {name}")
            action = "preserve_physical"
        elif current is None:
            action = "create_link"
        elif current["ownership"] == "physical_copy":
            action = "replace_physical_with_link"
        elif current["ownership"] == "broken_link":
            action = "repair_link"
        elif current["ownership"] == "shared_link":
            action = (
                "keep_link"
                if current.get("resolved_target") == desired_resolved_target
                else "retarget_link"
            )
        else:
            action = "blocked_unmanaged_entry"
            blocked.append(name)

        skills[name] = {
            "source": "skills_dojo",
            "policy_class": "publish",
            "digest": candidate_skills[name]["digest"],
            "file_count": candidate_skills[name]["file_count"],
            "codex": True,
            "claude": True,
            "claude_action": action,
            "claude_before": current,
            "claude_target": desired_target,
            "managed": action not in {"blocked_unmanaged_entry", "preserve_physical"},
        }
        if name in approval_required:
            skills[name]["parity_decision"] = {
                **approval_required[name],
                "approval_required": True,
            }

    excluded_claude = {}
    for name, exclusion in sorted(excluded.items()):
        current = claude_map.get(name)
        rule = exclusion["claude"]
        if rule == "absent" and current is not None:
            raise RuntimeError(f"excluded Claude skill must stay absent: {name}")
        if rule == "preserve_physical" and (
            current is None or current.get("ownership") != "physical_copy"
        ):
            raise RuntimeError(f"excluded Claude skill is not physical: {name}")
        excluded_claude[name] = {
            "policy_class": "exclude",
            "status": exclusion["status"],
            "reason": exclusion["reason"],
            "claude_action": rule,
            "claude_before": current,
        }

    unmanaged = {
        name: metadata
        for name, metadata in sorted(claude_map.items())
        if name not in names and name not in excluded
    }
    manifest = {
        "version": 2,
        "candidate": str(candidate),
        "active_shelf": str(active),
        "claude_root": str(claude),
        "policy": {
            "version": policy["version"],
            "path": str(policy_path),
            "digest": policy_digest,
        },
        "classification_counts": {
            "publish": len(publish),
            "exclude": len(excluded),
            "claude_preserve_physical": len(preserve_physical),
            "host_specific": len(host_specific),
            "claude_approval_required": len(approval_required),
            "claude_app_owned": len(app_owned),
        },
        "skills": skills,
        "excluded": excluded_claude,
        "unmanaged_claude": unmanaged,
        "blocked": blocked,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    print(f"publish={len(publish)}")
    print(f"exclude={len(excluded)}")
    print(f"managed={sum(1 for entry in skills.values() if entry['managed'])}")
    print(f"host_specific={len(host_specific)}")
    print(f"claude_preserve_physical={len(preserve_physical)}")
    print(f"blocked={len(blocked)}")
    return 1 if blocked else 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--repo", required=True)
    build_parser.add_argument("--ref", action="append", required=True)
    build_parser.add_argument("--active", required=True)
    build_parser.add_argument("--claude", required=True)
    build_parser.add_argument("--candidate")
    build_parser.add_argument("--output", required=True)
    build_parser.set_defaults(handler=build)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--manifest", required=True)
    verify_parser.set_defaults(handler=verify)
    resolve_parser = commands.add_parser("resolve")
    resolve_parser.add_argument("--manifest", required=True)
    resolve_parser.add_argument("--host-specific", action="append")
    resolve_parser.add_argument("--output", required=True)
    resolve_parser.set_defaults(handler=resolve)
    distribution_parser = commands.add_parser("distribution")
    distribution_parser.add_argument("--candidate", required=True)
    distribution_parser.add_argument("--active", required=True)
    distribution_parser.add_argument("--claude", required=True)
    distribution_parser.add_argument("--policy")
    distribution_parser.add_argument("--output", required=True)
    distribution_parser.set_defaults(handler=distribution)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
