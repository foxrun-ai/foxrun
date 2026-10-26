#!/usr/bin/env python3
"""Plan or apply a create-only workspace installation from module manifests."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import subprocess
import tempfile
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from base import pack_policy


FORMAT = 1
MAX_SOURCE_BYTES = 2_000_000
MAX_TREE_ENTRIES = 10_000
MAX_TARGET_FILE_BYTES = 100_000_000
PLACEHOLDER = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}")
# Core modules. An add-on is any other folder with install.json in the modules root or its modules/.
KNOWN_MODULES = {"base", "memory", "decisions", "events", "work"}
BASE_MODULES = {"base", "work", "memory"}
WORKSPACE_ID = re.compile(r"^[a-z][a-z0-9-]{1,80}$")
FORBIDDEN_DESTINATION_PARTS = {
    ".agents", ".claude", ".codex", ".gbrain", ".git", ".gstack", ".hermes",
    ".ob" + "sidian", ".openclaw", "auth", "configs", "credentials", "runtime",
    "runtimes", "secret", "secrets", "setting", "settings", "skill", "skills",
    "token", "tokens", "authentication", ".ssh", "keys", "mcp",
}


class InstallError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def reject_symlink_components(path: Path, label: str) -> None:
    path = canonical(path)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise InstallError(f"{label} crosses a symlink component: {current}")
        if not os.path.lexists(current):
            break


def require_existing_directory(path: Path, label: str) -> Path:
    path = canonical(path)
    reject_symlink_components(path, label)
    if not path.is_dir():
        raise InstallError(f"{label} must be an existing directory: {path}")
    return path


def within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_sandbox(target: Path, live_vault: Path) -> tuple[Path, Path]:
    target = require_existing_directory(target, "target sandbox")
    live_vault = require_existing_directory(live_vault, "live vault root")
    if within(target, live_vault) or within(live_vault, target):
        raise InstallError("target sandbox overlaps the live vault root")
    return target, live_vault


def infer_source_vault(modules_root: Path) -> Path | None:
    if modules_root.name == 'modules' and (modules_root.parent / 'AGENTS.md').is_file():
        return modules_root.parent.parent
    return None


def safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise InstallError(f"{label} must be a non-empty POSIX relative path")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise InstallError(f"{label} must not contain empty or traversal components: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        raise InstallError(f"{label} must not be absolute or contain traversal: {value!r}")
    return path.as_posix()


def safe_destination(value: Any, label: str = "manifest destination") -> str:
    relative = safe_relative(value, label)
    # These empty workspace folders are part of the day-one model.
    if relative in {'skills', 'tools/mcp', 'skills/.gitkeep', 'tools/mcp/.gitkeep'}:
        return relative
    parts = [part.lower() for part in PurePosixPath(relative).parts]
    filename = parts[-1]
    sensitive_name = re.compile(
        r"^(?:\.env(?:\.|$)|(?:auth|credential|runtime|secret|setting|skill|token)s?(?:\.|$))"
    )
    if any(part in FORBIDDEN_DESTINATION_PARTS or sensitive_name.match(part) for part in parts):
        raise InstallError(f"{label} enters a runtime, skill, config, or auth path: {relative}")
    if filename == ".mcp.json" or filename == ".env" or filename.startswith(".env."):
        raise InstallError(f"{label} names a runtime, config, or auth file: {relative}")
    return relative


def validate_install_metadata(
    workspace: str, timestamp: str, approved_tags: list[str],
) -> tuple[str, str, list[str]]:
    if not isinstance(workspace, str) or not WORKSPACE_ID.fullmatch(workspace):
        raise InstallError("target workspace must be a lowercase workspace id")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise InstallError("install timestamp must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise InstallError("install timestamp must include a timezone")
    if not isinstance(approved_tags, list) or not all(
        isinstance(tag, str) and tag and "\n" not in tag for tag in approved_tags
    ):
        raise InstallError("approved tags must be a JSON list of non-empty strings")
    if len(approved_tags) != len(set(approved_tags)):
        raise InstallError("approved tags must be unique")
    return workspace, timestamp, approved_tags


def safe_source(root: Path, relative: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    reject_symlink_components(path, "manifest source")
    if not path.is_file():
        raise InstallError(f"manifest source is missing or not a file: {path}")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise InstallError(f"manifest source exceeds {MAX_SOURCE_BYTES} bytes: {path}")
    return path


def read_source(path: Path) -> bytes:
    reject_symlink_components(path, "source")
    if not path.is_file():
        raise InstallError(f"source is missing: {path}")
    size = path.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise InstallError(f"source exceeds {MAX_SOURCE_BYTES} bytes: {path}")
    return path.read_bytes()


def source_record(path: Path, kind: str) -> dict[str, Any]:
    data = read_source(path)
    return {"path": str(canonical(path)), "kind": kind, "bytes": len(data), "sha256": sha256(data)}


def parse_modules(raw: str, workspace_type: str, modules_root: Path | None = None) -> list[str]:
    requested = [item.strip() for item in raw.split(",") if item.strip()]
    if len(requested) != len(set(requested)):
        raise InstallError("module list contains duplicates")
    addons = set()
    if modules_root is not None:
        addons = {path.parent.name for pattern in ('*/install.json', 'modules/*/install.json')
                  for path in Path(modules_root).glob(pattern)}
    unknown = sorted(set(requested) - KNOWN_MODULES - addons)
    if unknown:
        raise InstallError("unknown modules: " + ", ".join(unknown))
    missing_base = sorted(BASE_MODULES - set(requested))
    if missing_base:
        raise InstallError("module list omits base-tier modules: " + ", ".join(missing_base))
    if modules_root is not None:
        for module in sorted(set(requested) - KNOWN_MODULES):
            needed = set(load_manifest(Path(modules_root), module)[0].get("requires", [])) - set(requested)
            if needed:
                raise InstallError(module + " requires " + ", ".join(sorted(needed)))
    return sorted(requested, key=lambda name: (name != "base", name))


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(read_source(path).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise InstallError(f"{label} is not valid UTF-8 JSON: {path}") from error


def load_manifest(modules_root: Path, module: str) -> tuple[dict[str, Any], Path]:
    module_root = (modules_root / 'modules' / module if (modules_root / 'modules' / module).is_dir() else modules_root / module)
    path = safe_source(module_root, "install.json")
    data = load_json(path, "install manifest")
    if isinstance(data, dict) and not pack_policy.ships(data):
        raise InstallError("module is not shipped: " + module)
    if not isinstance(data, dict) or not {"files", "blueprint"} <= set(data) <= {"files", "blueprint", "ships", "needs", "requires"}:
        raise InstallError(f"unsupported manifest shape: {path}")
    if not isinstance(data["blueprint"], bool) or not isinstance(data["files"], list):
        raise InstallError(f"unsupported manifest policy types: {path}")
    # needs: outside programs a module uses. The installer lists them and installs none.
    if not isinstance(data.get("needs", []), list):
        raise InstallError(f"unsupported needs list: {path}")
    for index, item in enumerate(data.get("needs", [])):
        if not isinstance(item, dict) or set(item) != {"program", "why", "get", "reader"} or not all(
                isinstance(value, str) and value for value in item.values()):
            raise InstallError(f"unsupported needs row at {path}:{index + 1}")
    for index, item in enumerate(data["files"]):
        if not isinstance(item, dict) or set(item) != {"from", "to", "if_exists"}:
            raise InstallError(f"unsupported file policy at {path}:{index + 1}")
        if item["if_exists"] != "skip":
            raise InstallError(f"unsupported if_exists policy at {path}:{index + 1}")
    return data, path


def scan_tree(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pending = [root]
    count = 0
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > MAX_TREE_ENTRIES:
                    raise InstallError(f"target tree exceeds {MAX_TREE_ENTRIES} entries")
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode):
                    raise InstallError(f"target tree contains a symlink: {relative}")
                if stat.S_ISDIR(metadata.st_mode):
                    rows.append({"path": relative, "type": "directory"})
                    pending.append(path)
                elif stat.S_ISREG(metadata.st_mode):
                    if metadata.st_size > MAX_TARGET_FILE_BYTES:
                        raise InstallError(f"target file exceeds {MAX_TARGET_FILE_BYTES} bytes: {relative}")
                    data = path.read_bytes()
                    rows.append({"path": relative, "type": "file", "bytes": len(data), "sha256": sha256(data)})
                else:
                    raise InstallError(f"target tree contains an unsupported object: {relative}")
    return sorted(rows, key=lambda row: row["path"])


def render_template(data: bytes, values: dict[str, str], path: Path) -> tuple[bytes, list[str]]:
    try:
        text = data.decode("utf-8")
    except UnicodeError as error:
        raise InstallError(f"template is not UTF-8: {path}") from error
    needed = sorted(set(PLACEHOLDER.findall(text)))
    missing = sorted(set(needed) - set(values))
    if missing:
        raise InstallError(f"unresolved placeholders in {path}: " + ", ".join(missing))
    rendered = PLACEHOLDER.sub(lambda match: values[match.group(1)], text)
    unresolved = sorted(set(PLACEHOLDER.findall(rendered)))
    if unresolved:
        raise InstallError(f"rendered template still has placeholders in {path}: " + ", ".join(unresolved))
    return rendered.encode("utf-8"), needed


def stamp_markdown_metadata(
    data: bytes, *, workspace: str, timestamp: str, approved_tags: list[str], path: Path,
) -> tuple[bytes, dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeError as error:
        raise InstallError(f"rendered Markdown is not UTF-8: {path}") from error
    lines = text.splitlines(keepends=True)
    metadata = {
        "workspace": json.dumps(workspace, ensure_ascii=False),
        "timestamp": json.dumps(timestamp, ensure_ascii=False),
        "tags": json.dumps(approved_tags, ensure_ascii=False),
    }
    status = None
    if lines and lines[0].strip() == "---":
        end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
        if end is None:
            raise InstallError(f"Markdown frontmatter has no closing delimiter: {path}")
        frontmatter = lines[1:end]
        body = "".join(lines[end + 1:])
    else:
        frontmatter = []
        body = text
    found: set[str] = set()
    stamped: list[str] = []
    previous_key = None
    for line in frontmatter:
        if re.match(r"^[\"'](?:workspace|timestamp|tags)[\"']\s*:", line):
            raise InstallError(f"quoted install metadata keys are unsupported: {path}")
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):", line)
        if not match:
            if previous_key in metadata and line.strip() and not line.lstrip().startswith("#"):
                raise InstallError(f"multiline install metadata is unsupported: {path}")
            stamped.append(line)
            continue
        key = match.group(1)
        previous_key = key
        if key in found:
            raise InstallError(f"duplicate top-level Markdown metadata key {key!r}: {path}")
        found.add(key)
        if key == "status":
            status = line.split(":", 1)[1].strip() or None
        if key in metadata:
            stamped.append(f"{key}: {metadata[key]}\n")
        else:
            stamped.append(line)
    for key in ("workspace", "timestamp", "tags"):
        if key not in found:
            stamped.append(f"{key}: {metadata[key]}\n")
    output = "---\n" + "".join(stamped) + "---\n" + body
    return output.encode("utf-8"), {
        "status": status or "not declared",
        "acceptance": "not accepted by installer",
        "metadata_stamped": ["workspace", "timestamp", "tags"],
    }


def plan_hash(plan: dict[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_sha256"}
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def semantic_payload(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if key != "plan_sha256"}


def render_action_content(plan: dict[str, Any], action: dict[str, Any]) -> tuple[bytes, list[str], dict[str, Any] | None]:
    source = canonical(Path(action["source"]))
    data = read_source(source)
    rendered, needed = render_template(data, plan["values"], source)
    state = None
    if PurePosixPath(action["destination"]).suffix.lower() == ".md":
        metadata = plan["install_metadata"]
        rendered, state = stamp_markdown_metadata(
            rendered,
            workspace=metadata["workspace"],
            timestamp=metadata["timestamp"],
            approved_tags=metadata["approved_tags"],
            path=source,
        )
    return rendered, needed, state


def verify_source_record(record: dict[str, Any], modules_root: Path) -> None:
    path = canonical(Path(record["path"]))
    if not within(path, modules_root):
        raise InstallError("plan source escapes the modules root: " + str(path))
    data = read_source(path)
    if len(data) != record["bytes"] or sha256(data) != record["sha256"]:
        raise InstallError("source changed after the plan was created: " + str(path))


# One database: the system data.db. A workspace never gets its own.
# install.py builds the tables of every shipped pack, add-ons included, in that one file.
ONE_DATABASE = ("a workspace gets no database of its own; "
                "the tables of every pack, add-ons included, go in the system data.db, which install.py builds")


def target_row(target: Path, relative: str) -> dict[str, Any] | None:
    path = target.joinpath(*PurePosixPath(relative).parts)
    if not os.path.lexists(path):
        return None
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise InstallError(f"target destination is a symlink: {relative}")
    if stat.S_ISREG(metadata.st_mode):
        data = path.read_bytes()
        return {"type": "file", "bytes": len(data), "sha256": sha256(data)}
    if stat.S_ISDIR(metadata.st_mode):
        return {"type": "directory"}
    raise InstallError(f"target destination has unsupported type: {relative}")


def plan_install(
    *, modules_root: Path, target: Path, live_vault: Path, workspace_type: str,
    raw_modules: str, values: dict[str, str], target_workspace: str, install_timestamp: str,
    approved_tags: list[str], database: str | None, actor: str | None,
) -> dict[str, Any]:
    if database is not None or actor is not None:
        raise InstallError("database step refused: " + ONE_DATABASE)
    modules_root = require_existing_directory(modules_root, "modules root")
    target, live_vault = validate_sandbox(target, live_vault)
    source_vault = infer_source_vault(modules_root)
    if source_vault and (within(target, source_vault) or within(source_vault, target)):
        raise InstallError("target sandbox overlaps the inferred legacy module source vault")
    modules = parse_modules(raw_modules, workspace_type, modules_root)
    if not isinstance(values, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in values.items()):
        raise InstallError("placeholder values must be a JSON object of strings")
    target_workspace, install_timestamp, approved_tags = validate_install_metadata(
        target_workspace, install_timestamp, approved_tags,
    )
    explicit_values = dict(values)
    values = dict(values)
    # Defaults belong to the selected module, not to an installer wrapper.
    default_sources = {}
    defaults = {}
    for module in modules:
        _, manifest_path = load_manifest(modules_root, module)
        default_path = manifest_path.parent / 'defaults.json'
        if default_path.exists():
            supplied = load_json(default_path, 'module defaults')
            if not isinstance(supplied, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in supplied.items()
            ):
                raise InstallError('module defaults must be a JSON object of strings')
            defaults.update(supplied)
            record = source_record(default_path, 'defaults:' + module)
            default_sources[record['path']] = record
    person_path = modules_root / 'config/person.json'
    if person_path.exists():
        person = load_json(person_path, 'person configuration')
        if not isinstance(person, dict) or not isinstance(person.get('name'), str) or not person['name']:
            raise InstallError('config/person.json must contain a person name')
        defaults['owner'] = person['name']
        record = source_record(person_path, 'person-configuration')
        default_sources[record['path']] = record
    values = dict(defaults, **values)
    metadata_values = {
        "workspace": target_workspace,
        "timestamp": install_timestamp,
        "approved_tags": json.dumps(approved_tags, ensure_ascii=False),
    }
    for key, expected in metadata_values.items():
        if key in explicit_values and explicit_values[key] != expected:
            raise InstallError(f"placeholder value {key!r} conflicts with explicit install metadata")
        values[key] = expected
    before = scan_tree(target)
    existing_paths = {row["path"]: row for row in before}
    sources: dict[str, dict[str, Any]] = dict(default_sources)
    destinations: dict[str, dict[str, Any]] = {}
    required: set[str] = set()

    for module in modules:
        manifest, manifest_path = load_manifest(modules_root, module)
        manifest_record = source_record(manifest_path, f"manifest:{module}")
        sources[manifest_record["path"]] = manifest_record
        module_root = (modules_root / 'modules' / module if (modules_root / 'modules' / module).is_dir() else modules_root / module)
        for entry in manifest["files"]:
            source_relative = safe_relative(entry["from"], "manifest source")
            destination = safe_destination(entry["to"])
            source_path = safe_source(module_root, source_relative)
            source_bytes = read_source(source_path)
            source_item = source_record(source_path, f"template:{module}")
            sources[source_item["path"]] = source_item
            rendered, needed = render_template(source_bytes, values, source_path)
            new_content_state = None
            if PurePosixPath(destination).suffix.lower() == ".md":
                rendered, new_content_state = stamp_markdown_metadata(
                    rendered,
                    workspace=target_workspace,
                    timestamp=install_timestamp,
                    approved_tags=approved_tags,
                    path=source_path,
                )
            required.update(needed)
            proposed = {
                "destination": destination,
                "source": str(source_path),
                "modules": [module],
                "content_sha256": sha256(rendered),
                "bytes": len(rendered),
                "placeholders": needed,
                "new_content_state": new_content_state,
            }
            prior = destinations.get(destination)
            if prior:
                if prior["content_sha256"] != proposed["content_sha256"]:
                    raise InstallError(f"conflicting duplicate manifest destination: {destination}")
                prior["modules"] = sorted(set(prior["modules"] + [module]))
                continue
            destinations[destination] = proposed

    actions: list[dict[str, Any]] = []
    needed_dirs: set[str] = set()
    for destination, item in sorted(destinations.items()):
        parts = PurePosixPath(destination).parts[:-1]
        for depth in range(1, len(parts) + 1):
            parent = PurePosixPath(*parts[:depth]).as_posix()
            existing = existing_paths.get(parent)
            if existing and existing["type"] != "directory":
                raise InstallError(f"destination parent is not a directory: {parent}")
            if not existing:
                needed_dirs.add(parent)
        collision = target_row(target, destination)
        action = "preserve-existing" if collision else "create-file"
        actions.append({"action": action, **item, "target_before": collision})
    actions = [
        {"action": "create-directory", "destination": path}
        for path in sorted(needed_dirs, key=lambda value: (len(PurePosixPath(value).parts), value))
    ] + actions

    after = {row["path"]: dict(row) for row in before}
    for action in actions:
        destination = action["destination"]
        if action["action"] == "create-directory":
            after[destination] = {"path": destination, "type": "directory"}
        elif action["action"] == "create-file":
            after[destination] = {
                "path": destination, "type": "file", "bytes": action["bytes"],
                "sha256": action["content_sha256"],
            }

    plan = {
        "format": FORMAT,
        "workspace_type": workspace_type,
        "modules": modules,
        "modules_root": str(modules_root),
        "target_root": str(target),
        "live_vault_root": str(live_vault),
        "inferred_source_vault": str(source_vault) if source_vault else None,
        "install_metadata": {
            "workspace": target_workspace,
            "timestamp": install_timestamp,
            "approved_tags": approved_tags,
            "acceptance": "not accepted by installer",
        },
        "values": {key: values[key] for key in sorted(required)},
        "required_placeholders": sorted(required),
        "sources": [sources[key] for key in sorted(sources)],
        "before_tree": before,
        "after_tree": [after[key] for key in sorted(after)],
        "actions": actions,
        "database": None,
        "limitations": [
            "Manifests still point to first-pass templates; this installer does not switch to templates-v2.",
            "Generated CAPABILITIES.md and index.md files are stubs, not accepted contracts or completed generators.",
            "New Markdown receives target workspace, timestamp, and approved tags; source status remains unchanged and unapproved.",
            "Workspace type validates the explicit module list; it does not invent a final installation manifest.",
            "Skills, runtime files, configuration, and registries are outside this package.",
        ],
    }
    plan["plan_sha256"] = plan_hash(plan)
    return plan


def verify_plan(plan: dict[str, Any]) -> None:
    if plan.get("format") != FORMAT or plan.get("plan_sha256") != plan_hash(plan):
        raise InstallError("plan format or drift hash is invalid")
    target, live_vault = validate_sandbox(Path(plan["target_root"]), Path(plan["live_vault_root"]))
    if str(target) != plan["target_root"] or str(live_vault) != plan["live_vault_root"]:
        raise InstallError("plan root identity changed")
    if scan_tree(target) != plan["before_tree"]:
        raise InstallError("target changed after the plan was created")
    modules_root = require_existing_directory(Path(plan["modules_root"]), "modules root")
    inferred_source_vault = infer_source_vault(modules_root)
    if plan.get("inferred_source_vault") != (str(inferred_source_vault) if inferred_source_vault else None):
        raise InstallError("inferred source-vault boundary changed")
    if inferred_source_vault and (within(target, inferred_source_vault) or within(inferred_source_vault, target)):
        raise InstallError("target sandbox overlaps the inferred legacy module source vault")
    if not isinstance(plan.get("values"), dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in plan["values"].items()
    ):
        raise InstallError("plan placeholder values are invalid")
    metadata = plan.get("install_metadata")
    if not isinstance(metadata, dict):
        raise InstallError("plan install metadata is missing")
    validate_install_metadata(
        metadata.get("workspace"), metadata.get("timestamp"), metadata.get("approved_tags"),
    )
    if plan.get("database") is not None:
        raise InstallError("plan has a database step: " + ONE_DATABASE)
    reconstructed = plan_install(
        modules_root=modules_root,
        target=target,
        live_vault=live_vault,
        workspace_type=plan["workspace_type"],
        raw_modules=",".join(plan["modules"]),
        values=plan["values"],
        target_workspace=metadata["workspace"],
        install_timestamp=metadata["timestamp"],
        approved_tags=metadata["approved_tags"],
        database=None,
        actor=None,
    )
    if semantic_payload(reconstructed) != semantic_payload(plan):
        raise InstallError("saved plan does not match a reconstruction from manifests and recorded inputs")
    for record in plan["sources"]:
        verify_source_record(record, modules_root)
    for action in plan["actions"]:
        destination = safe_destination(action.get("destination"), "plan destination")
        if action.get("action") not in {
            "create-directory", "create-file", "preserve-existing",
        }:
            raise InstallError("plan action is unsupported: " + str(action.get("action")))
        if action["action"] != "create-file":
            continue
        source = canonical(Path(action["source"]))
        if not within(source, modules_root):
            raise InstallError("file action source escapes the modules root: " + str(source))
        rendered, needed, state = render_action_content(plan, action)
        if (
            needed != action["placeholders"]
            or state != action.get("new_content_state")
            or len(rendered) != action["bytes"]
            or sha256(rendered) != action["content_sha256"]
        ):
            raise InstallError("rendered source changed after the plan was created: " + action["destination"])


def publish_bytes(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".install-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise InstallError("target appeared during apply: " + str(path)) from error
    finally:
        temporary.unlink(missing_ok=True)


def created_file_record(path: Path, expected_sha256: str) -> dict[str, Any]:
    metadata = path.lstat()
    return {
        "path": path,
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "sha256": expected_sha256,
    }


def created_directory_record(path: Path) -> dict[str, Any]:
    metadata = path.lstat()
    return {"path": path, "device": metadata.st_dev, "inode": metadata.st_ino}


def rollback_created(
    files: list[dict[str, Any]], directories: list[dict[str, Any]], target: Path,
) -> list[str]:
    unresolved: list[str] = []
    for record in reversed(files):
        path = record["path"]
        relative = path.relative_to(target).as_posix()
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(metadata.st_mode) or (metadata.st_dev, metadata.st_ino) != (record["device"], record["inode"]):
            unresolved.append(relative + " changed identity")
            continue
        if sha256(path.read_bytes()) != record["sha256"]:
            unresolved.append(relative + " changed bytes")
            continue
        path.unlink()
    for record in reversed(directories):
        path = record["path"]
        relative = path.relative_to(target).as_posix()
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(metadata.st_mode) or (metadata.st_dev, metadata.st_ino) != (record["device"], record["inode"]):
            unresolved.append(relative + " changed identity")
            continue
        try:
            path.rmdir()
        except OSError:
            unresolved.append(relative + " is no longer empty")
    return unresolved


def apply_plan(plan: dict[str, Any]) -> dict[str, Any]:
    verify_plan(plan)
    target = Path(plan["target_root"])
    created_files: list[dict[str, Any]] = []
    created_dirs: list[dict[str, Any]] = []
    try:
        for action in plan["actions"]:
            if action["action"] != "create-directory":
                continue
            path = target.joinpath(*PurePosixPath(action["destination"]).parts)
            reject_symlink_components(path.parent, "target parent")
            try:
                path.mkdir()
                created_dirs.append(created_directory_record(path))
            except FileExistsError as error:
                raise InstallError("target directory appeared during apply: " + str(path)) from error
        for action in plan["actions"]:
            if action["action"] != "create-file":
                continue
            path = target.joinpath(*PurePosixPath(action["destination"]).parts)
            reject_symlink_components(path.parent, "target parent")
            rendered, _, _ = render_action_content(plan, action)
            if sha256(rendered) != action["content_sha256"]:
                raise InstallError("source changed during apply: " + action["destination"])
            publish_bytes(path, rendered)
            created_files.append(created_file_record(path, action["content_sha256"]))
    except Exception as error:
        unresolved = rollback_created(created_files, created_dirs, target)
        if unresolved:
            raise InstallError(
                str(error) + "; rollback preserved changed paths: " + ", ".join(unresolved)
            ) from error
        raise
    # A new registered workspace must appear in the installed views now.
    home = Path(os.environ.get('FOXRUN_HOME', '~/.foxrun')).expanduser()
    portfolio = Path(os.environ.get('FOXRUN_PORTFOLIO', '~/foxrun')).expanduser()
    script = home / 'base/make_workspaces_view.py'
    if target.parent.resolve() == portfolio.resolve() and script.is_file() and (target / 'AGENTS.md').is_file():
        subprocess.run([sys.executable, '-B', str(script), '--system-home', str(home),
                        '--workspace-root', str(portfolio)], check=True)
    return {
        "plan_sha256": plan["plan_sha256"],
        "created_files": [record["path"].relative_to(target).as_posix() for record in created_files],
        "preserved": [action["destination"] for action in plan["actions"] if action["action"] == "preserve-existing"],
        "after_tree": scan_tree(target),
    }


def write_plan(path: Path, plan: dict[str, Any], target: Path) -> None:
    path = canonical(path)
    reject_symlink_components(path.parent, "plan output parent")
    path.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink_components(path.parent, "plan output parent")
    if within(path, target):
        raise InstallError("plan output must be outside the target sandbox")
    data = (json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", metavar="PLAN_JSON")
    parser.add_argument("--modules-root")
    parser.add_argument("--workspace-type", choices=("personal", "ecom"))
    parser.add_argument("--modules")
    parser.add_argument("--target-workspace")
    parser.add_argument("--install-timestamp")
    parser.add_argument("--approved-tags", help="JSON list of approved target tags.")
    parser.add_argument("--target")
    parser.add_argument("--live-vault-root")
    parser.add_argument("--values-json")
    parser.add_argument("--plan-out")
    parser.add_argument("--database", help="Refused: " + ONE_DATABASE + ".")
    parser.add_argument("--by", help="Refused with --database.")
    return parser


def run(args: argparse.Namespace) -> int:
    if args.apply:
        supplied = [
            args.modules_root, args.workspace_type, args.modules, args.target,
            args.target_workspace, args.install_timestamp, args.approved_tags,
            args.live_vault_root, args.values_json, args.plan_out, args.database, args.by,
        ]
        if any(value is not None for value in supplied):
            raise InstallError("--apply cannot be combined with planning arguments")
        plan = load_json(Path(args.apply), "install plan")
        if not isinstance(plan, dict):
            raise InstallError("install plan must be a JSON object")
        print(json.dumps(apply_plan(plan), indent=2, sort_keys=True))
        return 0
    required = {
        "--modules-root": args.modules_root,
        "--workspace-type": args.workspace_type,
        "--modules": args.modules,
        "--target-workspace": args.target_workspace,
        "--install-timestamp": args.install_timestamp,
        "--approved-tags": args.approved_tags,
        "--target": args.target,
        "--live-vault-root": args.live_vault_root,
        "--values-json": args.values_json,
        "--plan-out": args.plan_out,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise InstallError("planning requires " + ", ".join(missing))
    values = load_json(Path(args.values_json), "placeholder values")
    try:
        approved_tags = json.loads(args.approved_tags)
    except json.JSONDecodeError as error:
        raise InstallError("--approved-tags must be a JSON list") from error
    plan = plan_install(
        modules_root=Path(args.modules_root), target=Path(args.target),
        live_vault=Path(args.live_vault_root), workspace_type=args.workspace_type,
        raw_modules=args.modules, values=values,
        target_workspace=args.target_workspace, install_timestamp=args.install_timestamp,
        approved_tags=approved_tags, database=args.database, actor=args.by,
    )
    write_plan(Path(args.plan_out), plan, Path(plan["target_root"]))
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv))
    except (InstallError, OSError, KeyError, TypeError) as error:
        print("install failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
