#!/usr/bin/env python3
"""Load and validate the skill catalog: which skills publish, and the canary list."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


POLICY_RELATIVE_PATH = Path("config/catalog.yaml")
CANARY_REQUIRED_SKILLS = (
    "herdr",
    "magicpath",
    "orchestrate",
    "runtime-session-search",
    "tabladb",
    "telegram-organize",
    "telegram-topics",
)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError(f"duplicate policy key: {key}")
        result[key] = value
    return result


def authored_skills(root: Path) -> Path:
    """Repository skills live under skills/; release payloads stay flat."""
    return root / "skills" if (root / "skills").is_dir() else root


def root_skill_names(root: Path) -> set[str]:
    return {
        path.name
        for path in authored_skills(root).iterdir()
        if path.is_dir()
        and not path.is_symlink()
        and not path.name.startswith(".")
        and (path / "SKILL.md").is_file()
    }


def _require_sorted_unique(values: object, field: str) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise RuntimeError(f"policy {field} must be a list of names")
    if len(values) != len(set(values)):
        raise RuntimeError(f"duplicate policy classification in {field}")
    if values != sorted(values):
        raise RuntimeError(f"policy {field} must be sorted")
    return values


def load_policy(path: Path, dojo_root: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    try:
        policy = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid publication policy: {path}: {exc}") from exc
    if not isinstance(policy, dict) or policy.get("version") != 1:
        raise RuntimeError("publication policy version must be 1")

    policy = read_catalog(path, dojo_root)
    publish = _require_sorted_unique(policy.get("publish"), "publish")
    preserve = _require_sorted_unique(
        policy.get("claude_preserve_physical"), "claude_preserve_physical"
    )
    exclude = policy.get("exclude")
    host_specific = policy.get("host_specific")
    approval_required = policy.get("claude_approval_required")
    if not isinstance(exclude, dict):
        raise RuntimeError("policy exclude must be an object")
    if not isinstance(host_specific, dict):
        raise RuntimeError("policy host_specific must be an object")
    if not isinstance(approval_required, dict):
        raise RuntimeError("policy claude_approval_required must be an object")

    publish_set = set(publish)
    exclude_set = set(exclude)
    overlap = sorted(publish_set & exclude_set)
    if overlap:
        raise RuntimeError("duplicate publish/exclude classification: " + ", ".join(overlap))

    roots = root_skill_names(dojo_root)
    unclassified = sorted(roots - publish_set - exclude_set)
    missing = sorted((publish_set | exclude_set) - roots)
    if unclassified:
        raise RuntimeError("unclassified root skills: " + ", ".join(unclassified))
    if missing:
        raise RuntimeError("policy source skills do not exist: " + ", ".join(missing))

    for name, entry in sorted(exclude.items()):
        if not isinstance(entry, dict):
            raise RuntimeError(f"policy exclusion must be an object: {name}")
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            raise RuntimeError(f"policy exclusion needs a reason: {name}")
        if entry.get("status") not in {"retired", "source_only"}:
            raise RuntimeError(f"policy exclusion needs a valid status: {name}")
        if entry.get("claude") not in {"absent", "preserve_physical"}:
            raise RuntimeError(f"policy exclusion needs a Claude rule: {name}")

    invalid_preserve = sorted(set(preserve) - publish_set)
    if invalid_preserve:
        raise RuntimeError(
            "Claude physical preservation names are not published sources: "
            + ", ".join(invalid_preserve)
        )
    invalid_approvals = sorted(set(approval_required) - publish_set)
    if invalid_approvals:
        raise RuntimeError(
            "Claude approval names are not published sources: "
            + ", ".join(invalid_approvals)
        )
    decision_overlap = sorted(set(preserve) & set(approval_required))
    if decision_overlap:
        raise RuntimeError(
            "Claude names cannot be both preserved and approval-gated: "
            + ", ".join(decision_overlap)
        )
    for name, entry in sorted(approval_required.items()):
        if not isinstance(entry, dict) or entry.get("action") != "convert_to_shared_link":
            raise RuntimeError(f"invalid Claude approval decision: {name}")
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            raise RuntimeError(f"Claude approval decision needs a reason: {name}")

    collisions = sorted((publish_set | exclude_set) & set(host_specific))
    if collisions:
        raise RuntimeError(
            "host-specific names collide with Dojo sources: " + ", ".join(collisions)
        )
    for name, entry in sorted(host_specific.items()):
        if not isinstance(entry, dict):
            raise RuntimeError(f"host-specific policy must be an object: {name}")
        if entry.get("dayone_hold"):
            raise RuntimeError(entry["dayone_hold"])
        codex_source = entry.get("codex_source")
        if not isinstance(codex_source, str):
            raise RuntimeError(f"host-specific source is missing: {name}")
        source = Path(os.path.expanduser(codex_source)).resolve(strict=False)
        if not (source / "SKILL.md").is_file():
            raise RuntimeError(f"host-specific source does not exist: {name}")

    app_owned = policy.get("claude_app_owned", {})
    if not isinstance(app_owned, dict):
        raise RuntimeError("policy claude_app_owned must be an object")
    owned_collisions = sorted(
        (publish_set | exclude_set | set(host_specific)) & set(app_owned)
    )
    if owned_collisions:
        raise RuntimeError(
            "Claude app-owned names collide with shelf names: "
            + ", ".join(owned_collisions)
        )
    for name, entry in sorted(app_owned.items()):
        if not name or name.startswith(".") or name != Path(name).name:
            raise RuntimeError(f"Claude app-owned name must be one folder name: {name}")
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("reason"), str)
            or not entry["reason"].strip()
        ):
            raise RuntimeError(f"Claude app-owned folder needs a reason: {name}")

    if "fleet" in publish_set:
        if "herd" not in publish_set:
            raise RuntimeError("fleet requires published sibling herd")
        if not os.access(authored_skills(dojo_root) / "herd" / "bin" / "herd", os.X_OK):
            raise RuntimeError("fleet requires executable herd/bin/herd")

    return policy, hashlib.sha256(raw).hexdigest()


def policy_path_for(root: Path) -> Path:
    return root / POLICY_RELATIVE_PATH


def canary_checklist() -> dict:
    return {
        "fresh_sessions_required": True,
        "required_skills": list(CANARY_REQUIRED_SKILLS),
        "runtimes": ["hermes", "codex", "claude"],
        "same_session_checks_do_not_complete_activation": True,
    }


"""Catalog selection and ownership-aware runtime links. Python 3.9 standard library."""
import re
import tempfile


def skill_status(path):
    text = path.read_text(encoding='utf-8')
    front = text.split('\n---', 1)[0] if text.startswith('---\n') else ''
    match = re.search(r'^status:\s*["\']?([^\n"\']+)', front, re.M)
    return match.group(1).strip() if match else 'active'


def catalog_scope(catalog, name, source_root):
    """Absent means global; a draft or retired source never leaves the workshop."""
    page = authored_skills(source_root) / name / 'SKILL.md'
    if not page.is_file():
        return 'off'
    if page.is_file() and skill_status(page) in {'draft', 'retired'}:
        return 'off'
    value = catalog.get('where', {}).get(name, 'global')
    if value == 'off':
        return 'off'
    if isinstance(value, list) and value and all(isinstance(v, str) and re.fullmatch(r'[a-z0-9][a-z0-9-]*', v) for v in value):
        if len(set(value)) != len(value):
            raise RuntimeError('duplicate workspace in catalog: ' + name)
        return sorted(value)
    if name not in catalog.get('where', {}):
        return 'global'
    raise RuntimeError('where must be off or a nonempty workspace list: ' + name)


def read_catalog(path, source_root):
    """Return derived legacy fields for existing release tools; never write a publish list."""
    raw = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_reject_duplicate_keys)
    if raw.get('version') != 1 or not isinstance(raw.get('where', {}), dict):
        raise RuntimeError('catalog needs version 1 and a where mapping')
    result = dict(raw)
    names = root_skill_names(source_root)
    for name in raw.get('where', {}):
        if not isinstance(name, str) or name != Path(name).name or name in {'.', '..'}:
            raise RuntimeError('unsafe catalog skill name')
        catalog_scope(raw, name, source_root)
    published, excluded, workspace = [], {}, {}
    for name in sorted(names):
        scope = catalog_scope(raw, name, source_root)
        if scope == 'global':
            published.append(name)
        else:
            excluded[name] = dict(raw.get('exclude', {}).get(name, {}))
            excluded[name].update(reason=excluded[name].get('reason', 'Catalog scope or draft source.'),
                                  status='source_only', claude='absent')
            if isinstance(scope, list):
                workspace[name] = scope
    result.update(publish=published, exclude=excluded, workspace_publish=workspace)
    result['claude_preserve_physical'] = sorted(set(raw.get('claude_preserve_physical', [])) & set(published))
    result['claude_approval_required'] = {k: v for k, v in raw.get('claude_approval_required', {}).items() if k in published}
    result.setdefault('host_specific', {})
    result.setdefault('claude_app_owned', {})
    return result


def owned_link_matches(path, previous):
    if not previous or not path.is_symlink(): return False
    return os.readlink(path) == previous or path.resolve() == Path(previous).resolve()


def route_plan(catalog, source_root, candidate, portfolio, global_roots, owned, stable_shelf=None):
    """Plan only manifest-owned links. A private or divergent entry always wins."""
    candidate, portfolio = Path(candidate).resolve(), Path(portfolio).resolve()
    wanted = {}
    private_targets = set()
    for name in sorted(root_skill_names(source_root)):
        scope = catalog_scope(catalog, name, source_root)
        if scope == 'off':
            continue
        payload = candidate / name
        if not (payload / 'SKILL.md').is_file():
            raise RuntimeError('eligible skill missing from candidate: ' + name)
        if scope == 'global':
            roots = [Path(root) for root in global_roots]
            payload = Path(stable_shelf) / name if stable_shelf is not None else payload
        else:
            roots = []
            for workspace in scope:
                home = portfolio / workspace
                if home.is_symlink() or not (home / 'AGENTS.md').is_file():
                    raise RuntimeError('workspace is absent or unsafe: ' + workspace)
                roots.append(home / '.agents/skills')
                private = home / 'skills' / name
                if (private / 'SKILL.md').is_file():
                    native = str(home / '.agents/skills' / name)
                    private_targets.add(native)
                    wanted[native] = str(private.resolve())
        for root in roots:
            # A root link exposes an entire shelf. Do not mutate its referent or hide private skills.
            if root.is_symlink() or root.parent.is_symlink():
                raise RuntimeError('runtime root needs an explicit ownership migration: ' + str(root))
            target = str(root / name)
            if target not in private_targets:
                wanted[target] = str(payload)
    plan = []
    for target, source in sorted(wanted.items()):
        path = Path(target)
        exists = path.exists() or path.is_symlink()
        previous = owned.get(target)
        matches_previous = owned_link_matches(path, previous)
        if exists and not matches_previous:
            action = 'keep_private'
        elif target in private_targets:
            action = 'private_link'
        elif path.is_symlink() and os.readlink(path) == source:
            action = 'keep_owned'
        else:
            action = 'link'
        plan.append(dict(action=action, target=target, source=source, owned_source=previous))
    for target, previous in sorted(owned.items()):
        if target in wanted:
            continue
        path = Path(target)
        if owned_link_matches(path, previous):
            plan.append(dict(action='retire_owned', target=target, source=previous))
        else:
            plan.append(dict(action='keep_private', target=target, source=previous))
    return plan


def apply_route_plan(plan, owned):
    result = dict(owned)
    # Validate the complete plan first. A later invalid payload must not leave earlier links behind.
    for row in plan:
        if row['action'] not in {'link', 'private_link'}: continue
        payload = Path(row['source'])
        if row['action'] == 'link':
            paths = [payload]
            for root, dirs, files in os.walk(payload, followlinks=False):
                paths += [Path(root) / name for name in dirs + files]
            for path in paths:
                if path.is_symlink() or path.stat().st_mode & 0o222:
                    raise RuntimeError('route payload is not frozen: ' + str(path))
        elif not (payload / 'SKILL.md').is_file():
            raise RuntimeError('private workspace source disappeared')
        target = Path(row['target'])
        if target.exists() or target.is_symlink():
            if not owned_link_matches(target, row.get('owned_source')):
                raise RuntimeError('private runtime entry appeared; route refused: ' + str(target))
    for row in plan:
        path = Path(row['target'])
        if row['action'] in {'link', 'private_link'}:
            # Check every payload before writing a runtime link.
            payload = Path(row['source'])
            for root, dirs, files in os.walk(payload, followlinks=False) if row['action'] == 'link' else []:
                for name in dirs + files:
                    p = Path(root) / name
                    if p.is_symlink() or p.stat().st_mode & 0o222:
                        raise RuntimeError('route payload is not frozen: ' + str(p))
            if row['action'] == 'link' and payload.stat().st_mode & 0o222:
                raise RuntimeError('route payload root is not frozen')
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name('.' + path.name + '.route-' + str(os.getpid()))
            os.symlink(row['source'], temporary)
            os.replace(temporary, path)
            if row['action'] == 'private_link':
                # The pointer becomes a private workspace entry. Later off/global rules leave it alone.
                result.pop(str(path), None)
            else:
                result[str(path)] = row['source']
        elif row['action'] == 'retire_owned':
            # Recheck ownership immediately before removal.
            if not owned_link_matches(path, row['source']):
                raise RuntimeError('owned runtime link changed: ' + str(path))
            path.unlink()
            result.pop(str(path), None)
        elif row['action'] == 'keep_private':
            result.pop(str(path), None)
    return result
