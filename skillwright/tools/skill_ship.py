#!/usr/bin/env python3
"""Build, validate, publish, inspect, and roll back shared-skill releases."""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from skill_catalog import authored_skills, canary_checklist, load_policy, policy_path_for, read_catalog, catalog_scope, route_plan, apply_route_plan


SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
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


def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve(strict=False)


def env_link_path(name: str, default: str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.environ.get(name, default))))


def source_manifest_path(root: Path) -> Path:
    """Use the renamed manifest, or the current authoring manifest."""
    for name in ("shipped.yaml", "distribution.yaml"):
        candidate = root / "manifests" / name
        if candidate.is_file():
            return candidate
    return root / "manifests" / "shipped.yaml"


DOJO = env_path("SKILLS_DOJO_ROOT", "~/.foxrun/skillwright")
RELEASES = env_path("SKILL_RELEASES_ROOT", "~/.foxrun/skillwright/skill-releases")
STATE = env_path("SKILL_STATE_ROOT", "~/.foxrun/skillwright/skill-state")
ACTIVE = env_link_path("SKILLS_ACTIVE_PATH", "~/.foxrun/skills")
CLAUDE = env_link_path("SKILLS_CLAUDE_ROOT", "~/.claude/skills")
CODEX = env_link_path("SKILLS_CODEX_ROOT", "~/.codex/skills")
# What Claude and Codex read (g-source-installed-yours-and-skill-owners): one link per skill to the shelf.
AGENTS = env_link_path("SKILLS_AGENTS_ROOT", "~/.agents/skills")
LOCK_PATH = env_path("SKILLS_LOCK_PATH", str(STATE / "lifecycle.lock"))
STATE_FILE = STATE / "release-state.json"
TRANSACTION_FILE = STATE / "release-transaction.json"
CODEX_STATE_FILE = STATE / "codex-state.json"
SHIPS = STATE / "ships"
DIST = source_manifest_path(DOJO)
DIST_RELPATH = DIST.relative_to(DOJO).as_posix()
POLICY = policy_path_for(DOJO)
PARITY = env_path(
    "SKILLS_PARITY_TOOL", str(Path(__file__).resolve().with_name("skill_route.py"))
)


def person_root_for(dojo: Path) -> Path | None:
    """The person's own skill source (g-source-installed-yours-and-skill-owners).

    SKILLS_PERSON_ROOT names it; an empty value turns it off. Without it, only the
    installed home uses <portfolio>/skillwright, so an isolated Dojo never reads it.
    """
    value = os.environ.get("SKILLS_PERSON_ROOT")
    if value is not None:
        return Path(value).expanduser().resolve(strict=False) if value else None
    if dojo != Path("~/.foxrun/skillwright").expanduser().resolve(strict=False):
        return None
    portfolio = os.environ.get("FOXRUN_PORTFOLIO", "~/foxrun")
    candidate = (Path(portfolio).expanduser() / "skillwright").resolve(strict=False)
    return candidate if any((candidate / part).is_dir() for part in ("skills", "retired")) else None


PERSON = person_root_for(DOJO)


def source_home(name: str) -> tuple[Path, str]:
    """Return the repository that holds a skill's source and its owner.

    The person's copy wins over a product skill with the same name, so a product
    update never replaces the person's skill.
    """
    if PERSON is not None and (PERSON / "skills" / name / "SKILL.md").is_file():
        return PERSON, "person"
    return DOJO, "product"


def skill_owner(name: str) -> str:
    """Owner for a released skill; a skill with no product source is the person's."""
    home, owner = source_home(name)
    if owner == "product" and not (DOJO / "skills" / name / "SKILL.md").is_file():
        return "person"
    return owner


def removed_person_skills(record: dict) -> list[str]:
    """Remove only proven person skills absent from both current source trees.

    Missing ownership is not proof of person ownership. A product source protects
    the skill even when the person previously shipped an override of that name.
    """
    if PERSON is None:
        return []
    if not PERSON.is_dir():
        raise RuntimeError("Person source is unavailable; refusing skill removals: " + str(PERSON))
    removed = []
    for name, entry in sorted(record["skills"].items()):
        if entry.get("owner") != "person":
            continue
        if not SAFE_ID.fullmatch(name) or name != Path(name).name:
            # Never remove a skill whose name is unsafe as a path; keep it and ship the rest.
            continue
        if any((home / "skills" / name / "SKILL.md").is_file() for home in (PERSON, DOJO)):
            continue
        if git_in(PERSON, "status", "--porcelain", "--", "skills/" + name, "retired/" + name):
            raise RuntimeError("Commit the person skill removal before shipping: " + name)
        removed.append(name)
    return removed


def git_in(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        text=True,
        capture_output=True,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    ).stdout.strip()


class ShipStepError(RuntimeError):
    def __init__(self, message: str, output: object | None = None):
        super().__init__(message)
        self.output = output


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(DOJO), *args],
        check=True,
        text=True,
        capture_output=True,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    ).stdout.strip()


@contextmanager
def exported_head(ref: str = "HEAD"):
    commit = git("rev-parse", ref)
    with tempfile.TemporaryDirectory(prefix="skills-dojo-head-") as temporary:
        temporary_root = Path(temporary)
        archive = temporary_root / "source.tar"
        source_root = temporary_root / "source"
        source_root.mkdir()
        subprocess.run(
            [
                "git",
                "-C",
                str(DOJO),
                "archive",
                "--format=tar",
                f"--output={archive}",
                commit,
            ],
            check=True,
            capture_output=True,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
        subprocess.run(
            ["tar", "-xf", str(archive), "-C", str(source_root)],
            check=True,
            capture_output=True,
        )
        # Git archives preserve link text, but the canonical catalog belongs outside this repository.
        alias = source_root / 'config/catalog.yaml'
        if alias.is_symlink():
            from catalog_state import approved_catalog, canonical
            _raw, ident, _approval = approved_catalog(DOJO)
            if os.readlink(alias) != '../../config/catalog.yaml':
                raise RuntimeError('Exported catalog alias changed; preserve ../../config/catalog.yaml.')
            payload = canonical(DOJO).read_bytes()
            if hashlib.sha256(payload).hexdigest() != ident:
                raise RuntimeError('Catalog version changed during source export.')
            owner = temporary_root / 'config/catalog.yaml'
            owner.parent.mkdir(parents=True, exist_ok=True); owner.write_bytes(payload)
        yield source_root, commit


@contextmanager
def lifecycle_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"skill lifecycle lock is busy: {LOCK_PATH}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_json(path: Path) -> dict:
    if path == POLICY:
        return read_catalog(path, DOJO)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def remove_file(path: Path) -> None:
    path.unlink()
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def file_records(path: Path) -> list[tuple[str, str, str]]:
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
                (relative.as_posix(), mode, hashlib.sha256(payload).hexdigest())
            )
    return records


def digest_tree(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    records = file_records(path)
    for relative, mode, content_hash in sorted(records):
        digest.update(relative.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(mode.encode("ascii"))
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), len(records)


def validate_frontmatter(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise RuntimeError(f"missing YAML frontmatter: {path}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise RuntimeError(f"unterminated YAML frontmatter: {path}") from exc
    seen = set()
    for line in lines[1:end]:
        match = re.match(r"^([A-Za-z0-9_-]+):", line)
        if not match:
            continue
        key = match.group(1)
        if key in seen:
            raise RuntimeError(f"duplicate frontmatter key '{key}': {path}")
        seen.add(key)
    missing = {"name", "description"} - seen
    if missing:
        raise RuntimeError(
            f"missing frontmatter keys {sorted(missing)}: {path}"
        )


def validate_distribution_policy(
    distribution: dict, source_root: Path = DOJO
) -> tuple[dict, str]:
    policy, policy_digest = load_policy(policy_path_for(source_root), source_root)
    manifest_policy = distribution.get("policy", {})
    snapshot = distribution.get("version") == 3
    if distribution.get("version") not in {2, 3}:
        raise RuntimeError("distribution manifest version must be 2 or 3")
    if snapshot:
        from skill_scoped import record_digest
        if distribution.get("digest") != record_digest(distribution["skills"]):
            raise RuntimeError("snapshot record digest mismatch")
    if manifest_policy.get("version") != policy["version"]:
        raise RuntimeError("distribution policy version mismatch")
    if manifest_policy.get("digest") != policy_digest:
        raise RuntimeError("distribution policy digest mismatch")

    publish = set(policy["publish"])
    exclude = set(policy["exclude"])
    host_specific = set(policy["host_specific"])
    skills = distribution.get("skills", {})
    manifest_publish = {
        name for name, entry in skills.items() if entry.get("source") == "skills_dojo"
    }
    manifest_host = {
        name for name, entry in skills.items() if entry.get("source") == ("host_snapshot" if snapshot else "host_specific")
    }
    unknown_sources = sorted(
        name
        for name, entry in skills.items()
        if entry.get("source") not in {"skills_dojo", "host_snapshot" if snapshot else "host_specific"}
    )
    if unknown_sources:
        raise RuntimeError("unknown distribution sources: " + ", ".join(unknown_sources))
    if manifest_publish != publish:
        missing = sorted(publish - manifest_publish)
        extra = sorted(manifest_publish - publish)
        raise RuntimeError(
            f"distribution completeness failure; missing={missing} extra={extra}"
        )
    if manifest_host != host_specific:
        missing = sorted(host_specific - manifest_host)
        extra = sorted(manifest_host - host_specific)
        raise RuntimeError(
            f"host-specific completeness failure; missing={missing} extra={extra}"
        )
    if set(distribution.get("excluded", {})) != exclude:
        raise RuntimeError("distribution exclusions do not match publication policy")
    overlap = sorted(set(skills) & exclude)
    if overlap:
        raise RuntimeError("excluded skills are distributed: " + ", ".join(overlap))

    for name in sorted(publish):
        source = authored_skills(source_root) / name
        validate_frontmatter(source / "SKILL.md")
        digest, count = digest_tree(source)
        entry = skills[name]
        expected_digest = entry.get("source_digest", entry.get("digest")) if snapshot else entry.get("digest")
        expected_count = entry.get("source_file_count", entry.get("file_count")) if snapshot else entry.get("file_count")
        if expected_digest != digest or expected_count != count:
            raise RuntimeError(f"distribution source digest is stale: {name}")
        if snapshot and entry.get('standard_snapshots'):
            from skill_scoped import source_entry
            expected=source_entry(sys.modules[__name__],source,source_root)
            if expected.get('standard_snapshots')!=entry['standard_snapshots']:
                raise RuntimeError('distribution standard snapshot is stale: '+name)
            if not entry.get('source_drift') and (expected['digest'],expected['file_count'])!=(entry['digest'],entry['file_count']):
                raise RuntimeError('distribution packaged digest is stale: '+name)

    if "fleet" in publish:
        if "herd" not in manifest_publish:
            raise RuntimeError("published fleet requires published sibling herd")
        if not os.access(authored_skills(source_root) / "herd" / "bin" / "herd", os.X_OK):
            raise RuntimeError("published fleet requires executable herd/bin/herd")
    return policy, policy_digest


def require_clean_main(*, require_sync: bool = True) -> str:
    if git("branch", "--show-current") != "main":
        raise RuntimeError("Skillwright must be on main before building")
    try:
        upstream = git("rev-parse", "@{u}")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Skillwright main has no upstream") from exc
    head = git("rev-parse", "HEAD")
    if require_sync and upstream != head:
        raise RuntimeError("Skillwright main is not synchronized with its upstream")
    return head


def release_path(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or "/" in value:
        return candidate.resolve(strict=False)
    if not SAFE_ID.fullmatch(value):
        raise RuntimeError(f"unsafe release id: {value}")
    return RELEASES / value


def validate_skill_payloads(candidate: Path, release_manifest: dict) -> None:
    for name, expected in release_manifest["skills"].items():
        path = candidate / name
        if path.is_symlink():
            if expected["source"] != "host_specific":
                raise RuntimeError(f"unexpected managed symlink: {name}")
            if not path.exists() or not (path / "SKILL.md").is_file():
                raise RuntimeError(f"broken host-specific skill: {name}")
            continue
        if not path.is_dir() or not (path / "SKILL.md").is_file():
            raise RuntimeError(f"missing SKILL.md: {name}")
        validate_frontmatter(path / "SKILL.md")
        if any(part.name == ".git" for part in path.rglob(".git")):
            raise RuntimeError(f"embedded Git metadata in managed skill: {name}")
        digest, count = digest_tree(path)
        if digest != expected["digest"] or count != expected["file_count"]:
            raise RuntimeError(f"content drift in candidate skill: {name}")


def validate_candidate(
    candidate: Path,
    require_current_policy: bool = False,
    *,
    source_root: Path | None = None,
    source_commit: str | None = None,
    distribution_override: Path | None = None,
) -> dict:
    if require_current_policy and source_root is None:
        with exported_head() as (export, commit):
            return validate_candidate(
                candidate,
                require_current_policy=True,
                source_root=export,
                source_commit=commit,
                distribution_override=distribution_override,
            )
    if not candidate.is_dir():
        raise RuntimeError(f"candidate is not a directory: {candidate}")
    release_manifest_path = candidate / ".release-manifest.json"
    if not release_manifest_path.is_file():
        raise RuntimeError(f"candidate has no release manifest: {candidate}")
    release_manifest = load_json(release_manifest_path)
    if release_manifest.get("version") == 3:
        from skill_scoped import validate_record
        validate_record(sys.modules[__name__], candidate)
        if require_current_policy:
            # Version-three manifests are lifecycle state, not the stale record in a source Git archive.
            distribution = load_json(distribution_override or DIST)
            _policy, policy_digest = validate_distribution_policy(distribution, source_root)
            if distribution != release_manifest:
                raise RuntimeError("snapshot candidate and shipped record differ")
            if release_manifest.get("policy", {}).get("digest") != policy_digest:
                raise RuntimeError("snapshot policy digest is not current")
        return release_manifest
    if release_manifest.get("version") == 2:
        classifications = release_manifest.get("classifications", {})
        published = set(classifications.get("publish", []))
        excluded = set(classifications.get("exclude", []))
        host_specific = set(classifications.get("host_specific", []))
        expected_policy_names = published | host_specific
        if set(release_manifest["skills"]) != expected_policy_names:
            raise RuntimeError("candidate release policy membership mismatch")
        overlap = sorted(set(release_manifest["skills"]) & excluded)
        if overlap:
            raise RuntimeError("candidate contains excluded skills: " + ", ".join(overlap))
        if require_current_policy:
            distribution = load_json(
                distribution_override or source_root / DIST_RELPATH
            )
            policy, policy_digest = validate_distribution_policy(distribution, source_root)
            if release_manifest.get("dojo_commit") != source_commit:
                raise RuntimeError("candidate was not built from the current Dojo commit")
            if release_manifest.get("policy", {}).get("digest") != policy_digest:
                raise RuntimeError("candidate policy digest is not current")
            if published != set(policy["publish"]):
                raise RuntimeError("candidate publish classification is not current")
            if excluded != set(policy["exclude"]):
                raise RuntimeError("candidate exclusion classification is not current")
            if host_specific != set(policy["host_specific"]):
                raise RuntimeError("candidate host-specific classification is not current")
            for name, expected in release_manifest["skills"].items():
                current = distribution["skills"][name]
                if expected["source"] == "skills_dojo":
                    if (
                        expected.get("digest") != current.get("digest")
                        or expected.get("file_count") != current.get("file_count")
                    ):
                        raise RuntimeError(f"candidate source is stale: {name}")
                elif expected.get("target") != str(
                    Path(current["codex_source"]).expanduser().resolve(strict=False)
                ):
                    raise RuntimeError(f"candidate host-specific source is stale: {name}")
    elif require_current_policy:
        raise RuntimeError("legacy candidate has no publication policy provenance")
    expected_names = set(release_manifest["skills"])
    actual_names = {
        path.name
        for path in candidate.iterdir()
        if path.name != ".release-manifest.json"
    }
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise RuntimeError(f"candidate membership mismatch; missing={missing} extra={extra}")

    validate_skill_payloads(candidate, release_manifest)
    if release_manifest.get("version") == 2 and "fleet" in expected_names:
        if "herd" not in expected_names:
            raise RuntimeError("candidate fleet requires sibling herd")
        if not os.access(candidate / "herd" / "bin" / "herd", os.X_OK):
            raise RuntimeError("candidate herd/bin/herd is not executable")
    return release_manifest


def make_read_only(path: Path) -> None:
    for current_root, dirs, files in os.walk(path, followlinks=False):
        root = Path(current_root)
        for name in files:
            candidate = root / name
            if candidate.is_symlink():
                continue
            mode = candidate.stat().st_mode
            candidate.chmod(0o555 if mode & stat.S_IXUSR else 0o444)
        for name in dirs:
            candidate = root / name
            if not candidate.is_symlink():
                candidate.chmod(0o555)
    path.chmod(0o555)


def build(args: argparse.Namespace) -> int:
    if DIST.is_file() and load_json(DIST).get("version") == 3:
        raise RuntimeError("Full build is on hold: version 3 records support scoped ship; X5 must prove host vendor routes.")
    with lifecycle_lock():
        distribution_override = getattr(args, "distribution_override", None)
        head = require_clean_main(require_sync=distribution_override is None)
        with exported_head(head) as (source_root, source_commit):
            distribution = load_json(
                distribution_override or source_root / DIST_RELPATH
            )
            policy, policy_digest = validate_distribution_policy(distribution, source_root)
            release_id = args.release_id or (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + head[:12]
            )
            if not SAFE_ID.fullmatch(release_id):
                raise RuntimeError(f"unsafe release id: {release_id}")
            final = RELEASES / release_id
            if final.exists() or final.is_symlink():
                raise RuntimeError(f"release already exists: {release_id}")
            RELEASES.mkdir(parents=True, exist_ok=True)
            temporary = Path(
                tempfile.mkdtemp(prefix=f".build-{release_id}-", dir=RELEASES)
            )
            try:
                release_skills = {}
                for name, entry in distribution["skills"].items():
                    destination = temporary / name
                    if entry["source"] == "host_specific":
                        source = Path(entry["codex_source"]).expanduser().resolve(
                            strict=False
                        )
                        if not (source / "SKILL.md").is_file():
                            raise RuntimeError(
                                f"host-specific source is unavailable: {name}"
                            )
                        os.symlink(source, destination)
                        release_skills[name] = {
                            "source": "host_specific",
                            "target": str(source),
                        }
                        continue
                    source = authored_skills(source_root) / name
                    if not (source / "SKILL.md").is_file():
                        raise RuntimeError(f"Skillwright source is unavailable: {name}")
                    shutil.copytree(
                        source,
                        destination,
                        symlinks=True,
                        ignore=shutil.ignore_patterns(*EXCLUDED_PARTS),
                    )
                    digest, count = digest_tree(destination)
                    release_skills[name] = {
                        "source": "skills_dojo",
                        "digest": digest,
                        "file_count": count,
                    }
                write_json(
                    temporary / ".release-manifest.json",
                    {
                        "version": 2,
                        "release_id": release_id,
                        "dojo_commit": head,
                        "policy": {
                            "version": policy["version"],
                            "path": str(
                                policy_path_for(source_root).relative_to(source_root)
                            ),
                            "digest": policy_digest,
                        },
                        "classifications": {
                            "publish": policy["publish"],
                            "exclude": sorted(policy["exclude"]),
                            "host_specific": sorted(policy["host_specific"]),
                        },
                        "canary_checklist": canary_checklist(),
                        "skills": release_skills,
                    },
                )
                validate_candidate(
                    temporary,
                    require_current_policy=True,
                    source_root=source_root,
                    source_commit=source_commit,
                    distribution_override=distribution_override,
                )
                make_read_only(temporary)
                os.replace(temporary, final)
            except Exception:
                if temporary.exists():
                    shutil.rmtree(temporary, ignore_errors=True)
                raise
        if not getattr(args, "quiet", False):
            print(release_id)
        return 0


def validate(args: argparse.Namespace) -> int:
    candidate = release_path(args.candidate)
    manifest = validate_candidate(candidate, require_current_policy=True)
    print(f"valid {manifest['release_id']} skills={len(manifest['skills'])}")
    return 0


def active_target() -> Path | None:
    if not ACTIVE.is_symlink():
        return None
    return ACTIVE.resolve(strict=False)


def switch_link(target: Path) -> None:
    temporary = ACTIVE.with_name(f".{ACTIVE.name}.next-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    # Measure from the real parent: a symlinked ancestor (macOS /var -> /private/var)
    # makes a link relative to the unresolved parent point at the wrong place.
    os.symlink(os.path.relpath(target.resolve(strict=False), temporary.parent.resolve()), temporary)
    os.replace(temporary, ACTIVE)
    if ACTIVE.resolve(strict=False) != target.resolve(strict=False):
        raise RuntimeError("active release readback mismatch")


def path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def state_snapshot() -> dict | None:
    if STATE_FILE.is_symlink():
        raise RuntimeError(f"release state path must not be a symlink: {STATE_FILE}")
    if STATE_FILE.is_file():
        return load_json(STATE_FILE)
    if STATE_FILE.exists():
        raise RuntimeError(f"release state path is not a regular file: {STATE_FILE}")
    return None


def release_snapshot(path: Path, kind: str = "release") -> dict:
    resolved = path.resolve(strict=False)
    if not path_within(resolved, RELEASES):
        raise RuntimeError(f"release target is outside the release root: {resolved}")
    if not resolved.is_dir():
        raise RuntimeError(f"release target is unavailable: {resolved}")
    digest, count = digest_tree(resolved)
    return {
        "kind": kind,
        "path": str(resolved),
        "digest": digest,
        "file_count": count,
    }


def directory_snapshot(path: Path, storage_path: Path) -> dict:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"active directory is unavailable: {path}")
    digest, count = digest_tree(path)
    return {
        "kind": "directory",
        "path": str(path),
        "storage_path": str(storage_path),
        "digest": digest,
        "file_count": count,
    }


def missing_snapshot() -> dict:
    return {"kind": "missing", "path": str(ACTIVE)}


def tree_matches(path: Path, snapshot: dict) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    digest, count = digest_tree(path)
    return digest == snapshot.get("digest") and count == snapshot.get("file_count")


def active_matches(snapshot: dict) -> bool:
    kind = snapshot.get("kind")
    if kind in {"release", "release_snapshot"}:
        return (
            ACTIVE.is_symlink()
            and active_target() == Path(snapshot["path"]).resolve(strict=False)
            and tree_matches(Path(snapshot["path"]), snapshot)
        )
    if kind == "directory":
        return tree_matches(ACTIVE, snapshot)
    if kind == "missing":
        return not ACTIVE.exists() and not ACTIVE.is_symlink()
    raise RuntimeError(f"unknown active snapshot kind: {kind}")


def stored_directory_matches(snapshot: dict) -> bool:
    storage = snapshot.get("storage_path")
    return bool(storage) and tree_matches(Path(storage), snapshot)


def validate_transaction_snapshot(snapshot: object) -> None:
    if not isinstance(snapshot, dict):
        raise RuntimeError("release transaction snapshot must be an object")
    kind = snapshot.get("kind")
    if kind in {"release", "release_snapshot"}:
        path = Path(snapshot.get("path", ""))
        if not path.is_absolute() or not path_within(path, RELEASES):
            raise RuntimeError("release transaction target is outside the release root")
    elif kind == "directory":
        if snapshot.get("path") != str(ACTIVE):
            raise RuntimeError("release transaction directory has the wrong active path")
        storage = Path(snapshot.get("storage_path", ""))
        if not storage.is_absolute() or storage == ACTIVE:
            raise RuntimeError("release transaction directory storage path is invalid")
    elif kind == "missing":
        if snapshot.get("path") != str(ACTIVE):
            raise RuntimeError("release transaction missing snapshot has the wrong path")
        return
    else:
        raise RuntimeError(f"unknown release transaction snapshot kind: {kind}")
    if (
        not isinstance(snapshot.get("digest"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", snapshot["digest"])
        or not isinstance(snapshot.get("file_count"), int)
        or snapshot["file_count"] < 0
    ):
        raise RuntimeError("release transaction snapshot fingerprint is invalid")


def read_transaction() -> dict | None:
    if TRANSACTION_FILE.is_symlink():
        raise RuntimeError(
            f"release transaction path must not be a symlink: {TRANSACTION_FILE}"
        )
    if TRANSACTION_FILE.is_file():
        transaction = load_json(TRANSACTION_FILE)
        if transaction.get("version") != 1:
            raise RuntimeError("unknown release transaction version")
        if transaction.get("operation") not in {"publish", "rollback"}:
            raise RuntimeError("unknown release transaction operation")
        if transaction.get("active_path") != str(ACTIVE):
            raise RuntimeError("release transaction belongs to another active path")
        validate_transaction_snapshot(transaction.get("active_before"))
        validate_transaction_snapshot(transaction.get("active_after"))
        if not isinstance(transaction.get("state_after"), dict):
            raise RuntimeError("release transaction has no expected final state")
        return transaction
    if TRANSACTION_FILE.exists():
        raise RuntimeError(f"release transaction path is not a regular file: {TRANSACTION_FILE}")
    return None


def validate_recovery_state(transaction: dict) -> None:
    before = transaction.get("state_before")
    after = transaction.get("state_after")
    current = state_snapshot()
    if current != before and current != after:
        raise RuntimeError("release state drifted after the interrupted transaction")


def validate_recovery_active(transaction: dict) -> None:
    before = transaction["active_before"]
    after = transaction["active_after"]
    if active_matches(before) or active_matches(after):
        return
    # A directory can be parked before the next atomic pointer operation.
    if not ACTIVE.exists() and not ACTIVE.is_symlink():
        if stored_directory_matches(before) or stored_directory_matches(after):
            return
    raise RuntimeError("active pointer or preserved directory drifted after interruption")


def move_active_directory_to_storage(snapshot: dict) -> None:
    storage = Path(snapshot["storage_path"])
    if storage.exists() or storage.is_symlink():
        raise RuntimeError(f"directory storage path drifted: {storage}")
    storage.parent.mkdir(parents=True, exist_ok=True)
    os.rename(ACTIVE, storage)


def restore_active_snapshot(before: dict, after: dict) -> None:
    if active_matches(before):
        return
    before_kind = before["kind"]
    # Validate every restoration source before changing the working pointer.
    if before_kind in {"release", "release_snapshot"}:
        target = Path(before["path"])
        if not tree_matches(target, before):
            raise RuntimeError("preserved release snapshot changed during recovery")
    elif before_kind == "directory":
        if not stored_directory_matches(before):
            raise RuntimeError("preserved active directory changed during recovery")
    elif before_kind != "missing":
        raise RuntimeError(f"unknown recovery snapshot kind: {before_kind}")

    after_kind = after["kind"]
    after_is_active = active_matches(after)
    if not after_is_active and (ACTIVE.exists() or ACTIVE.is_symlink()):
        raise RuntimeError("active path changed during recovery")
    if not after_is_active:
        # The process stopped between parking a directory and switching the pointer.
        pass
    elif after_kind == "directory":
        move_active_directory_to_storage(after)

    if before_kind in {"release", "release_snapshot"}:
        # os.replace inside switch_link keeps release-to-release recovery atomic.
        switch_link(target)
    elif before_kind == "directory":
        if after_is_active and after_kind in {"release", "release_snapshot"}:
            ACTIVE.unlink()
        storage = Path(before["storage_path"])
        os.rename(storage, ACTIVE)
    elif after_is_active and after_kind in {"release", "release_snapshot"}:
        ACTIVE.unlink()
    if not active_matches(before):
        raise RuntimeError("active path recovery readback mismatch")


def restore_state_snapshot(snapshot: dict | None) -> None:
    current = state_snapshot()
    if current == snapshot:
        return
    if snapshot is None:
        remove_file(STATE_FILE)
    else:
        write_json(STATE_FILE, snapshot)


def recover_transaction_unlocked() -> bool:
    transaction = read_transaction()
    if transaction is None:
        return False
    validate_recovery_state(transaction)
    validate_recovery_active(transaction)
    restore_active_snapshot(transaction["active_before"], transaction["active_after"])
    restore_state_snapshot(transaction.get("state_before"))
    remove_file(TRANSACTION_FILE)
    return True


def begin_transaction(operation: str, active_before: dict, active_after: dict,
                      state_before: dict | None, state_after: dict) -> None:
    if read_transaction() is not None:
        raise RuntimeError("an unfinished release transaction requires recovery")
    write_json(
        TRANSACTION_FILE,
        {
            "version": 1,
            "operation": operation,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "active_path": str(ACTIVE),
            "active_before": active_before,
            "active_after": active_after,
            "state_before": state_before,
            "state_after": state_after,
        },
    )


def require_reviewed_authorization(args: argparse.Namespace, expected: str) -> None:
    if getattr(args, "authorize_reviewed", None) != expected:
        raise RuntimeError(
            "reviewed authorization must exactly match the release id: " + expected
        )


def validate_repairable_active(previous_target: Path, candidate: Path,
                               accepted_names: list[str] | None) -> list[str]:
    manifest_path = previous_target / ".release-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise RuntimeError("active drift repair requires a regular release manifest")
    manifest = load_json(manifest_path)
    if manifest.get("version") != 2:
        raise RuntimeError("active drift repair requires a version 2 release manifest")
    classifications = manifest.get("classifications", {})
    published = set(classifications.get("publish", []))
    host_specific = set(classifications.get("host_specific", []))
    excluded = set(classifications.get("exclude", []))
    declared = published | host_specific
    if not SAFE_ID.fullmatch(str(manifest.get("release_id", ""))):
        raise RuntimeError("active drift repair found an invalid release id")
    if declared & excluded or published & host_specific:
        raise RuntimeError("active drift repair found overlapping classifications")
    if set(manifest.get("skills", {})) != declared:
        raise RuntimeError("active drift repair found malformed manifest membership")
    actual = {
        path.name
        for path in previous_target.iterdir()
        if path.name != ".release-manifest.json"
    }
    missing = sorted(set(manifest["skills"]) - actual)
    extra = sorted(actual - set(manifest["skills"]))
    accepted = sorted(set(accepted_names or []))
    if missing or not extra or accepted != extra:
        raise RuntimeError(
            "active drift is not the exact reviewed extra-skill set; "
            f"missing={missing} extra={extra} accepted={accepted}"
        )
    validate_skill_payloads(previous_target, manifest)
    if "fleet" in declared and (
        "herd" not in declared
        or not os.access(previous_target / "herd" / "bin" / "herd", os.X_OK)
    ):
        raise RuntimeError("active drift repair found an invalid fleet/herd release")
    successor = load_json(candidate / ".release-manifest.json")
    for name in extra:
        old_path = previous_target / name
        if old_path.is_symlink() or not (old_path / "SKILL.md").is_file():
            raise RuntimeError(f"repair extra is not a regular skill directory: {name}")
        validate_frontmatter(old_path / "SKILL.md")
        old_digest, old_count = digest_tree(old_path)
        expected = successor.get("skills", {}).get(name)
        if (
            not expected
            or expected.get("source") != "skills_dojo"
            or expected.get("digest") != old_digest
            or expected.get("file_count") != old_count
        ):
            raise RuntimeError(
                f"repair successor does not preserve exact active skill content: {name}"
            )
    return extra


def publish(args: argparse.Namespace) -> int:
    if load_json(release_path(args.candidate) / ".release-manifest.json").get("version") == 3:
        raise RuntimeError("Full publication is on hold: version 3 records require scoped ship and existing consumer routes.")
    candidate = release_path(args.candidate)
    with lifecycle_lock():
        recover_transaction_unlocked()
        require_clean_main()
        manifest = validate_candidate(candidate, require_current_policy=True)
        require_reviewed_authorization(args, manifest["release_id"])
        previous = None
        preserved_directory = None
        state_before = state_snapshot()
        if ACTIVE.is_symlink():
            previous_target = active_target()
            if previous_target is None:
                raise RuntimeError("active release pointer is unreadable")
            try:
                validate_candidate(previous_target)
                active_before = release_snapshot(previous_target)
                previous = {"kind": "release", "path": str(previous_target)}
            except (OSError, RuntimeError, KeyError, ValueError, json.JSONDecodeError):
                active_before = release_snapshot(previous_target, "release_snapshot")
                attestation = getattr(args, "accept_active_drift_digest", None)
                if attestation != active_before["digest"]:
                    raise RuntimeError(
                        "active release is invalid; reviewed repair requires "
                        "--accept-active-drift-digest " + active_before["digest"]
                    )
                validate_repairable_active(
                    previous_target,
                    candidate,
                    getattr(args, "accept_active_drift_skill", None),
                )
                previous = {
                    "kind": "release_snapshot",
                    "path": str(previous_target),
                    "digest": active_before["digest"],
                    "file_count": active_before["file_count"],
                }
        elif ACTIVE.exists():
            if not args.preserve_existing_to:
                raise RuntimeError(
                    "first activation requires --preserve-existing-to for the current directory"
                )
            preserved_directory = Path(args.preserve_existing_to).expanduser().resolve(strict=False)
            if preserved_directory.exists() or preserved_directory.is_symlink():
                raise RuntimeError(f"preservation path already exists: {preserved_directory}")
            preserved_directory.parent.mkdir(parents=True, exist_ok=True)
            active_before = directory_snapshot(ACTIVE, preserved_directory)
            previous = {
                "kind": "directory",
                "path": str(preserved_directory),
                "digest": active_before["digest"],
                "file_count": active_before["file_count"],
            }
        else:
            active_before = missing_snapshot()
        active_after = release_snapshot(candidate)
        state_after = {
            "version": 1,
            "current": {"kind": "release", "path": str(candidate)},
            "previous": previous,
            "release_id": manifest["release_id"],
        }
        begin_transaction("publish", active_before, active_after, state_before, state_after)
        try:
            if preserved_directory is not None:
                os.rename(ACTIVE, preserved_directory)
            switch_link(candidate)
            write_json(STATE_FILE, state_after)
            remove_file(TRANSACTION_FILE)
        except Exception as exc:
            try:
                recover_transaction_unlocked()
            except Exception as recovery_exc:
                raise RuntimeError(
                    f"publish failed ({exc}); automatic recovery failed ({recovery_exc})"
                ) from recovery_exc
            raise
        if not getattr(args, "quiet", False):
            print(f"active {manifest['release_id']}")
        return 0


def rollback(args: argparse.Namespace) -> int:
    if STATE_FILE.is_file() and load_json(STATE_FILE).get("scoped"):
        from skill_scoped import rollback_one
        return rollback_one(sys.modules[__name__], args)
    with lifecycle_lock():
        recover_transaction_unlocked()
        state = state_snapshot()
        if state is None:
            raise RuntimeError("no release state is available")
        previous = state.get("previous")
        if not previous:
            raise RuntimeError("no previous release is available")
        current = state.get("current")
        if not current or current.get("kind") not in {
            "release", "release_snapshot", "directory"
        }:
            raise RuntimeError("unknown current-state kind")
        current_path = Path(current["path"])
        if current["kind"] in {"release", "release_snapshot"}:
            if not ACTIVE.is_symlink() or active_target() != current_path.resolve():
                raise RuntimeError("active release drift; rollback stopped")
            if current["kind"] == "release":
                validate_candidate(current_path)
                active_before = release_snapshot(current_path)
            else:
                active_before = release_snapshot(current_path, "release_snapshot")
                if (
                    active_before["digest"] != current.get("digest")
                    or active_before["file_count"] != current.get("file_count")
                ):
                    raise RuntimeError("active release snapshot no longer matches its attestation")
                if getattr(args, "accept_active_drift_digest", None) != active_before["digest"]:
                    raise RuntimeError(
                        "rollback from a drifted release requires --accept-active-drift-digest "
                        + active_before["digest"]
                    )
            current_token = current_path.name
        elif current["kind"] == "directory" and (
            ACTIVE.is_symlink() or not ACTIVE.is_dir() or current_path.exists()
        ):
            raise RuntimeError("active directory drift; rollback stopped")
        elif current["kind"] == "directory":
            active_before = directory_snapshot(ACTIVE, current_path)
            current_token = active_before["digest"]
        else:
            raise RuntimeError("unknown current-state kind")
        require_reviewed_authorization(args, current_token)
        if previous["kind"] == "release":
            target = Path(previous["path"])
            validate_candidate(target)
            active_after = release_snapshot(target)
        elif previous["kind"] == "release_snapshot":
            target = Path(previous["path"])
            active_after = release_snapshot(target, "release_snapshot")
            if (
                active_after["digest"] != previous.get("digest")
                or active_after["file_count"] != previous.get("file_count")
            ):
                raise RuntimeError("preserved release snapshot no longer matches its attestation")
            if getattr(args, "accept_active_drift_digest", None) != active_after["digest"]:
                raise RuntimeError(
                    "rollback to a drifted release requires --accept-active-drift-digest "
                    + active_after["digest"]
                )
        elif previous["kind"] == "directory":
            target = Path(previous["path"])
            if target.is_symlink() or not target.is_dir():
                raise RuntimeError(f"preserved directory is unavailable: {target}")
            active_after = directory_snapshot(target, target)
            active_after["path"] = str(ACTIVE)
            if previous.get("digest") and (
                active_after["digest"] != previous.get("digest")
                or active_after["file_count"] != previous.get("file_count")
            ):
                raise RuntimeError("preserved directory no longer matches its release state")
        else:
            raise RuntimeError("unknown previous-state kind")
        state_after = {
            "version": 1,
            "current": previous,
            "previous": current,
            "rolled_back": True,
        }
        begin_transaction("rollback", active_before, active_after, state, state_after)
        try:
            if current["kind"] == "directory":
                os.rename(ACTIVE, current_path)
            if previous["kind"] in {"release", "release_snapshot"}:
                switch_link(target)
            else:
                if ACTIVE.is_symlink():
                    ACTIVE.unlink()
                os.rename(target, ACTIVE)
            write_json(STATE_FILE, state_after)
            remove_file(TRANSACTION_FILE)
        except Exception as exc:
            try:
                recover_transaction_unlocked()
            except Exception as recovery_exc:
                raise RuntimeError(
                    f"rollback failed ({exc}); automatic recovery failed ({recovery_exc})"
                ) from recovery_exc
            raise
        if not getattr(args, "quiet", False):
            print(f"rolled back to {previous['path']}")
        return 0


def recover(_args: argparse.Namespace) -> int:
    if (STATE / "scoped-transaction.json").is_file():
        from skill_scoped import read_transaction
        with lifecycle_lock():
            read_transaction(sys.modules[__name__])
        print("recovered single-skill transaction")
        return 0
    with lifecycle_lock():
        recovered = recover_transaction_unlocked()
    print("recovered interrupted release transaction" if recovered else "no recovery needed")
    return 0


def parity_dry_run(candidate: Path, distribution_override: Path | None = None) -> dict:
    command = [str(PARITY), "dry-run", "--candidate", str(candidate)]
    if distribution_override is not None:
        command.extend(["--distribution", str(distribution_override)])
    result = run_checked_command(command)
    return json.loads(result["stdout"])


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def run_checked_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    extra_env: dict[str, str] | None = None,
    stdin=None,
) -> dict:
    started_at = utc_now()
    environment = os.environ.copy()
    if extra_env:
        environment.update(extra_env)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=environment,
            stdin=stdin,
        )
    except subprocess.TimeoutExpired as exc:
        output = {
            "command": command,
            "started_at": started_at,
            "finished_at": utc_now(),
            "returncode": None,
            "stdout": text_output(exc.stdout),
            "stderr": text_output(exc.stderr),
            "timed_out": True,
        }
        raise ShipStepError(f"command timed out after {timeout} seconds", output) from exc
    output = {
        "command": command,
        "started_at": started_at,
        "finished_at": utc_now(),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": False,
    }
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no command output"
        raise ShipStepError(
            f"command failed with exit {result.returncode}: {detail}", output
        )
    return output


def outgoing_check(repo: Path, tip: str, base: str) -> tuple[list[str], str | None]:
    """Name each commit a push of tip sends past base, and read every object it sends, whole.

    Return the commit lines and None when all are clean, or a refusal reason. A git error is a
    refusal, never a clean result. The patterns are the ones skill backup checks before its push.
    """
    from skill_backup import SECRET_PATTERNS

    git = ["git", "-C", str(repo)]
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    log = subprocess.run(git + ["log", "--format=%h %s", f"{base}..{tip}"],
                         capture_output=True, text=True, env=env)
    listed = subprocess.run(git + ["rev-list", "--objects", tip, "--not", base],
                            capture_output=True, text=True, env=env)
    if log.returncode or listed.returncode:
        return [], "the secret scan could not list the outgoing commits"
    commits = log.stdout.splitlines()
    names: dict[str, str] = {}
    for line in listed.stdout.splitlines():
        sha, _, path = line.partition(" ")
        if sha:
            names.setdefault(sha, path)
    if not names:
        return commits, None
    read = subprocess.run(git + ["cat-file", "--batch"], input="".join(sha + "\n" for sha in names).encode(),
                          capture_output=True, env=env)
    if read.returncode:
        return commits, "the secret scan could not read the outgoing objects"
    data, at, seen = read.stdout, 0, 0
    while at < len(data):
        end = data.find(b"\n", at)
        header = data[at:end].split() if end >= 0 else []
        if len(header) != 3 or header[0].decode("ascii", "replace") not in names or not header[2].isdigit():
            return commits, "the secret scan could not read the outgoing objects"
        sha, size = header[0].decode("ascii"), int(header[2])
        body = data[end + 1:end + 1 + size]
        if len(body) != size or data[end + 1 + size:end + 2 + size] != b"\n":
            return commits, "the secret scan could not read the outgoing objects"
        if any(pattern.search(body) for pattern in SECRET_PATTERNS):
            return commits, "secret-looking value in " + (names[sha] or header[1].decode("ascii") + " " + sha[:12])
        at, seen = end + 2 + size, seen + 1
    if seen != len(names):
        return commits, "the secret scan could not read the outgoing objects"
    return commits, None


def ship_preflight(*, dry_run: bool = False, repo: Path | None = None) -> dict:
    report = {"commands": []}
    repo = DOJO if repo is None else repo

    def run_git(*args: str) -> dict:
        try:
            result = run_checked_command(
                ["git", "-C", str(repo), *args],
                extra_env={"GIT_OPTIONAL_LOCKS": "0"},
            )
        except ShipStepError as exc:
            if exc.output is not None:
                report["commands"].append(exc.output)
            raise
        report["commands"].append(result)
        return result

    branch = run_git("branch", "--show-current")["stdout"].strip()
    if branch != "main":
        raise ShipStepError("Skillwright must be on main before shipping", report)
    ignored_modified = run_git("diff", "--name-only", "HEAD", "--")[
        "stdout"
    ].splitlines()
    ignored_untracked = run_git(
        "ls-files", "--others", "--exclude-standard", "--directory"
    )["stdout"].splitlines()
    try:
        upstream = run_git("rev-parse", "--abbrev-ref", "@{u}")["stdout"].strip()
    except ShipStepError as exc:
        raise ShipStepError("Skillwright main has no upstream", report) from exc
    if "/" not in upstream:
        raise ShipStepError(f"unsupported upstream ref: {upstream}", report)
    remote, upstream_branch = upstream.split("/", 1)
    run_git("fetch", "--quiet", remote, upstream_branch)
    counts = run_git("rev-list", "--left-right", "--count", "HEAD...@{u}")[
        "stdout"
    ].split()
    if len(counts) != 2:
        raise ShipStepError("could not compare main with its upstream", report)
    ahead, behind = (int(value) for value in counts)
    report.update(
        branch=branch,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        pushed=False,
        ignored_modified=sorted(ignored_modified),
        ignored_untracked=sorted(ignored_untracked),
    )
    if behind:
        raise ShipStepError(
            f"main is behind {upstream}; pull --rebase and rerun ship", report
        )
    if ahead and not dry_run:
        # This push publishes every commit main has past its upstream, not only the shipped skill.
        # Name each one, and refuse a secret-looking value in anything it sends.
        report["outgoing"], refused = outgoing_check(repo, "HEAD", "@{u}")
        if refused:
            raise ShipStepError(f"refused to push main to {upstream}: {refused}", report)
        print(f"ship: pushing {ahead} commit(s) on main to {upstream}:", file=sys.stderr)
        for line in report["outgoing"]:
            print("  " + line, file=sys.stderr)
        run_git("push", remote, f"HEAD:{upstream_branch}")
        report["pushed"] = True
    head = run_git("rev-parse", "HEAD")["stdout"].strip()
    upstream_head = run_git("rev-parse", "@{u}")["stdout"].strip()
    report.update(dojo_commit=head, upstream_commit=upstream_head)
    if head != upstream_head and not dry_run:
        raise ShipStepError(
            f"main is not synchronized with {upstream} after preflight", report
        )
    return report


def refresh_distribution_manifest(
    preflight: dict, *, dry_run_output: Path | None = None
) -> dict:
    """Regenerate the resolved source manifest so a plain skill edit can ship.

    The build refuses stale source digests. Instead of asking a person to run
    the inventory command, ship does it, commits the manifest when it changed,
    and pushes so main stays synchronized (Person, 2026-09-07: edit -> ships).
    """
    inventory = Path(__file__).resolve().with_name("skill_inventory.py")
    worktree_output = DIST
    report = {
        "commands": [],
        "changed": False,
        "would_change": False,
        "changed_skills": [],
        "committed": None,
        "manifest_worktree_left_dirty": False,
    }
    with tempfile.TemporaryDirectory(prefix="skills-manifest-") as temporary:
        output = Path(temporary) / "shipped.yaml"
        with exported_head(preflight["dojo_commit"]) as (source_root, _commit):
            previous_distribution = load_json(
                source_root / DIST_RELPATH
            )
            report["commands"].append(
                run_checked_command(
                    [
                        str(inventory),
                        "distribution",
                        "--candidate",
                        str(source_root),
                        "--active",
                        str(ACTIVE),
                        "--claude",
                        str(CLAUDE),
                        "--output",
                        str(output),
                    ]
                )
            )
            distribution = load_json(output)
            distribution["candidate"] = previous_distribution["candidate"]
            distribution["policy"]["path"] = previous_distribution["policy"]["path"]
            write_json(output, distribution)

        current = run_checked_command(
            [
                "git",
                "-C",
                str(DOJO),
                "show",
                f"{preflight['dojo_commit']}:{DIST_RELPATH}",
            ],
            extra_env={"GIT_OPTIONAL_LOCKS": "0"},
        )
        report["commands"].append(current)
        report["changed_skills"] = sorted(
            name
            for name in previous_distribution["skills"].keys() | distribution["skills"].keys()
            if previous_distribution["skills"].get(name, {}).get("digest")
            != distribution["skills"].get(name, {}).get("digest")
        )
        if output.read_text(encoding="utf-8") == current["stdout"]:
            if dry_run_output is not None:
                shutil.copyfile(output, dry_run_output)
            return report

        report["changed"] = True
        if dry_run_output is not None:
            report["would_change"] = True
            shutil.copyfile(output, dry_run_output)
            return report
        old = preflight["dojo_commit"]
        remote, upstream_branch = preflight["upstream"].split("/", 1)
        blob_result = run_checked_command(
            ["git", "-C", str(DOJO), "hash-object", "-w", str(output)],
            extra_env={"GIT_OPTIONAL_LOCKS": "0"},
        )
        report["commands"].append(blob_result)
        blob = blob_result["stdout"].strip()
        temporary_index = Path(temporary) / "index"
        index_env = {
            "GIT_INDEX_FILE": str(temporary_index),
            "GIT_OPTIONAL_LOCKS": "0",
        }
        for args in (
            ["read-tree", old],
            [
                "update-index",
                "--add",
                "--cacheinfo",
                f"100644,{blob},{DIST_RELPATH}",
            ],
        ):
            result = run_checked_command(
                ["git", "-C", str(DOJO), *args], extra_env=index_env
            )
            report["commands"].append(result)
        tree_result = run_checked_command(
            ["git", "-C", str(DOJO), "write-tree"], extra_env=index_env
        )
        report["commands"].append(tree_result)
        tree = tree_result["stdout"].strip()
        commit_result = run_checked_command(
            [
                "git",
                "-C",
                str(DOJO),
                "commit-tree",
                tree,
                "-p",
                old,
                "-m",
                "chore: regen distribution manifest (ship)",
            ],
            extra_env={"GIT_OPTIONAL_LOCKS": "0"},
        )
        report["commands"].append(commit_result)
        commit = commit_result["stdout"].strip()
        report["outgoing"], refused = outgoing_check(DOJO, commit, old)
        if refused:
            raise ShipStepError(f"refused to push the manifest commit to {preflight['upstream']}: {refused}", report)
        # Push the commit object before changing the local ref, index, or manifest.
        try:
            pushed = run_checked_command(
                ["git", "-C", str(DOJO), "push", remote, f"{commit}:refs/heads/{upstream_branch}"],
                extra_env={"GIT_OPTIONAL_LOCKS": "0"},
            )
        except ShipStepError as exc:
            report["commands"].append(exc.output)
            report["local_state_unchanged"] = True
            raise ShipStepError(
                "manifest push failed; local main, index, and manifest worktree unchanged", report
            ) from exc
        report["commands"].append(pushed)
        report["commands"].append(run_checked_command(
            ["git", "-C", str(DOJO), "update-ref", "refs/heads/main", commit, old],
            extra_env={"GIT_OPTIONAL_LOCKS": "0"},
        ))

        worktree_was_clean = not (
            preflight["ignored_modified"] or preflight["ignored_untracked"]
        )
        if worktree_was_clean:
            read_tree = run_checked_command(
                ["git", "-C", str(DOJO), "read-tree", commit],
                extra_env={"GIT_OPTIONAL_LOCKS": "0"},
            )
            report["commands"].append(read_tree)
            worktree_output.write_bytes(output.read_bytes())
        else:
            report["manifest_worktree_left_dirty"] = True
        report["committed"] = commit
        preflight["dojo_commit"] = commit
        preflight["upstream_commit"] = commit
        return report


def run_ship_tests(source_root: Path = DOJO) -> dict:
    tests_root = source_root / "tests"
    if not tests_root.is_dir():
        raise ShipStepError(f"top-level tests directory is missing: {tests_root}")
    suites = [("top-level", tests_root, source_root)]
    for skill in sorted(authored_skills(source_root).iterdir(), key=lambda path: path.name):
        if (
            skill.is_dir()
            and not skill.is_symlink()
            and (skill / "SKILL.md").is_file()
            and (skill / "tests").is_dir()
        ):
            suites.append((skill.name, skill, skill))
    commands = []
    uv = shutil.which("uv")
    for label, start, top in suites:
        if uv:
            # pytest runs both unittest classes and plain test_* functions; unittest
            # discover reports "NO TESTS RAN" (exit 5) for function-style suites.
            command = [uv, "run", "--with", "pytest", "pytest", "-q", "-p", "no:cacheprovider",
                       str(start.relative_to(source_root))]
        else:
            command = [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(start.relative_to(source_root)),
                "-p",
                "test_*.py",
            ]
            if top != source_root:
                command[6:6] = ["-t", str(top.relative_to(source_root))]
        try:
            output = run_checked_command(
                command,
                cwd=source_root,
                extra_env={"PYTHONDONTWRITEBYTECODE": "1"},
            )
        except ShipStepError as exc:
            failed = exc.output or {"command": command}
            if isinstance(failed, dict):
                failed["suite"] = label
            commands.append(failed)
            raise ShipStepError(f"test suite failed: {label}", {"commands": commands}) from exc
        output["suite"] = label
        commands.append(output)
    return {"suite_count": len(suites), "commands": commands}


def active_release_details() -> tuple[Path, dict] | None:
    if not ACTIVE.is_symlink():
        return None
    target = active_target()
    if target is None:
        raise RuntimeError("active release pointer is unreadable")
    return target, validate_candidate(target)


def changed_skill_names(candidate_manifest: dict, previous_manifest: dict | None) -> list[str]:
    if previous_manifest is None:
        changed = sorted(candidate_manifest["skills"])
    else:
        previous_skills = previous_manifest.get("skills", {})
        changed = sorted(
            name
            for name, entry in candidate_manifest["skills"].items()
            if previous_skills.get(name) != entry
        )
    if changed:
        return changed
    return list(candidate_manifest["canary_checklist"]["required_skills"])


def canary_prompt(required: list[str]) -> str:
    names = ", ".join(required)
    return (
        "report whether each required skill is actually available to you in this "
        "fresh session. Do not guess. Return exactly one line per skill as "
        f"<name>: present or <name>: absent. Required skills: {names}"
    )


def codex_canary_prompt(prompt: str) -> str:
    required = prompt.rsplit("Required skills: ", 1)[-1]
    return (
        "Use your file tools to read ~/.foxrun/skills/<name>/SKILL.md for each "
        "required skill and reply `<name>: present` only if the file exists and "
        "has a `name:` line, else `<name>: absent`. Required skills: "
        + required
    )


def parse_canary_overrides(values: list[str] | None) -> dict[str, str]:
    overrides = {}
    shared = os.environ.get("SKILLS_CANARY_COMMAND")
    if shared:
        overrides = {runtime: shared for runtime in ("claude", "codex", "hermes")}
    for value in values or []:
        runtime, separator, template = value.partition("=")
        if separator != "=" or runtime not in {"claude", "codex", "hermes"} or not template:
            raise RuntimeError(
                "--canary-command must be runtime=template for claude, codex, or hermes"
            )
        overrides[runtime] = template
    return overrides


def code_model():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from base.agent_catalog import resolve_model
    return resolve_model('code', 'codex')


def canary_command(runtime: str, prompt: str, overrides: dict[str, str]) -> list[str]:
    if runtime in overrides:
        return [
            part.replace("{runtime}", runtime).replace("{prompt}", prompt)
            for part in shlex.split(overrides[runtime])
        ]
    if runtime == "claude":
        return [
            "claude",
            "-p",
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--strict-mcp-config",
            "--max-budget-usd",
            "1.20",
            # The stream's first event lists every skill this fresh session loaded.
            "--output-format",
            "stream-json",
            "--verbose",
            prompt,
        ]
    if runtime == "codex":
        return [
            "codex",
            "exec",
            "-m",
            code_model(),
            "-s",
            "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            codex_canary_prompt(prompt),
        ]
    # Hermes guesses when asked without tools (it reported a rolled-back skill as
    # present on 2026-09-07). Ground the answer in its real skill index instead.
    # Only the skills toolset is needed; do not auto-load skill instructions.
    return [
        "hermes",
        "chat",
        "--oneshot",
        "-t",
        "skills",
        "--ignore-rules",
        "-q",
        "Call the skills_list tool once. Then, using only that tool result, "
        + prompt,
        "--max-turns",
        "4",
        "--run-budget",
        "150",
    ]


def hidden_from_model(candidate: Path, names: list[str]) -> list[str]:
    """Skills whose page sets `disable-model-invocation: true`.

    Claude lists such a skill for the person to call, but never shows it to the
    model, so the model cannot report it. The canary checks Claude's list instead.
    """
    hidden = []
    for name in names:
        page = candidate / name / "SKILL.md"
        lines = page.read_text(encoding="utf-8").splitlines() if page.is_file() else []
        if lines[:1] != ["---"] or "---" not in lines[1:]:
            continue
        front = lines[1 : lines.index("---", 1)]
        if any(re.fullmatch(r"disable-model-invocation:\s*true\s*", line) for line in front):
            hidden.append(name)
    return hidden


def claude_stream(stdout: str) -> tuple[set[str] | None, str]:
    """Read `claude -p --output-format stream-json`: the skills the session listed, and the reply.

    Output that is not a stream (a test command) gives no list and the text unchanged.
    """
    listed, reply = None, None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            listed = {str(name) for name in event.get("skills") or []}
        elif event.get("type") == "result" and isinstance(event.get("result"), str):
            reply = event["result"]
    return listed, stdout if reply is None else reply


def run_fresh_canaries(
    required: list[str], prompt: str, overrides: dict[str, str], hidden: list[str] = ()
) -> dict:
    runtimes = ("claude", "codex", "hermes")

    def run_one(runtime: str) -> tuple[str, dict]:
        # One retry: a runtime can fail for a moment (T742: claude failed twice in a
        # window with a Claude Code self-update and a login refresh, then passed).
        # The first attempt stays in the record; a real failure fails twice.
        runtime, first = attempt(runtime)
        if first["result"] == "passed":
            return runtime, first
        runtime, second = attempt(runtime)
        second["first_attempt"] = first
        return runtime, second

    def attempt(runtime: str) -> tuple[str, dict]:
        command = canary_command(runtime, prompt, overrides)
        try:
            output = run_checked_command(
                command, timeout=180, stdin=subprocess.DEVNULL
            )
        except ShipStepError as exc:
            result = exc.output if isinstance(exc.output, dict) else {"command": command}
            result["result"] = "failed"
            result["error"] = str(exc)
            return runtime, result
        listed, reply = None, output["stdout"]
        if runtime == "claude":
            listed, reply = claude_stream(output["stdout"])
            if listed is not None:
                # Keep the reply, not the whole stream (its first event lists every skill and tool).
                output["stdout"] = reply
        statuses = {}
        for line in reply.splitlines():
            match = re.fullmatch(r"\s*([^:]+):\s*(present|absent)\s*", line)
            if match and match.group(1).strip() in required:
                statuses[match.group(1).strip()] = match.group(2)
        if listed is not None:
            # A skill hidden from the model is present when the fresh session lists it.
            checked = sorted(set(hidden) & set(required))
            for name in checked:
                statuses[name] = "present" if name in listed else "absent"
            output["checked_by_list"] = checked
        missing = sorted(set(required) - set(statuses))
        absent = sorted(name for name, value in statuses.items() if value == "absent")
        output.update(statuses=statuses, missing=missing, absent=absent)
        if missing or absent:
            output["result"] = "failed"
            output["error"] = f"canary reply missing={missing} absent={absent}"
        else:
            output["result"] = "passed"
        return runtime, output

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(run_one, runtime): runtime for runtime in runtimes}
        for future in concurrent.futures.as_completed(futures):
            runtime, output = future.result()
            results[runtime] = output
    failures = sorted(
        runtime for runtime, output in results.items() if output["result"] != "passed"
    )
    report = {"required_skills": required, "prompt": prompt, "runtimes": results}
    if failures:
        raise ShipStepError("fresh canaries failed: " + ", ".join(failures), report)
    return report


def run_consumer_checks(candidate: Path, required: list[str]) -> dict:
    outputs = {}
    for runtime in ("codex", "hermes", "claude"):
        command = [str(PARITY), "check", "--runtime", runtime]
        if runtime == "claude":
            command.extend(["--sandbox", str(CLAUDE)])
        else:
            command.extend(["--candidate", str(candidate)])
        for name in required:
            command.extend(["--required", name])
        try:
            outputs[runtime] = run_checked_command(command)
        except ShipStepError as exc:
            if isinstance(exc.output, dict):
                outputs[runtime] = exc.output
            raise ShipStepError(f"consumer check failed: {runtime}", outputs) from exc
    return outputs


def run_receipt_step(receipt: dict, path: Path, name: str, action) -> object:
    step = {"name": name, "started_at": utc_now()}
    try:
        output = action()
        step.update(result="passed", output=output)
    except Exception as exc:
        step.update(result="failed", error=str(exc))
        if isinstance(exc, ShipStepError) and exc.output is not None:
            step["output"] = exc.output
        raise
    finally:
        step["finished_at"] = utc_now()
        receipt["steps"].append(step)
        write_json(path, receipt)
    return output


def codex_link_matches(path: Path, target: Path) -> bool:
    return path.is_symlink() and os.readlink(path) == str(target)


def restore_codex_changes(
    changed: list[dict], archive: Path, *, allow_missing: bool = False
) -> None:
    for record in reversed(changed):
        name = record["name"]
        path = CODEX / name
        expected = ACTIVE / name
        if path.is_symlink():
            if not codex_link_matches(path, expected):
                raise RuntimeError(f"Codex link drift: {name}")
            path.unlink()
        elif path.exists():
            raise RuntimeError(f"refusing to overwrite unexpected Codex entry: {name}")
        elif not allow_missing:
            raise RuntimeError(f"Codex link is missing during rollback: {name}")
        before = record["before"]
        if before is None:
            continue
        if before["kind"] == "symlink":
            os.symlink(before["target"], path)
        elif before["kind"] in {"directory", "file"}:
            stored = archive / name
            if not stored.exists() and not stored.is_symlink():
                raise RuntimeError(f"Codex archive entry is missing: {name}")
            os.rename(stored, path)
        else:
            raise RuntimeError(f"unsupported Codex rollback entry: {name}")


def apply_codex_links(candidate: Path, release_id: str) -> dict:
    manifest = validate_candidate(candidate)
    if not ACTIVE.is_symlink() or active_target() != candidate.resolve(strict=False):
        raise RuntimeError("candidate is not the active shared release")
    if CODEX.exists() and not CODEX.is_dir():
        raise RuntimeError(f"Codex skills root is not a directory: {CODEX}")
    CODEX.mkdir(parents=True, exist_ok=True)
    archive = STATE / "codex-parity-archive" / release_id
    if archive.exists() or archive.is_symlink():
        raise RuntimeError(f"Codex archive already exists: {archive}")
    changed = []
    report = {"created": [], "refreshed": [], "kept": []}
    try:
        for name in sorted(manifest["skills"]):
            path = CODEX / name
            target = ACTIVE / name
            if codex_link_matches(path, target):
                report["kept"].append(name)
                continue
            before = None
            if path.is_symlink():
                before = {"kind": "symlink", "target": os.readlink(path)}
                path.unlink()
            elif path.exists():
                archive.mkdir(parents=True, exist_ok=True)
                kind = "directory" if path.is_dir() else "file"
                os.rename(path, archive / name)
                before = {"kind": kind}
            changed.append({"name": name, "before": before})
            temporary = CODEX / f".{name}.next-{os.getpid()}"
            if temporary.exists() or temporary.is_symlink():
                raise RuntimeError(f"Codex temporary link already exists: {temporary}")
            os.symlink(target, temporary)
            os.replace(temporary, path)
            if not codex_link_matches(path, target) or not (path / "SKILL.md").is_file():
                raise RuntimeError(f"Codex link readback failed: {name}")
            report["created" if before is None else "refreshed"].append(name)
        if changed:
            if CODEX_STATE_FILE.is_symlink():
                raise RuntimeError(
                    f"Codex state path must not be a symlink: {CODEX_STATE_FILE}"
                )
            write_json(
                CODEX_STATE_FILE,
                {
                    "version": 1,
                    "release_id": release_id,
                    "candidate": str(candidate),
                    "archive": str(archive),
                    "changed": changed,
                },
            )
    except Exception:
        restore_codex_changes(changed, archive, allow_missing=True)
        raise
    return report


def rollback_codex_links(release_id: str) -> dict:
    if CODEX_STATE_FILE.is_symlink() or not CODEX_STATE_FILE.is_file():
        raise RuntimeError("no Codex link state is available")
    state = load_json(CODEX_STATE_FILE)
    if state.get("version") != 1 or state.get("release_id") != release_id:
        raise RuntimeError("Codex link state does not match this release")
    changed = state.get("changed", [])
    restore_codex_changes(changed, Path(state["archive"]))
    write_json(
        CODEX_STATE_FILE,
        {
            "version": 1,
            "release_id": release_id,
            "rolled_back": True,
            "restored": len(changed),
        },
    )
    return {"restored": len(changed)}


def rollback_ship(
    release_id: str, restore_claude: bool, restore_codex: bool
) -> dict:
    report = {
        "release": None,
        "claude_links": None,
        "codex_links": None,
        "complete": False,
    }
    if restore_codex:
        try:
            report["codex_links"] = rollback_codex_links(release_id)
            report["codex_links"]["result"] = "passed"
        except Exception as exc:
            report["codex_links"] = {"result": "failed", "error": str(exc)}
    try:
        rollback(
            argparse.Namespace(
                authorize_reviewed=release_id,
                accept_active_drift_digest=None,
                quiet=True,
            )
        )
        report["release"] = {"result": "passed"}
    except Exception as exc:
        report["release"] = {"result": "failed", "error": str(exc)}
    if restore_claude:
        try:
            report["claude_links"] = run_checked_command([str(PARITY), "rollback"])
            report["claude_links"]["result"] = "passed"
        except Exception as exc:
            output = exc.output if isinstance(exc, ShipStepError) else None
            report["claude_links"] = {
                "result": "failed",
                "error": str(exc),
                "output": output,
            }
    report["complete"] = (
        report["release"]["result"] == "passed"
        and (not restore_claude or report["claude_links"]["result"] == "passed")
        and (not restore_codex or report["codex_links"]["result"] == "passed")
    )
    return report


def release_file_hashes(root: Path) -> dict[str, tuple[str, str]]:
    """Include every file and link, including the release record."""
    found = {}
    for base, dirs, files in os.walk(root, followlinks=False):
        base = Path(base)
        for name in list(dirs):
            if (base / name).is_symlink():
                dirs.remove(name)
                files.append(name)
        for name in files:
            path = base / name
            key = path.relative_to(root).as_posix()
            if path.is_symlink():
                raw = os.readlink(path).encode("utf-8", "surrogateescape")
                found[key] = ("link", hashlib.sha256(raw).hexdigest())
            elif path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                found[key] = ("file", digest.hexdigest())
            else:
                raise RuntimeError(f"unsupported release entry: {path}")
    return found


def prove_git_rebuild(release: Path) -> None:
    """Recreate the frozen payload from the commit named by its release."""
    from skill_scoped import RECORD, package_skill, record_digest, validate_record

    match = re.fullmatch(r"[0-9]{8}T[0-9]{6}(?:[0-9]{6})?Z-([0-9a-f]{12})", release.name)
    if not match:
        raise RuntimeError("release name has no Git commit")
    commit = git("rev-parse", match.group(1) + "^{commit}")
    if not commit.startswith(match.group(1)):
        raise RuntimeError("release name does not match its Git commit")
    manifest = validate_record(sys.modules[__name__], release)
    if manifest.get("dojo_commit") != commit or manifest.get("version") != 3:
        raise RuntimeError("release record does not match its Git commit")
    if manifest.get("digest") != record_digest(manifest["skills"]):
        raise RuntimeError("release record digest differs")
    with exported_head(commit) as (source, exported_commit):
        if exported_commit != commit:
            raise RuntimeError("Git archive resolved a different commit")
        policy = source / "config/catalog.yaml"
        if not policy.is_file() or hashlib.sha256(policy.read_bytes()).hexdigest() != manifest["policy"]["digest"]:
            raise RuntimeError("release policy cannot be rebuilt from Git")
        with tempfile.TemporaryDirectory(prefix="skill-rebuild-") as temporary:
            rebuilt = Path(temporary)
            for name, expected in manifest["skills"].items():
                if expected.get("source") != "skills_dojo" or expected.get("source_drift"):
                    raise RuntimeError(f"skill {name} has no exact Git rebuild")
                authored = source / "skills" / name
                if not authored.is_dir():
                    raise RuntimeError(f"skill {name} is absent from Git")
                actual = package_skill(sys.modules[__name__], authored, rebuilt / name, source)
                for field in ("digest", "file_count"):
                    if actual[field] != expected.get(field):
                        raise RuntimeError(f"skill {name} differs from its Git rebuild")
            # The record stores release time and canary results. Its payload and
            # policy are checked above before its exact bytes join the rebuild.
            shutil.copy2(release / RECORD, rebuilt / RECORD)
            if release_file_hashes(rebuilt) != release_file_hashes(release):
                raise RuntimeError("release file hashes differ from its Git rebuild")


def prune_old_releases() -> None:
    """Retain the active release and four newest others; warn on any hold."""
    try:
        with lifecycle_lock():
            _prune_old_releases_locked()
    except Exception as exc:
        print(f"warning: release pruning skipped: {exc}", file=sys.stderr)


def _prune_old_releases_locked() -> None:
    if not ACTIVE.is_symlink() or not RELEASES.is_dir():
        print("warning: release pruning skipped; active shelf is not a release link", file=sys.stderr)
        return
    live = ACTIVE.resolve(strict=False)
    if live.parent != RELEASES or not live.is_dir():
        print("warning: release pruning skipped; active target is outside releases", file=sys.stderr)
        return
    folders = sorted((p for p in RELEASES.iterdir() if p.is_dir() and not p.is_symlink()), key=lambda p: p.name)
    keep = {live, *[p for p in folders if p != live][-4:]}
    for release in folders:
        if release in keep:
            continue
        try:
            prove_git_rebuild(release)
            if ACTIVE.resolve(strict=False) == release or release in keep:
                raise RuntimeError("release became protected during pruning")
            for base, _dirs, _files in os.walk(release, followlinks=False):
                os.chmod(base, os.stat(base).st_mode | 0o700)
            shutil.rmtree(release)
            print(f"pruned rebuilt release {release.name}")
        except Exception as exc:
            print(f"warning: kept release {release.name}: {exc}", file=sys.stderr)


def ship(args: argparse.Namespace) -> int:
    if getattr(args, "workflow", None):
        from workflow_ship import ship_one
        return ship_one(args)
    if getattr(args, "skill", None):
        from skill_scoped import ship_one
        result = ship_one(sys.modules[__name__], args)
        if result == 0 and not args.dry_run:
            prune_old_releases()
        return result
    if DIST.is_file() and load_json(DIST).get("version") == 3:
        raise RuntimeError("Full ship is on hold until X5 proves the host vendor routes. Use ship --skill NAME.")
    head = git("rev-parse", "HEAD")
    release_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + head[:12]
    receipt_path = SHIPS / f"{release_id}.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise RuntimeError(f"ship receipt already exists: {receipt_path}")
    receipt = {
        "version": 1,
        "release_id": release_id,
        "started_at": utc_now(),
        "finished_at": None,
        "result": "running",
        "dry_run": bool(args.dry_run),
        "source": {"kind": "git-archive", "commit": head},
        "ignored_modified": [],
        "ignored_untracked": [],
        "manifest_worktree_left_dirty": False,
        "codex_links": {"created": [], "refreshed": [], "kept": []},
        "dojo_commit": head,
        "upstream_commit": None,
        "previous_release_id": None,
        "previous_dojo_commit": None,
        "required_skills": [],
        "canary_outputs": None,
        "steps": [],
        "failure_step": None,
        "rollback": None,
    }
    write_json(receipt_path, receipt)
    current_step = "preflight"
    candidate = release_path(release_id)
    parity = None
    previous = None
    state = {"published": False, "claude_applied": False, "codex_applied": False}
    preview = tempfile.TemporaryDirectory(prefix="skills-ship-preview-") if args.dry_run else None
    preview_manifest = Path(preview.name) / "shipped.yaml" if preview else None
    try:
        preflight = run_receipt_step(
            receipt, receipt_path, current_step,
            lambda: ship_preflight(dry_run=args.dry_run),
        )
        receipt["dojo_commit"] = preflight["dojo_commit"]
        receipt["upstream_commit"] = preflight["upstream_commit"]
        receipt["source"]["commit"] = preflight["dojo_commit"]
        receipt["ignored_modified"] = preflight["ignored_modified"]
        receipt["ignored_untracked"] = preflight["ignored_untracked"]

        current_step = "manifest"
        manifest_report = run_receipt_step(
            receipt, receipt_path, current_step,
            lambda: refresh_distribution_manifest(
                preflight, dry_run_output=preview_manifest
            ),
        )
        receipt["manifest_worktree_left_dirty"] = manifest_report[
            "manifest_worktree_left_dirty"
        ]
        if manifest_report.get("committed"):
            receipt["dojo_commit"] = preflight["dojo_commit"]
            receipt["upstream_commit"] = preflight["upstream_commit"]
            receipt["source"]["commit"] = preflight["dojo_commit"]

        current_step = "tests"
        with exported_head(preflight["dojo_commit"]) as (source_root, _commit):
            run_receipt_step(
                receipt,
                receipt_path,
                current_step,
                lambda: run_ship_tests(source_root),
            )

        current_step = "build_validate_parity"

        def build_gates() -> dict:
            nonlocal parity, previous
            build(argparse.Namespace(
                release_id=release_id, quiet=True,
                distribution_override=preview_manifest,
            ))
            manifest = validate_candidate(
                candidate, require_current_policy=True,
                distribution_override=preview_manifest,
            )
            parity = parity_dry_run(candidate, distribution_override=preview_manifest)
            if parity.get("blocked"):
                raise ShipStepError(
                    "Claude parity dry run is blocked", {"parity": parity}
                )
            previous = active_release_details()
            previous_manifest = previous[1] if previous else None
            required = changed_skill_names(manifest, previous_manifest)
            prompt = canary_prompt(required)
            receipt["required_skills"] = required
            if previous:
                receipt["previous_release_id"] = previous_manifest["release_id"]
                receipt["previous_dojo_commit"] = previous_manifest.get("dojo_commit")
            return {
                "candidate": str(candidate),
                "candidate_valid": True,
                "skill_count": len(manifest["skills"]),
                "parity": parity,
                "canary_prompt_preview": prompt,
            }

        run_receipt_step(receipt, receipt_path, current_step, build_gates)
        if args.dry_run:
            receipt.update(result="dry_run", finished_at=utc_now())
            write_json(receipt_path, receipt)
            preview.cleanup()
            if manifest_report["would_change"]:
                names = ", ".join(manifest_report["changed_skills"]) or "no skill digests differ"
                print(f"manifest would change: {names}")
            else:
                print("manifest unchanged")
            print(f"dry-run {release_id} — nothing published")
            return 0

        current_step = "publish"

        def publish_candidate() -> dict:
            if previous is None:
                raise RuntimeError("ship requires an active release as a rollback target")
            publish(
                argparse.Namespace(
                    candidate=str(candidate),
                    preserve_existing_to=None,
                    authorize_reviewed=release_id,
                    accept_active_drift_digest=None,
                    accept_active_drift_skill=None,
                    quiet=True,
                )
            )
            state["published"] = True
            return {"active_release_id": release_id}

        run_receipt_step(receipt, receipt_path, current_step, publish_candidate)

        current_step = "claude_links"

        def apply_claude_links() -> dict:
            approvals = parity.get("approval_required_changes", [])
            if approvals:
                raise ShipStepError(
                    "Claude parity changes require Person approval",
                    {"approval_required_changes": approvals},
                )
            changes = parity.get("changes", [])
            unsupported = [row for row in changes if row.get("action") != "create_link"]
            if unsupported:
                raise ShipStepError(
                    "Claude parity has changes that ship cannot apply automatically",
                    {"unsupported_changes": unsupported},
                )
            if not changes:
                return {"applied": False, "changes": []}
            archive = STATE / "claude-parity-archive" / release_id
            output = run_checked_command(
                [
                    str(PARITY),
                    "apply",
                    "--candidate",
                    str(candidate),
                    "--archive",
                    str(archive),
                ]
            )
            state["claude_applied"] = True
            return {"applied": True, "archive": str(archive), "changes": changes, "command": output}

        run_receipt_step(receipt, receipt_path, current_step, apply_claude_links)

        current_step = "codex_links"
        codex_links = run_receipt_step(
            receipt,
            receipt_path,
            current_step,
            lambda: apply_codex_links(candidate, release_id),
        )
        receipt["codex_links"] = codex_links
        state["codex_applied"] = bool(
            codex_links["created"] or codex_links["refreshed"]
        )

        current_step = "consumer_checks"
        run_receipt_step(
            receipt,
            receipt_path,
            current_step,
            lambda: run_consumer_checks(candidate, receipt["required_skills"]),
        )

        current_step = "canaries"
        prompt = canary_prompt(receipt["required_skills"])
        overrides = parse_canary_overrides(args.canary_command)
        canaries = run_receipt_step(
            receipt,
            receipt_path,
            current_step,
            lambda: run_fresh_canaries(
                receipt["required_skills"], prompt, overrides,
                hidden_from_model(candidate, receipt["required_skills"]),
            ),
        )
        receipt["canary_outputs"] = canaries["runtimes"]
        receipt.update(result="shipped", finished_at=utc_now())
        write_json(receipt_path, receipt)
        print(f"shipped {release_id}")
        prune_old_releases()
        return 0
    except Exception as exc:
        if preview is not None:
            preview.cleanup()
        receipt["failure_step"] = current_step
        receipt["error"] = str(exc)
        if (
            current_step == "canaries"
            and isinstance(exc, ShipStepError)
            and isinstance(exc.output, dict)
        ):
            receipt["canary_outputs"] = exc.output.get("runtimes")
        switched = ACTIVE.is_symlink() and active_target() == candidate.resolve(strict=False)
        if state["published"] or switched:
            rollback_started = utc_now()
            rollback_report = rollback_ship(
                release_id, state["claude_applied"], state["codex_applied"]
            )
            receipt["rollback"] = rollback_report
            receipt["steps"].append(
                {
                    "name": "rollback",
                    "started_at": rollback_started,
                    "finished_at": utc_now(),
                    "result": "passed" if rollback_report["complete"] else "failed",
                    "output": rollback_report,
                }
            )
            if rollback_report["complete"]:
                suffix = f"rolled back to {receipt['previous_release_id']}"
            else:
                suffix = "rollback incomplete"
        else:
            suffix = "nothing published"
            # A git push in preflight or manifest is already on the upstream; say so.
            if any(step.get("name") in ("preflight", "manifest") and isinstance(step.get("output"), dict)
                   and (step["output"].get("pushed") or step["output"].get("committed"))
                   for step in receipt["steps"]):
                suffix = "no release published; main was already pushed to its upstream"
        receipt.update(result="failed", finished_at=utc_now())
        write_json(receipt_path, receipt)
        print(f"skill_ship.py ship: {exc}", file=sys.stderr)
        print(f"failed {current_step} — {suffix}")
        return 1


def deliver(args: argparse.Namespace) -> int:
    """Build or reuse one candidate, run all pre-publication gates, then publish if authorized."""
    if args.candidate:
        candidate = release_path(args.candidate)
    else:
        release_id = args.release_id or (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + git("rev-parse", "HEAD")[:12]
        )
        build(argparse.Namespace(release_id=release_id, quiet=True))
        candidate = release_path(release_id)
    manifest = validate_candidate(candidate, require_current_policy=True)
    parity = parity_dry_run(candidate)
    changes = parity.get("changes", [])
    approvals = parity.get("approval_required_changes", [])
    report = {
        "version": 1,
        "release_id": manifest["release_id"],
        "candidate": str(candidate),
        "candidate_valid": True,
        "consumer_parity_ready": not changes and not parity.get("blocked"),
        "parity_changes": changes,
        "parity_approval_required_changes": approvals,
        "publication_authorized": False,
        "published": False,
        "activation_complete": False,
        "fresh_session_canaries_required": manifest["canary_checklist"],
    }
    if args.authorize_reviewed:
        if changes or parity.get("blocked"):
            print(json.dumps(report, indent=2, sort_keys=True))
            raise RuntimeError(
                "consumer links are not established; use the reviewed bootstrap "
                "sequence: publish, parity apply, verify, and rollback on failure"
            )
        args.candidate = str(candidate)
        args.quiet = True
        publish(args)
        report["publication_authorized"] = True
        report["published"] = True
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def readiness(_args: argparse.Namespace) -> int:
    """Observe build prerequisites without locks, writes, fetches, or publication."""
    blockers = []
    report = {
        "version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "ready_to_build": False,
        "publication_authorized": False,
        "upstream_observation": "local tracking ref; no network refresh",
        "active_valid": None,
        "publish_skills": [],
        "excluded_skills": [],
        "host_specific_skills": [],
        "blockers": blockers,
        "remaining_checks": ["lifecycle lock at execution", "consumer parity dry-run",
                             "reviewed activation", "fresh-session canaries"],
        "pending_transaction": None,
    }
    errors = (OSError, RuntimeError, subprocess.CalledProcessError,
              ValueError, KeyError, TypeError, AttributeError)
    try:
        report["dojo_commit"] = require_clean_main()
    except errors as exc:
        blockers.append({"check": "source", "reason": str(exc)})
    try:
        head = report.get("dojo_commit", "HEAD")
        with exported_head(head) as (source_root, _commit):
            distribution = load_json(source_root / DIST_RELPATH)
            policy, digest = validate_distribution_policy(distribution, source_root)
        report.update(publish_skills=policy["publish"],
                      excluded_skills=sorted(policy["exclude"]),
                      host_specific_skills=sorted(policy["host_specific"]),
                      policy_digest=digest)
        if distribution.get("version") == 3:
            blockers.append({"check": "full_publication", "reason": "Version 3 uses scoped ship; full publication needs proved X5 vendor routes and reviewed ownership baselines."})
    except errors as exc:
        blockers.append({"check": "distribution", "reason": str(exc)})
    report["ready_to_build"] = not blockers
    if ACTIVE.is_symlink():
        target = active_target()
        if target is not None and target.is_dir():
            digest, count = digest_tree(target)
            report["active_tree_digest"] = digest
            report["active_tree_file_count"] = count
        try:
            manifest = validate_candidate(target)
            report["active_valid"] = True
            report["active_release_id"] = manifest["release_id"]
        except errors as exc:
            report["active_valid"] = False
            blockers.append({"check": "active_release", "reason": str(exc)})
    elif ACTIVE.exists():
        try:
            if load_json(ACTIVE / ".release-manifest.json").get("version") == 3:
                manifest = validate_candidate(ACTIVE)
                report["active_valid"] = True
                report["active_release_id"] = manifest["release_id"]
            else:
                blockers.append({"check": "active_release", "reason": "physical active directory needs reviewed preservation"})
        except errors as exc:
            report["active_valid"] = False
            blockers.append({"check": "active_release", "reason": str(exc)})
    try:
        transaction = read_transaction()
        if transaction:
            report["pending_transaction"] = {
                "operation": transaction["operation"],
                "created_at": transaction["created_at"],
            }
            blockers.append({
                "check": "interrupted_transaction",
                "reason": "run tools/skill_ship.py recover before delivery",
            })
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        blockers.append({"check": "interrupted_transaction", "reason": str(exc)})
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if blockers else 0


def status(_args: argparse.Namespace) -> int:
    payload = {
        "active_path": str(ACTIVE),
        "active_kind": "symlink" if ACTIVE.is_symlink() else "directory" if ACTIVE.exists() else "missing",
        "active_target": str(active_target()) if ACTIVE.is_symlink() else None,
        "state": state_snapshot(),
        "transaction": read_transaction(),
        "releases": sorted(path.name for path in RELEASES.iterdir()) if RELEASES.is_dir() else [],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


TRIGGER = Path(__file__).resolve().with_name("skill-ship-trigger.sh")
HOOKS = ("post-commit", "post-merge")
# Legacy signatures identify owned hooks during an upgrade.
OWN_MARKERS = ("Skillwright ship trigger", "Skills Dojo ship trigger", "Skills Dojo post-commit trigger")

def trigger_stub(hook: str) -> str:
    return (
        "#!/bin/sh\n"
        "# Skillwright ship trigger. Do not edit: the logic is tracked in tools/skill-ship-trigger.sh.\n"
        "# Installed by tools/skill_ship.py install-trigger. Remove this file to turn the trigger off.\n"
        'trigger="$(git rev-parse --show-toplevel)/tools/skill-ship-trigger.sh"\n'
        '[ -x "$trigger" ] || exit 0\n'
        f'exec "$trigger" {hook} "$@"\n'
    )


def person_trigger_stub(hook: str) -> str:
    """The person's skill source runs the installed trigger and names itself as the source."""
    return (
        "#!/bin/sh\n"
        "# Skillwright ship trigger (person source). Do not edit: the logic is tracked in tools/skill-ship-trigger.sh.\n"
        "# Installed by tools/skill_ship.py install-trigger. Remove this file to turn the trigger off.\n"
        f"trigger={shlex.quote(str(TRIGGER))}\n"
        '[ -x "$trigger" ] || exit 0\n'
        'SKILLS_SOURCE_REPO="$(git rev-parse --show-toplevel)"\n'
        "export SKILLS_SOURCE_REPO\n"
        f'exec "$trigger" {hook} "$@"\n'
    )


def trigger_hooks_dir(repo: Path | None = None) -> Path:
    repo = DOJO if repo is None else repo
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
        text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"not a Git repository: {repo}")
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else repo / path


def trigger_state_of(path: Path, hook: str, stub=None) -> str:
    stub = trigger_stub if stub is None else stub
    if not path.exists() and not path.is_symlink():
        return "missing"
    if path.is_symlink() or not path.is_file():
        return "foreign"
    text = path.read_text(encoding="utf-8", errors="replace")
    if text == stub(hook):
        return "current" if os.access(path, os.X_OK) else "stale"
    return "stale" if any(marker in text for marker in OWN_MARKERS) else "foreign"


def install_trigger(args: argparse.Namespace) -> int:
    try:
        directory = trigger_hooks_dir()
        if not TRIGGER.is_file() or not os.access(TRIGGER, os.X_OK):
            raise RuntimeError(f"installed trigger is missing or not executable: {TRIGGER}")
        report = {"dojo": str(DOJO), "hooks_dir": str(directory), "hooks": {}, "written": [], "kept_copies": []}
        # Both sources ship on commit: the Dojo (product skills) and the person's own skill source.
        targets = [(directory, "hooks", trigger_stub)]
        if PERSON is not None:
            person_dir = trigger_hooks_dir(PERSON)
            report.update(person=str(PERSON), person_hooks_dir=str(person_dir), person_hooks={})
            targets.append((person_dir, "person_hooks", person_trigger_stub))
        for folder, key, stub in targets:
            for hook in HOOKS:
                report[key][hook] = trigger_state_of(folder / hook, hook, stub)
        foreign = sorted(
            f"{hook} in {folder}" for folder, key, _stub in targets
            for hook, state in report[key].items() if state == "foreign"
        )
        if args.check:
            report["ok"] = all(state == "current" for _f, key, _s in targets for state in report[key].values())
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 1
        if foreign:
            raise RuntimeError("unknown hook, not replaced: " + ", ".join(foreign))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for folder, key, stub in targets:
            for hook in HOOKS:
                if report[key][hook] == "current":
                    continue
                path = folder / hook
                report["written"].append(str(path))
                if args.dry_run:
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    # Keep the replaced hook. Git runs only the exact hook names.
                    copy = folder / f"{hook}.replaced-{stamp}"
                    path.rename(copy)
                    report["kept_copies"].append(str(copy))
                path.write_text(stub(hook), encoding="utf-8")
                path.chmod(0o755)
                report[key][hook] = "current"
        report["ok"] = True
        report["dry_run"] = bool(args.dry_run)
        print(json.dumps(report, indent=2))
        return 0
    except RuntimeError as exc:
        print(f"skill_ship.py install-trigger: {exc}", file=sys.stderr)
        return 2



def catalog_routes(args):
    """Route a frozen complete candidate into manifest-owned native runtime entries."""
    state_path = STATE / 'catalog-routes.json'
    from contextlib import nullcontext
    with (nullcontext() if args.dry_run else lifecycle_lock()):
        owned = load_json(state_path).get('links', {}) if state_path.exists() else {}
        raw = json.loads(POLICY.read_text())
        if ACTIVE.resolve() != Path(args.candidate).resolve():
            raise RuntimeError('Activate the reviewed frozen candidate before routing its native links.')
        plan = route_plan(raw, DOJO, args.candidate, args.portfolio, args.global_root, owned, stable_shelf=ACTIVE)
        if not args.dry_run:
            links = apply_route_plan(plan, owned)
            write_json(state_path, dict(version=1, links=links))
        print(json.dumps(dict(dry_run=args.dry_run, actions=plan), indent=2))
    return 0

def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    install_parser = commands.add_parser("install-trigger")
    install_mode = install_parser.add_mutually_exclusive_group()
    install_mode.add_argument("--check", action="store_true")
    install_mode.add_argument("--dry-run", action="store_true")
    install_parser.set_defaults(handler=install_trigger)
    route_parser = commands.add_parser("route")
    route_parser.add_argument("--candidate", required=True)
    route_parser.add_argument("--portfolio", required=True)
    route_parser.add_argument("--global-root", action="append", required=True)
    route_parser.add_argument("--dry-run", action="store_true")
    route_parser.set_defaults(handler=catalog_routes)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--release-id")
    build_parser.set_defaults(handler=build)
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--candidate", required=True)
    validate_parser.set_defaults(handler=validate)
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--candidate", required=True)
    publish_parser.add_argument("--preserve-existing-to")
    publish_parser.add_argument("--authorize-reviewed", required=True)
    publish_parser.add_argument("--accept-active-drift-digest")
    publish_parser.add_argument("--accept-active-drift-skill", action="append")
    publish_parser.set_defaults(handler=publish)
    rollback_parser = commands.add_parser("rollback")
    rollback_parser.add_argument("--authorize-reviewed", required=True)
    rollback_parser.add_argument("--accept-active-drift-digest")
    rollback_parser.set_defaults(handler=rollback)
    status_parser = commands.add_parser("status")
    status_parser.set_defaults(handler=status)
    readiness_parser = commands.add_parser("readiness")
    readiness_parser.set_defaults(handler=readiness)
    recover_parser = commands.add_parser("recover")
    recover_parser.set_defaults(handler=recover)
    ship_parser = commands.add_parser("ship")
    ship_kind = ship_parser.add_mutually_exclusive_group()
    ship_kind.add_argument("--skill", help="Ship one checked skill using the current release record.")
    ship_kind.add_argument("--workflow", help="Release one standalone workflow to the shelf.")
    ship_parser.add_argument("--workspace", help="Promote this workspace workflow to the shared shelf.")
    ship_parser.add_argument("--source", help="Explicit workflow source file; never the released shelf.")
    ship_parser.add_argument("--approval", type=int, help="Person approval id for a workflow name over two words.")
    ship_parser.add_argument("--dry-run", action="store_true")
    ship_parser.add_argument(
        "--canary-command",
        action="append",
        help="test override in runtime=template form; supports {runtime} and {prompt}",
    )
    ship_parser.set_defaults(handler=ship)
    deliver_parser = commands.add_parser("deliver")
    candidate_group = deliver_parser.add_mutually_exclusive_group()
    candidate_group.add_argument("--candidate")
    candidate_group.add_argument("--release-id")
    deliver_parser.add_argument("--authorize-reviewed")
    deliver_parser.add_argument("--preserve-existing-to")
    deliver_parser.add_argument("--accept-active-drift-digest")
    deliver_parser.add_argument("--accept-active-drift-skill", action="append")
    deliver_parser.set_defaults(handler=deliver)
    record_parser = commands.add_parser("record-build")
    record_parser.add_argument("--source", required=True)
    record_parser.add_argument("--shelf", required=True)
    record_parser.add_argument("--output", required=True)
    record_parser.add_argument("--record-source")
    record_parser.add_argument("--record-shelf")
    record_parser.set_defaults(handler=lambda args: __import__("skill_scoped").record_build(sys.modules[__name__], args))
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        if args.command == "ship" and any(getattr(args, key, None) for key in ("workspace", "source", "approval")) and not getattr(args, "workflow", None):
            raise RuntimeError("--workspace, --source, and --approval require ship --workflow NAME.")
        return args.handler(args)
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"skill_ship.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
