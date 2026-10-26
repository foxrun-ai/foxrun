#!/usr/bin/env python3
"""Create, render, compare, apply, and probe agent-team identities."""
from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import json
import re
import shutil
import os
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import sys as _shared_sys
from pathlib import Path as _SharedPath
_shared_sys.path.insert(0, str(_SharedPath(__file__).resolve().parents[2]))
from base import simple_yaml as yaml, paths as system_paths

try:
    from .paths import roots, hermes_available
except ImportError:  # pragma: no cover
    from paths import roots, hermes_available

MARKER = "managed-by: agent-new v1"
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
RUNTIMES = {"hermes", "claude", "codex"}
HERMES_MODES = {"profile", "child", "kanban", "none"}
REQUIRED = {
    "id", "display_name", "role", "summary", "tier", "shared", "runtimes",
    "hermes_mode", "hermes_profile", "skills", "tools", "return_default",
    "version",
}
# SCHEMA.md front matter: type, workspace, and one ISO timestamp with an offset; never created/updated.
# Older workspace identities still carry created until their reviewed migration.
PAGE_TYPE = "agent-soul"
ISO_OFFSET_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:\d{2}|Z)$")

WRITE_STATE_HEADING = "## How you write state"
WRITE_STATE_MAX_LINES = 25
# The one state-writing rule every seat and worker carries. create scaffolds it verbatim.
# Wording matches the seats since b7e8752 (T630: core agent pages name no person).
WRITE_STATE_SECTION = """## How you write state

This rule holds with or without a skill attached. Rows, not chats.
Every command starts with `python3 ${FOXRUN_HOME:-$HOME/.foxrun}/work/work.py --db ${FOXRUN_HOME:-$HOME/.foxrun}/data.db --receipt-root ${FOXRUN_HOME:-$HOME/.foxrun}`.
Every command ends with `--by <id>`, where `<id>` is your frontmatter `id`.
The seven moves, in this order:

1. A task row before work. Find the existing row, or make one: `create --title "<title>" --project <stream>`. It prints the task id.
2. Claim it: `claim <task>`.
3. Start the run: `run-start <task> --model <model> --runtime <runtime> --session <session>`. It prints the run id.
4. Comment as you go: `comment <task> "<text>"`. The person's words go in verbatim, in a comment that starts with their name and a colon. The name is the `name` in `~/.foxrun/config/person.json`.
5. End the run: `run-end <run> --result <result> --evidence <path>`. The path is relative to the receipt root.
6. Close with proof: `done <task> --proof <path> --note "<one line>"`. Another seat accepts it.
7. Side rows, when they happen:
   `bug-open --id <bug> --title "<title>" --capability "<capability>"`
   `approval-add <task> --call approve --person-words "<their words>" --source comment:<n>`
   `decision-add --id <slug> --name "<name>" --statement "<statement>" --person-words "<their words>" --source comment:<n>`
`--person-words` records the person's exact words.

Same turn, a row: see `~/.foxrun/profile/AGENTS.md`.
The row comes first. The answer comes second.
A newer ruling kills the older version.
When you write or read a decision row with a replaces field, the replaced statement is dead: drop it from your working picture and never present it again as settled.
Before you call anything settled, check decisions.replaces for a newer row.
New words: write a new word with its old name, what it is related to, what is in it, and what it replaces.
"""

@dataclass
class Identity:
    data: dict[str, Any]
    body: str
    path: Path

AgentNewError = ValueError
def utc_now() -> datetime:
    return datetime.now(timezone.utc)
def stamp() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%S%fZ")
def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")
def csv_list(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]
def read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return deepcopy(default)
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    return deepcopy(default) if value is None else value
def safe_new_path(path: Path) -> None:
    r = roots()
    old = [Path.home() / "Obsidian", Path.home() / "Code", Path.home() / ".agents"]
    lexical = Path(os.path.abspath(path.expanduser()))
    real = lexical.resolve()
    if any(p == lexical or p in lexical.parents or p == real or p in real.parents for p in old):
        raise AgentNewError("Locked old place refused; use ~/.foxrun or ~/foxrun.")
    if not any(real == p.resolve() or p.resolve() in real.parents for p in [r["system"], r["portfolio"]]):
        raise AgentNewError("Agent write leaves the new homes; refused.")

def check_write(path: Path) -> None:
    """Refuse a write before it happens: the new homes, then the system home's ownership guard."""
    safe_new_path(path)
    declared = roots()["system"]
    system = declared.resolve()
    if path.resolve() == system or system in path.resolve().parents:
        sys.path.insert(0, str(system))
        from base.ownership import allowed
        # The declared home, not its real path: the guard maps a home behind a link (macOS /var) itself.
        ok, message = allowed(declared, path)
        if not ok:
            raise AgentNewError(message)

class Journal:
    """What one run wrote, so a failed create removes its own files and nothing else."""
    def __init__(self) -> None:
        self.entries: list[tuple[Path, bytes | None, str | None]] = []
        self.folders: list[Path] = []

    def before(self, path: Path) -> None:
        missing = [parent for parent in [path.parent, *path.parent.parents] if not parent.exists()]
        self.folders.extend(missing)  # deepest first
        previous = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        self.entries.append((path, previous, None))

    def wrote(self, text: str | None = None, link: str | None = None) -> None:
        path, previous, _ = self.entries[-1]
        self.entries[-1] = (path, previous, ("link:" + link) if link is not None else text)

    def undo(self) -> list[str]:
        """Restore or remove each path this run wrote, newest first, only if it still holds this run's bytes."""
        left: list[str] = []
        for path, previous, written in reversed(self.entries):
            if written is None:
                continue
            if written.startswith("link:") and previous is None:
                ours = path.is_symlink() and os.readlink(path) == written[5:]
            else:
                ours = path.is_file() and not path.is_symlink() and path.read_text(encoding="utf-8", errors="replace") == written
            if not ours:
                left.append(str(path))
                continue
            if previous is None:
                path.unlink()
            else:
                path.write_bytes(previous)
        for folder in sorted(set(self.folders), key=lambda f: len(f.parts), reverse=True):
            try:
                folder.rmdir()  # only an empty folder this run made
            except OSError:
                pass
        return left

def write_text(path: Path, text: str, journal: Journal | None = None) -> None:
    check_write(path)
    if journal is not None:
        journal.before(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if journal is not None:
        journal.wrote(text)
def yaml_text(value: Any) -> str:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
def policy(repo: Path) -> dict[str, Any]:
    sys.path.insert(0, str(roots()["system"]))
    from base.agent_catalog import model_policy
    try:
        return model_policy(roots()["system"])
    except ValueError as exc:
        raise AgentNewError(str(exc)) from exc
def resolve_capabilities(data, path):
    sys.path.insert(0, str(roots()["system"]))
    from base.agent_catalog import expand
    return expand(data, path)
def split_identity(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise AgentNewError("Identity frontmatter must start with ---.")
    try:
        front, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise AgentNewError("Identity frontmatter has no closing ---.") from exc
    data = yaml.safe_load(front)
    if not isinstance(data, dict):
        raise AgentNewError("Identity frontmatter must be a YAML mapping.")
    return data, body
def is_identity_page(path: Path) -> bool:
    """True for an identity page: front matter with type agent-soul, or no type (the legacy shape).
    README.md, soul.md (base-soul), and other typed pages in agents/ are not identities."""
    if path.name == "README.md":
        return False
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return False
    data, _ = split_identity(text)
    return data.get("type", PAGE_TYPE) == PAGE_TYPE
def validate_identity(identity: Identity, repo: Path) -> None:
    data = identity.data
    missing = sorted(REQUIRED - data.keys())
    if missing:
        raise AgentNewError("Missing required identity keys: " + ", ".join(missing))
    agent_id = data["id"]
    if not isinstance(agent_id, str) or not ID_RE.fullmatch(agent_id):
        raise AgentNewError(f"Invalid identity id: {agent_id!r}")
    if identity.path.stem != agent_id:
        raise AgentNewError("Identity id must match its filename.")
    tiers = policy(repo).get("tiers", {})
    if data["tier"] not in tiers:
        raise AgentNewError(f"Invalid tier: {data['tier']}")
    runtimes = data["runtimes"]
    if not isinstance(runtimes, list) or not set(runtimes).issubset(RUNTIMES):
        raise AgentNewError("Runtimes must contain Claude and Codex on day one.")
    mode = data["hermes_mode"]
    if mode not in HERMES_MODES:
        raise AgentNewError(f"Invalid hermes_mode: {mode}")
    expected = agent_id if mode in {"profile", "kanban"} else None
    if data["hermes_profile"] != expected:
        raise AgentNewError(f"hermes_profile must be {expected!r} for mode {mode}.")
    for key in ("display_name", "role", "summary"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise AgentNewError(f"{key} must be a non-empty string.")
    if not isinstance(data["shared"], bool):
        raise AgentNewError("shared must be true or false.")
    for key in ("skills", "tools"):
        if not isinstance(data[key], list) or not all(isinstance(x, str) for x in data[key]):
            raise AgentNewError(f"{key} must be a list of strings.")
    if not isinstance(data["version"], int) or data["version"] < 1:
        raise AgentNewError("version must be a positive integer.")
    if "timestamp" in data:
        if "created" in data or "updated" in data:
            raise AgentNewError("Use one timestamp; drop created and updated.")
        if not isinstance(data["timestamp"], str) or not ISO_OFFSET_RE.fullmatch(data["timestamp"]):
            raise AgentNewError("timestamp must be ISO 8601 with a time and an offset.")
        for key in ("type", "workspace"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise AgentNewError(f"{key} must be a non-empty string.")
    elif "created" not in data:
        raise AgentNewError("Missing required identity keys: timestamp")
    lines = identity.body.splitlines()
    # Two accepted shapes. v2 (2026-09-18): the agent writes three sections and the base soul
    # (soul.md) is appended at render. v1: the older six sections, still valid until migrated.
    shapes = [
        [f"# {data['display_name']}", "## Identity", "## What You Own", "## Judgment"],
        [f"# {data['display_name']}", "## Who you are", "## Responsibility", "## Judgment"],
        [f"# {data['display_name']}", "## Responsibility", "## Judgment", "## Style", "## Limits", "## Return"],
    ]
    def _ordered(headings: list[str]) -> bool:
        positions = [lines.index(heading) if heading in lines else -1 for heading in headings]
        return -1 not in positions and positions == sorted(positions)
    if not any(_ordered(headings) for headings in shapes):
        raise AgentNewError("Identity body must contain the required sections in order: Who you are, Responsibility, Judgment (or the older six).")
    # Boot reads (2026-09-26): optional fifth section, required for seats by docs/identity-format.md.
    if "## Boot reads" in lines and not _ordered(["## Judgment", "## Boot reads"]):
        raise AgentNewError("## Boot reads must come after ## Judgment.")
    # How you write state: required for seats and workers by docs/identity-format.md.
    # It sits after ## Judgment and before ## Boot reads.
    if WRITE_STATE_HEADING in lines:
        if not _ordered(["## Judgment", WRITE_STATE_HEADING]):
            raise AgentNewError("## How you write state must come after ## Judgment.")
        if "## Boot reads" in lines and not _ordered([WRITE_STATE_HEADING, "## Boot reads"]):
            raise AgentNewError("## How you write state must come before ## Boot reads.")
        start = lines.index(WRITE_STATE_HEADING)
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        while end > start and not lines[end - 1].strip():
            end -= 1
        if end - start > WRITE_STATE_MAX_LINES:
            raise AgentNewError(f"## How you write state exceeds {WRITE_STATE_MAX_LINES} lines.")
    if len(lines) > 400:
        raise AgentNewError("Identity body exceeds 400 lines.")
def load_identity(agent_id: str, repo: Path) -> Identity:
    if not ID_RE.fullmatch(agent_id):
        raise AgentNewError(f"Invalid identity id: {agent_id!r}")
    system = system_paths.resolve_seat(agent_id, home=repo.parent, shipped_dir=repo)
    candidates = ([system] if system is not None else []) + sorted(roots()["portfolio"].glob(f"*/team/{agent_id}.md"))
    candidates = [p for p in candidates if p.is_file()]
    mirror = roots()["portfolio"] / "sample-shop/team/mercer.md"
    if agent_id == "mercer" and mirror in candidates:
        # Sample Shop owns this identity. A shared Markdown view is not a second identity.
        # Resolve the owner before parsing; current workspace content must never be replaced by a view.
        candidates = [mirror]
    if len(candidates) != 1:
        raise AgentNewError(f"Identity {agent_id}: expected one owner; found {len(candidates)}.")
    path = candidates[0]
    if not path.exists():
        raise AgentNewError(f"Identity not found: {agent_id}")
    data, body = split_identity(path.read_text(encoding="utf-8"))
    data = resolve_capabilities(data, roots()["system"] / "config/catalog.yaml")
    identity = Identity(data, body, path)
    validate_identity(identity, repo)
    return identity
def known_skill_names(shelf: Path, hermes: Path, profile: str | None) -> set[str]:
    """Skill names visible to Hermes: shelf dirs plus nested bundled skills (category/name/SKILL.md)."""
    names = directory_names(shelf)
    roots_ = [hermes / "skills", hermes / "hermes-agent" / "skills"]
    if profile:
        roots_.append(hermes / "profiles" / profile / "skills")
    for root in roots_:
        if not root.is_dir():
            continue
        for depth_glob in ("*/SKILL.md", "*/*/SKILL.md", "*/*/*/SKILL.md"):
            for hit in root.glob(depth_glob):
                names.add(hit.parent.name)
    return names

def gaps_for(identity: Identity, shelf: Path, hermes: Path | None = None) -> list[str]:
    known = known_skill_names(shelf, hermes or roots()["hermes"], identity.data.get("hermes_profile"))
    return sorted(skill for skill in identity.data["skills"] if skill not in known)
def team_path(client: str, repo: Path) -> Path | None:
    """A client's team file: the product's execution/teams first, else the client's own workspace config."""
    product = repo / "execution" / "teams" / f"{client}.yaml"
    if product.exists():
        return product
    portfolio = roots()["portfolio"] / client / "config" / "agents" / f"execution-teams-{client}.yaml"
    return portfolio if portfolio.exists() else None
def team_files(repo: Path) -> list[Path]:
    """Every team file: the product's, then each workspace's own."""
    product = sorted((repo / "execution" / "teams").glob("*.yaml"))
    portfolio = sorted(roots()["portfolio"].glob("*/config/agents/execution-teams-*.yaml"))
    return product + portfolio
def team_data(identity: Identity, repo: Path) -> dict[str, Any]:
    client = identity.data.get("client_default")
    if not client:
        return {}
    if not isinstance(client, str) or not ID_RE.fullmatch(client):
        raise AgentNewError(f"Invalid client_default: {client!r}")
    path = team_path(client, repo)
    if path is None:
        raise AgentNewError(f"Team file not found: teams/{client}.yaml or {client}/config/agents/execution-teams-{client}.yaml")
    value = read_yaml(path, {})
    if not isinstance(value, dict):
        raise AgentNewError(f"Team file is invalid: {path.name}")
    return value
def cape_body(identity: Identity, repo: Path) -> str:
    data = identity.data
    lines = [
        f"<!-- {MARKER} -->",
        f"You are {data['display_name']}.",
        f"Read {identity.path} fully before anything else.",
    ]
    if data.get("client_default"):
        contract = roots()["portfolio"] / data["client_default"] / "AGENTS.md"
        safe_new_path(contract)
        if not contract.is_file():
            raise AgentNewError(f"Render held: workspace contract not found: {contract}")
        lines.append(f"Read the client contract at {contract}.")
    lines.extend([
        f"Read the shared base soul at {roots()['system'] / 'agents' / 'soul.md'}.",
        f"Read catalog selections at {roots()['system'] / 'config' / 'catalog.yaml'}; regenerate this file after a catalog change.",
        "Selected skills: " + json.dumps(data['skills'], ensure_ascii=False) + ".",
        "Permitted MCP tools: " + json.dumps(data['tools'], ensure_ascii=False) + ".",
        "Use these catalog selections; an off skill or an unselected scoped skill is unavailable.",
        f"Approvals in {roots()['system'] / 'config' / 'models.yaml'} always go to the person.",
        f"Return per {repo / 'execution' / 'result.schema.json'}: deliverable, evidence, unresolved, and cost.",
    ])
    return "\n".join(lines) + "\n"
def claude_cape(identity: Identity, repo: Path) -> str:
    data = identity.data
    tools = ["Read", "Glob", "Grep", "Bash"]
    if data["tier"] == "code":
        tools += ["Write", "Edit"]
    if data.get("claude_tools") is not None:
        tools = data["claude_tools"]
    front: dict[str, Any] = {
        "type": "agents",
        "workspace": identity.path.parent.parent.name if identity.path.parent.name == "team" else "system",
        "timestamp": iso_now(),
        "name": data["id"], "description": data["summary"], "tools": tools,
        "skills": data["skills"], "mcpServers": data["tools"],
    }
    model = policy(repo)["tiers"][data["tier"]]["claude"]["model"]
    front["model"] = model
    lines = []
    for key, value in front.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend("  - " + json.dumps(item, ensure_ascii=False) for item in value)
        else:
            lines.append(f"{key}: " + json.dumps(value, ensure_ascii=False))
    return "---\n" + "\n".join(lines) + "\n---\n" + cape_body(identity, repo)
def codex_cape(identity: Identity, repo: Path) -> str:
    data = identity.data
    tier = policy(repo)["tiers"][data["tier"]]["codex"]
    values = {
        "name": data["id"], "description": data["summary"], "model": tier["model"],
        "model_reasoning_effort": tier.get("reasoning_effort", data.get("effort", "high")), "service_tier": tier["service_tier"],
        "developer_instructions": cape_body(identity, repo).rstrip(),
    }
    lines = [f"# {MARKER}"]
    lines += [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in values.items()]
    return "\n".join(lines) + "\n"
def _identity_instructions(identity: Identity) -> str:
    """Return the identity body with the shared base appended for the v2 shape."""
    instructions = identity.body
    base = roots()["repo"] / "soul.md"
    if any(h in identity.body.splitlines() for h in ("## Who you are", "## Identity")) and base.is_file():
        shared = base.read_text(encoding="utf-8")
        if shared.startswith("---\n") and "\n---\n" in shared[4:]:
            shared = shared[4:].split("\n---\n", 1)[1]  # page front matter is not soul text
        instructions = instructions.rstrip("\n") + "\n\n" + shared
    return instructions

def desired_soul(identity: Identity) -> str:
    data = identity.data
    header = f"# SOUL.md — {data['display_name']} (agent-new v1, from agents/{data['id']}.md v{data['version']})"
    return header + "\n" + _identity_instructions(identity)
def directory_names(path: Path) -> set[str]:
    if not path.is_dir():
        return set()
    return {entry.name for entry in path.iterdir() if entry.is_dir()}
def disabled_skills(identity: Identity, repo: Path, hermes: Path, shelf: Path) -> list[str]:
    data = identity.data
    profile = data.get("hermes_profile") or data["id"]
    catalog = read_yaml(roots()["system"] / "config/catalog.yaml", {})
    core_data = {"core": catalog.get("sets", {}).get("base", {}).get("skills", []), "exceptions": catalog.get("exceptions", {})}
    live = read_yaml(hermes / "profiles" / profile / "config.yaml", {})
    live_disabled = set(((live or {}).get("skills") or {}).get("disabled") or []) if isinstance(live, dict) else set()
    if live_disabled:
        # Existing profile: keep every live ruling; only the identity's own skills come back on.
        disabled = live_disabled - set(data["skills"])
    else:
        # New profile: start from the lead's live rulings, then everything known that the identity does not name.
        lead = team_data(identity, repo).get("lead")
        lead_live = read_yaml(hermes / "profiles" / lead / "config.yaml", {}) if lead else {}
        disabled = set((((lead_live or {}).get("skills") or {}).get("disabled") or []))
        disabled |= known_skill_names(shelf, hermes, profile)
        disabled -= set(data["skills"]) | set(core_data.get("core", []))
    exceptions = (core_data.get("exceptions") or {}).get(data["id"], {})
    disabled -= set(exceptions.get("keep", []))
    disabled |= set(exceptions.get("disable", []))
    return sorted(disabled)
def overlay(identity: Identity, repo: Path, hermes: Path, shelf: Path) -> dict[str, Any]:
    data = identity.data
    tier = policy(repo)["tiers"][data["tier"]].get("hermes")
    if not tier:
        raise AgentNewError(f"Tier {data['tier']} has no Hermes configuration.")
    profile = data["hermes_profile"]
    live = read_yaml(hermes / "profiles" / profile / "config.yaml", {})
    live_servers = set((live.get("mcp_servers") or {}).keys()) if isinstance(live, dict) else set()
    server_names = live_servers | set(data["tools"])
    team = team_data(identity, repo)
    workspace = team.get("workspace", str(repo))
    work_hermes = policy(repo)["tiers"]["work"]["hermes"]
    result = {
        "model": {"default": tier["model"], "provider": tier["provider"]},
        "agent": {"reasoning_effort": tier.get("reasoning_effort", data.get("effort", "high")), "service_tier": tier["service_tier"]},
        "terminal": {"cwd": workspace},
        "delegation": {
            "model": work_hermes["model"], "provider": work_hermes["provider"],
            "reasoning_effort": work_hermes.get("reasoning_effort", data.get("effort", "high")),
        },
        "skills": {"disabled": disabled_skills(identity, repo, hermes, shelf), "write_approval": True, "external_dirs": [str(roots()["shelf"])]},
        "mcp_servers": mcp_overlay(data, live if isinstance(live, dict) else {}, server_names, repo, hermes),
    }
    auxiliary = live.get("auxiliary", {}) if isinstance(live, dict) else {}
    if isinstance(auxiliary, dict):
        changed = {
            name: {"model": tier["model"]}
            for name, settings in auxiliary.items()
            if isinstance(settings, dict) and isinstance(settings.get("model"), str)
            and any(old in settings["model"].lower() for old in policy(repo).get("banned", []) + policy(repo).get("legacy_auxiliary_model_tags", []))
        }
        if changed:
            result["auxiliary"] = changed
    return result
def mcp_overlay(data: dict[str, Any], live: dict[str, Any], server_names: set[str], repo: Path, hermes: Path) -> dict[str, Any]:
    """Enabled flags for known servers; a server the identity names but the profile lacks is copied from the lead's definition (no env, no headers)."""
    live_servers = live.get("mcp_servers") or {}
    lead = team_data(Identity(data, "") if False else _IdentityShim(data), repo).get("lead")
    lead_live = read_yaml(hermes / "profiles" / lead / "config.yaml", {}) if lead else {}
    lead_servers = ((lead_live or {}).get("mcp_servers") or {}) if isinstance(lead_live, dict) else {}
    out: dict[str, Any] = {}
    for name in sorted(server_names):
        if name in live_servers:
            out[name] = {"enabled": name in data["tools"]}
        elif name in lead_servers and name in data["tools"]:
            definition = {k: v for k, v in lead_servers[name].items() if k not in {"enabled", "env", "headers"}}
            definition["enabled"] = True
            out[name] = definition
        elif name in data["tools"]:
            out[name] = {"enabled": True}  # no definition in profile or lead; tool_probe will report it
    return out

class _IdentityShim:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

def assignment_brief(identity: Identity, repo: Path) -> str:
    data = identity.data
    assignment = {
        "identity": data["id"], "identity_version": data["version"],
        "client": data.get("client_default") or "", "task": "<assignment>",
        "inputs": [], "skills": data["skills"], "output": "<finished result>",
        "limits": {"timeout_seconds": policy(repo)["limits"]["child_timeout_seconds"], "cost_usd": 0, "tools": data["tools"]},
        "return_to": data["return_default"], "origin_topic": "<origin topic>",
    }
    instructions = _identity_instructions(identity)
    if instructions == identity.body:
        # Preserve the established v1 and missing-base output exactly.
        prefix = identity.body.rstrip() + "\n\n"
    else:
        # Preserve the appended base literally, including its final newline.
        prefix = instructions + ("\n" if instructions.endswith("\n") else "\n\n")
    return prefix + "## Assignment\n\n```yaml\n" + yaml_text(assignment) + "```\n"

def check_managed(path: Path) -> None:
    if path.exists() and MARKER not in path.read_text(encoding="utf-8", errors="replace"):
        raise AgentNewError(f"Refusing to overwrite unmarked cape: {path}")

def _ruled_codex_alias(identity, runtime):
    ruled = {"architect", "chief-of-staff", "comms-lead", "creative-reviewer", "designer", "video-producer"}
    if identity.path.parent.name == "team" or identity.data["id"] not in ruled or "codex" not in identity.data["runtimes"]:
        return None
    alias = roots()["system"] / "agents/generated/codex" / runtime.name
    relative = os.path.relpath(runtime, alias.parent)
    safe_new_path(alias)
    if os.path.lexists(alias) and (not alias.is_symlink() or os.readlink(alias) != relative):
        raise AgentNewError(f"Refusing to replace a ruled runtime path: {alias}")
    return alias, relative

def _keep_ruled_codex_alias(identity, runtime, journal=None):
    value = _ruled_codex_alias(identity, runtime)
    if value:
        alias, relative = value
        if not alias.is_symlink():
            if journal is not None:
                journal.before(alias)
            alias.parent.mkdir(parents=True, exist_ok=True)
            alias.symlink_to(relative)
            if journal is not None:
                journal.wrote(link=relative)

def render_identity(identity: Identity, *, dry_run: bool = False, journal: Journal | None = None) -> dict[str, Any]:
    r = roots()
    repo, vault, hermes, shelf = r["repo"], r["vault"], r["hermes"], r["shelf"]
    data = identity.data
    workspace = identity.path.parent.parent if identity.path.parent.name == "team" else None
    claude_dir = workspace / "team/claude" if workspace else r["system"] / "runs/generated/agents/claude"
    codex_dir = workspace / "team/codex" if workspace else r["system"] / "runs/generated/agents/codex"
    _ruled_codex_alias(identity, codex_dir / (data["id"] + ".toml"))
    targets: list[tuple[Path, str]] = []
    if "claude" in data["runtimes"]:
        targets.append(((claude_dir / f"{data['id']}.md" if workspace else claude_dir / f"{data['id']}.md"), claude_cape(identity, repo)))
    if "codex" in data["runtimes"]:
        targets.append((codex_dir / f"{data['id']}.toml", codex_cape(identity, repo)))
    for path, _ in targets:
        safe_new_path(path)
        if path.resolve() == identity.path.resolve():
            raise AgentNewError("Runtime cape would overwrite its identity; render refused.")
        check_managed(path)
    base = (r["system"] / "runs/generated/agents/workspaces" / workspace.name if workspace else r["system"] / "runs/generated/agents") / data["id"]
    if data["hermes_mode"] != "none":
        targets.append((base / "SOUL.md", desired_soul(identity)))
    if data["hermes_mode"] == "child":
        targets.append((base / "brief.md", assignment_brief(identity, repo)))
    elif data["hermes_mode"] in {"profile", "kanban"}:
        targets.append((base / "config.overlay.yaml", yaml_text(overlay(identity, repo, hermes, shelf))))
    gaps = gaps_for(identity, shelf, hermes)
    report_path = base / "render.json"
    report = {
        "written": [str(path) for path, _ in targets] + [str(report_path)],
        "hermes": "available" if hermes_available() else "Claude and Codex on day one.",
        "gaps": gaps, "version": data["version"], "timestamp": iso_now(), "dry_run": dry_run,
    }
    # Check every write before the first one, so a refused path leaves nothing half made.
    for path in [p for p, _ in targets] + [report_path]:
        check_write(path)
    if not dry_run:
        for path, text in targets:
            write_text(path, text, journal)
        write_text(report_path, json.dumps(report, indent=2) + "\n", journal)
        _keep_ruled_codex_alias(identity, codex_dir / (data["id"] + ".toml"), journal)
    return report

def project_live(live: Any, proposed: Any) -> Any:
    if not isinstance(proposed, dict):
        return live
    source = live if isinstance(live, dict) else {}
    return {key: project_live(source.get(key), value) for key, value in proposed.items()}

def leaf_changes(before: Any, after: Any, prefix: str = "") -> list[str]:
    if isinstance(after, dict):
        source = before if isinstance(before, dict) else {}
        result: list[str] = []
        for key, value in after.items():
            result += leaf_changes(source.get(key), value, f"{prefix}.{key}" if prefix else key)
        return result
    return [prefix] if before != after else []

def diff_data(identity: Identity) -> tuple[int, dict[str, Any]]:
    r = roots()
    data = identity.data
    if data["hermes_mode"] not in {"profile", "kanban"}:
        raise AgentNewError("diff only supports profile and kanban identities.")
    profile_dir = r["hermes"] / "profiles" / data["hermes_profile"]
    config_path = profile_dir / "config.yaml"
    proposed = overlay(identity, r["repo"], r["hermes"], r["shelf"])
    if not config_path.is_file():
        return 2, {"profile_missing": True, "profile": data["hermes_profile"], "proposed": proposed}
    live = read_yaml(config_path, {})
    selected = project_live(live, proposed)
    diff = "".join(difflib.unified_diff(
        yaml_text(selected).splitlines(True), yaml_text(proposed).splitlines(True),
        fromfile="live", tofile="proposed",
    ))
    old_disabled = set(((live.get("skills") or {}).get("disabled") or []))
    new_disabled = set(proposed["skills"]["disabled"])
    live_mcp = live.get("mcp_servers") or {}
    toggled = []
    for name, config in proposed["mcp_servers"].items():
        old = (live_mcp.get(name) or {}).get("enabled")
        if old != config["enabled"]:
            toggled.append(f"{name}: {old} -> {config['enabled']}")
    live_soul = profile_dir / "SOUL.md"
    generated_soul = r["repo"] / "generated" / "hermes" / data["id"] / "SOUL.md"
    soul_same = (live_soul.is_file() and generated_soul.is_file()
                 and live_soul.read_bytes() == generated_soul.read_bytes())
    result = {
        "profile_missing": False, "diff": diff, "keys_changed": leaf_changes(selected, proposed),
        "skills_newly_disabled": sorted(new_disabled - old_disabled),
        "skills_newly_enabled": sorted(old_disabled - new_disabled),
        "mcp_servers_toggled": toggled, "soul": "same" if soul_same else "different",
    }
    return (3 if result["keys_changed"] or not soul_same else 0), result

def deep_merge(base: dict[str, Any], change: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in change.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result

def default_runner(cmd: list[str], *, cwd: Path | None = None, timeout: int | None = None) -> Any:
    return subprocess.run(cmd, cwd=cwd, timeout=timeout, text=True, capture_output=True, check=False, stdin=subprocess.DEVNULL)

def run_command(runner: Callable[..., Any], cmd: list[str], cwd: Path | None, timeout: int | None) -> tuple[int, str]:
    try:
        result = runner(cmd, cwd=cwd, timeout=timeout)
        code = int(getattr(result, "returncode", 0))
        output = str(getattr(result, "stdout", "") or "") + str(getattr(result, "stderr", "") or "")
        return code, output
    except subprocess.TimeoutExpired as exc:
        return 124, str(exc)
    except Exception as exc:
        return 1, str(exc)

def print_diff(result: dict[str, Any]) -> None:
    if result.get("profile_missing"):
        print(f"Profile {result['profile']} is missing.")
        return
    print(result["diff"], end="") if result["diff"] else print("No YAML drift.")
    print("Keys changed: " + (", ".join(result["keys_changed"]) or "none"))
    disabled = result["skills_newly_disabled"]
    print(f"Skills newly disabled: {len(disabled)}" + (" — " + ", ".join(disabled) if disabled else ""))
    print("Skills newly enabled: " + (", ".join(result["skills_newly_enabled"]) or "none"))
    print("MCP servers toggled: " + (", ".join(result["mcp_servers_toggled"]) or "none"))
    print(f"SOUL.md: {result['soul']}")

def create_command(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    repo = roots()["repo"]
    if not ID_RE.fullmatch(args.id):
        raise AgentNewError(f"Invalid identity id: {args.id!r}")
    r = roots()
    if args.client == "system":
        path = repo / f"{args.id}.md"
    else:
        # The installer's workspace rule: lowercase letters, digits, and dashes.
        if not re.fullmatch(r"[a-z0-9-]+", args.client):
            raise AgentNewError("Client must name one workspace, or system.")
        workspace = r["portfolio"] / args.client
        if not workspace.is_dir():
            raise AgentNewError(f"Workspace not found: {workspace}")
        path = workspace / "team" / f"{args.id}.md"
    safe_new_path(path)
    system = system_paths.resolve_seat(args.id, home=repo.parent, shipped_dir=repo)
    matches = ([system] if system is not None else []) + list(r["portfolio"].glob(f"*/team/{args.id}.md"))
    if matches:
        raise AgentNewError(f"Identity already exists: {args.id}; use its existing owner.")
    if path.exists():
        raise AgentNewError(f"Identity already exists: {args.id}")
    mode = args.hermes_mode
    data = {
        "type": PAGE_TYPE, "workspace": args.client,
        "id": args.id, "display_name": args.id.replace("-", " ").title(),
        "role": args.role, "summary": args.summary, "tier": args.tier,
        "shared": args.shared, "client_default": None if args.client == "system" else args.client,
        "runtimes": sorted(set(csv_list(args.runtimes)) | {"claude", "codex"}), "hermes_mode": mode,
        "hermes_profile": args.id if mode in {"profile", "kanban"} else None,
        "sets": csv_list(args.sets),
        "return_default": args.return_to or "session:caller", "owns": [], "version": 1,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    body = f"""# {data['display_name']}

## Identity
{args.summary}

## What You Own
- Own this work: {args.role}.

## Judgment
- Verify source facts. Do not guess.

### Style
- Report in plain English with the result first.

### Limits
- Follow config/gates.md; approval goes to the person.

### Return
- Return the deliverable, evidence, unresolved items, and cost.

{WRITE_STATE_SECTION.replace("## ", "### ")}
### Boot reads
- None yet. Seats list named reads here, in order: see docs/identity-format.md.
"""
    if args.client != "system":
        body = body.replace("--db ${FOXRUN_HOME:-$HOME/.foxrun}/data.db --receipt-root ${FOXRUN_HOME:-$HOME/.foxrun}", f"--workspace {args.client} --receipt-root {r['portfolio'] / args.client}")
    data = resolve_capabilities(data, roots()["system"] / "config/catalog.yaml")
    requested_skills = csv_list(args.skills)
    requested_tools = csv_list(args.tools)
    if args.sets == "base" and (requested_skills or requested_tools):
        catalog = read_yaml(roots()["system"] / "config/catalog.yaml", {})
        matches = [key for key, definition in catalog.get("sets", {}).items()
                   if definition.get("skills", []) == requested_skills and definition.get("tools", []) == requested_tools]
        if not matches:
            raise AgentNewError("Requested capabilities need a reviewed catalog set.")
        data["sets"] = ["base", matches[0]]
        data = resolve_capabilities(data, roots()["system"] / "config/catalog.yaml")
    if args.skills and not set(csv_list(args.skills)).issubset(data["skills"]):
        raise AgentNewError("Skills come from catalog sets; select --sets instead of a handwritten list.")
    if args.tools and csv_list(args.tools) != data["tools"]:
        raise AgentNewError("Tools come from catalog sets; select --sets instead of a handwritten list.")
    identity = Identity(data, body, path)
    validate_identity(identity, repo)
    # Validate and check every output before writing the identity; dry-run writes nothing.
    check_write(path)
    report = render_identity(identity, dry_run=True)
    page = "---\n" + yaml_text({k:v for k,v in data.items() if k not in ("skills","tools")}) + "---\n" + body
    if args.dry_run:
        return 0, {"result": f"Dry run: would create identity {args.id}.", "path": str(path),
                   "runtime_files": report["written"], "page": page}
    # All or nothing: if any write fails, remove exactly what this run wrote.
    journal = Journal()
    try:
        write_text(path, page, journal)
        report = render_identity(identity, journal=journal)
    except BaseException as exc:
        left = journal.undo()
        if left and isinstance(exc, AgentNewError):
            raise AgentNewError(f"{exc}; changed since this run wrote it, left in place: {', '.join(left)}") from exc
        raise
    return 0, {"result": f"Created identity {args.id}.", "path": str(path), "runtime_files": report["written"]}

def apply_command(args: argparse.Namespace, runner: Callable[..., Any]) -> tuple[int, dict[str, Any]]:
    if args.yes != "person":
        raise AgentNewError("Apply refused. Use the literal confirmation: --yes person")
    r = roots()
    if runner is default_runner and not hermes_available():
        raise AgentNewError("Claude and Codex on day one.")
    identity = load_identity(args.id, r["repo"])
    if identity.data["hermes_mode"] not in {"profile", "kanban"}:
        raise AgentNewError("apply only supports profile and kanban identities.")
    _, preview = diff_data(identity)
    if not args.json:
        print_diff(preview)
    profile = identity.data["hermes_profile"]
    profile_dir = r["hermes"] / "profiles" / profile
    if not profile_dir.is_dir():
        cmd = ["hermes", "profile", "create", profile, "--no-alias", "--description", identity.data["summary"]]
        code, output = run_command(runner, cmd, r["repo"], None)
        if code:
            raise AgentNewError(f"Hermes profile create failed ({code}): {output[-300:]}")
        profile_dir.mkdir(parents=True, exist_ok=True)
    timestamp = stamp()
    overlay_data = overlay(identity, r["repo"], r["hermes"], r["shelf"])
    backups: list[tuple[Path, Path]] = []
    config_path = profile_dir / "config.yaml"
    live = read_yaml(config_path, {})
    if config_path.exists():
        backup = profile_dir / f"config.yaml.{timestamp}.bak"
        shutil.copy2(config_path, backup)
        backups.append((backup, config_path))
    write_text(config_path, yaml_text(deep_merge(live, overlay_data)))
    soul_path = profile_dir / "SOUL.md"
    if soul_path.exists():
        backup = profile_dir / f"SOUL.md.{timestamp}.bak"
        shutil.copy2(soul_path, backup)
        backups.append((backup, soul_path))
    write_text(soul_path, desired_soul(identity))
    cmd = ["hermes", "profile", "describe", profile, "--text", identity.data["summary"]]
    code, output = run_command(runner, cmd, r["repo"], None)
    if code:
        raise AgentNewError(f"Hermes profile describe failed ({code}): {output[-300:]}")
    rollback = [f"cp {source} {target}" for source, target in backups]
    return 0, {
        "result": f"Applied profile {profile}.", "diff": preview, "rollback": rollback,
        "note": "Gateway reload not performed — theme 3 owns restarts.",
    }

def lead_for(identity: Identity, repo: Path) -> str:
    """The lead profile that hosts this identity as a child: its client's team, else the first team listing it as shared, else the only team."""
    team = team_data(identity, repo)
    if team.get("lead"):
        return str(team["lead"])
    teams = team_files(repo)
    for path in teams:
        data = read_yaml(path, {}) or {}
        members = data.get("members") or {}
        listed = set(members.get("account") or []) | set(members.get("shared") or [])
        if identity.data["id"] in listed and data.get("lead"):
            return str(data["lead"])
    if len(teams) == 1:
        data = read_yaml(teams[0], {}) or {}
        if data.get("lead"):
            return str(data["lead"])
    raise AgentNewError(f"No team lead found for child identity {identity.data['id']}; add it to a teams/*.yaml members list.")

def probe_one(runtime: str, identity: Identity, timeout: int, runner: Callable[..., Any]) -> dict[str, Any]:
    r = roots()
    data = identity.data
    token = f"IDENTITY {data['id']} READY"
    prompt = f"Reply with exactly: {token}"
    started = time.monotonic()
    tmp_path: Path | None = None
    if runtime == "claude":
        cmd = ["claude", "-p", prompt, "--agent", data["id"], "--output-format", "json", "--max-turns", "4", "--allowedTools", "Read"]
        cwd = r["vault"]
    elif runtime == "codex":
        handle = tempfile.NamedTemporaryFile(prefix="agent-new-", suffix=".txt", delete=False)
        handle.close()
        tmp_path = Path(handle.name)
        model = policy(r["repo"])["tiers"][data["tier"]]["codex"]["model"]
        full_prompt = cape_body(identity, r["repo"]).rstrip() + "\n\n" + prompt
        cmd = ["codex", "exec", "-s", "read-only", "-C", str(r["vault"]), "--skip-git-repo-check", "-m", model, "--json", "-o", str(tmp_path), full_prompt]
        cwd = r["vault"]
    else:
        if runner is default_runner and not hermes_available():
            return {"runtime": runtime, "ok": True, "skipped": True, "seconds": 0.0, "exit_code": 0, "last_300": "Claude and Codex on day one."}
        if data["hermes_mode"] == "none":
            return {"runtime": runtime, "ok": True, "skipped": True, "seconds": 0.0, "exit_code": 0, "last_300": "Hermes skipped for mode none."}
        if data["hermes_mode"] == "child":
            lead = lead_for(identity, r["repo"])
            text = assignment_brief(identity, r["repo"]) + "\n" + prompt
            cmd = ["hermes", "-p", lead, "-z", text]
        else:
            cmd = ["hermes", "-p", data["hermes_profile"], "-z", prompt]
        cwd = r["repo"]
    code, output = run_command(runner, cmd, cwd, timeout)
    if tmp_path is not None:
        try:
            saved = tmp_path.read_text(encoding="utf-8")
            if saved:
                output = saved
        finally:
            tmp_path.unlink(missing_ok=True)
    seconds = round(time.monotonic() - started, 3)
    return {"runtime": runtime, "ok": code == 0 and token in output, "seconds": seconds, "exit_code": code, "last_300": output[-300:]}

def probe_command(args: argparse.Namespace, runner: Callable[..., Any]) -> tuple[int, dict[str, Any]]:
    r = roots()
    identity = load_identity(args.id, r["repo"])
    requested = csv_list(args.runtimes) if args.runtimes else list(identity.data["runtimes"])
    if not requested or not set(requested).issubset(RUNTIMES):
        raise AgentNewError("Probe runtimes must contain Claude and Codex on day one.")
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(requested)) as pool:
        futures = {runtime: pool.submit(probe_one, runtime, identity, args.timeout, runner) for runtime in requested}
        results = [futures[runtime].result() for runtime in requested]
    report = {"id": args.id, "timestamp": iso_now(), "results": results}
    report_path = r["repo"] / "generated" / "probes" / f"{args.id}-{stamp()}.json"
    write_text(report_path, json.dumps(report, indent=2) + "\n")
    report["path"] = str(report_path)
    return (0 if all(item["ok"] for item in results) else 4), report

def add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true")

def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="agent-new")
    sub = root.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("id")
    create.add_argument("--role", required=True)
    create.add_argument("--summary", required=True)
    create.add_argument("--tier", choices=["judgment", "work", "cheap", "code"], required=True)
    create.add_argument("--sets", default="base")
    create.add_argument("--skills", default="")
    create.add_argument("--tools", default="")
    create.add_argument("--client", required=True)
    create.add_argument("--runtimes", default="claude,codex")
    create.add_argument("--hermes-mode", choices=["none"], default="none", help="compatibility field; only none is supported")
    create.add_argument("--shared", action="store_true")
    create.add_argument("--dry-run", action="store_true")
    create.add_argument("--return", dest="return_to")
    add_json(create)
    for name in ("render", "diff"):
        item = sub.add_parser(name)
        item.add_argument("id")
        if name == "render":
            item.add_argument("--dry-run", action="store_true")
        add_json(item)
    apply = sub.add_parser("apply")
    apply.add_argument("id")
    apply.add_argument("--yes")
    add_json(apply)
    probe = sub.add_parser("probe")
    probe.add_argument("id")
    probe.add_argument("--runtimes")
    probe.add_argument("--timeout", type=int, default=90)
    add_json(probe)
    listing = sub.add_parser("list")
    add_json(listing)
    return root

def list_command() -> tuple[int, dict[str, Any]]:
    r = roots()
    rows = []
    system_names = {p.stem for folder in (r["repo"], r["repo"].parent / "profile/agents") for p in folder.glob("*.md")}
    system_files = [system_paths.resolve_seat(name, home=r["repo"].parent, shipped_dir=r["repo"]) for name in sorted(system_names)]
    for path in sorted([p for p in system_files if p is not None] + list(r["portfolio"].glob("*/team/*.md"))):
        try:
            if not is_identity_page(path):
                continue
            identity = load_identity(path.stem, r["repo"])
            data = identity.data
            rows.append({
                "id": data["id"], "tier": data["tier"], "hermes_mode": data["hermes_mode"],
                "runtimes": ",".join(data["runtimes"]), "skills": len(data["skills"]),
                "gaps": len(gaps_for(identity, r["shelf"])),
            })
        except AgentNewError:
            continue
    return 0, {"result": f"Found {len(rows)} identities.", "identities": rows}

def emit(args: argparse.Namespace, code: int, payload: dict[str, Any]) -> None:
    if args.json:
        print(json.dumps(payload, indent=2))
        return
    command = args.command
    if command in {"create", "render"}:
        print(payload["result"])
        if payload.get("gaps"):
            print("Skill gaps: " + ", ".join(payload["gaps"]))
    elif command == "diff":
        print_diff(payload)
    elif command == "apply":
        print(payload["result"])
        for line in payload["rollback"]:
            print("Rollback: " + line)
        print(payload["note"])
    elif command == "probe":
        print("runtime  ok  seconds  exit  last 300 chars")
        for item in payload["results"]:
            tail = item["last_300"].replace("\n", " ")
            print(f"{item['runtime']:<7}  {str(item['ok']).lower():<5}  {item['seconds']:<7}  {item['exit_code']:<4}  {tail}")
        print(f"Probe report written to {payload['path']}.")
    elif command == "list":
        print("id  tier  hermes_mode  runtimes  skills  gaps")
        for row in payload["identities"]:
            print(f"{row['id']}  {row['tier']}  {row['hermes_mode']}  {row['runtimes']}  {row['skills']}  {row['gaps']}")
        print(payload["result"])

def main(argv: list[str] | None = None, runner: Callable[..., Any] = default_runner) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    excluded = False
    for index, value in enumerate(argv):
        if value.startswith('--runtimes='):
            excluded |= 'hermes' in csv_list(value.split('=', 1)[1].casefold())
        elif value == '--runtimes' and index + 1 < len(argv):
            excluded |= 'hermes' in csv_list(argv[index + 1].casefold())
        elif value.startswith('--hermes-mode='):
            excluded |= value.split('=', 1)[1] != 'none'
        elif value == '--hermes-mode' and index + 1 < len(argv):
            excluded |= argv[index + 1] != 'none'
    if excluded:
        print('Claude and Codex on day one.')
        return 2
    args = parser().parse_args(argv)
    try:
        requested = csv_list(getattr(args, 'runtimes', '') or '')
        if 'hermes' in requested or getattr(args, 'hermes_mode', 'none') != 'none' or args.command == 'apply':
            print('Claude and Codex on day one.')
            return 2
        if args.command in {'render', 'diff', 'probe'}:
            identity = load_identity(args.id, roots()['repo'])
            if 'hermes' in identity.data['runtimes'] or identity.data['hermes_mode'] != 'none':
                print('Claude and Codex on day one.')
                return 2
        if args.command == "diff":
            raise AgentNewError("Diff held: Hermes profile and kanban routes are excluded on day one.")
        if args.command == "probe":
            raise AgentNewError("Probe held: agents-point has no approved agent-folder plan or live loader proof.")
        if args.command == "create":
            code, payload = create_command(args)
        elif args.command == "render":
            identity = load_identity(args.id, roots()["repo"])
            payload = render_identity(identity, dry_run=args.dry_run)
            payload["result"] = f"{'Planned' if args.dry_run else 'Rendered'} identity {args.id}."
            code = 0
        elif args.command == "diff":
            identity = load_identity(args.id, roots()["repo"])
            code, payload = diff_data(identity)
        elif args.command == "apply":
            code, payload = apply_command(args, runner)
        elif args.command == "probe":
            code, payload = probe_command(args, runner)
        else:
            code, payload = list_command()
        emit(args, code, payload)
        return code
    except AgentNewError as exc:
        payload = {"error": str(exc)}
        print(json.dumps(payload) if getattr(args, "json", False) else str(exc), file=sys.stdout if getattr(args, "json", False) else sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
