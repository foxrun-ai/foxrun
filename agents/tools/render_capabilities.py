#!/usr/bin/env python3
"""Render a deterministic CAPABILITIES.md preview from explicit safe sources."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import html
import json
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import types
from typing import Any

import sys as _shared_sys
from pathlib import Path as _SharedPath
_shared_sys.path.insert(0, str(_SharedPath(__file__).resolve().parents[2]))
from base import simple_yaml as yaml, paths as system_paths
from base.simple_yaml import MappingNode, Node, ScalarNode, SequenceNode

try:
    from .paths import roots, tool_path
except ImportError:  # pragma: no cover
    from paths import roots, tool_path


MARKER = "<!-- generated-by: agent-team capabilities v1 -->"
MAX_SOURCE_BYTES = 1_000_000
SECTIONS = ("Workflows", "Agents", "Reports", "Skills", "Schedules", "MCPs", "CLIs", "Hooks", "Plugins")
IDENTITY_REQUIRED = {
    "id", "display_name", "role", "summary", "tier", "shared", "runtimes",
    "hermes_mode", "hermes_profile", "skills", "tools", "return_default",
    "version",
}
# One of these dates the page: timestamp (SCHEMA.md), or created on an identity not yet migrated.
IDENTITY_DATE_KEYS = ("timestamp", "created")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,60}$")
SAFE_SKILL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")
WORKFLOW_IDENTITY = re.compile(r"^([a-z][a-z0-9-]*)(?:\s+\([^\n|]*\))?$")


class CapabilityError(ValueError):
    pass


@dataclass
class Agent:
    data: dict[str, Any]
    source: str
    lines: dict[tuple[Any, ...], int]


@dataclass
class Team:
    data: dict[str, Any]
    source: str
    lines: dict[tuple[Any, ...], int]


class SourceReader:
    def __init__(self, repo: Path, vault: Path, modules: Path, *, installed_layout: bool = False) -> None:
        self.installed_layout = installed_layout
        for label, root in (("repo", repo), ("vault", vault), ("modules", modules)):
            absolute = Path(os.path.abspath(root.expanduser()))
            if absolute.is_symlink():
                raise CapabilityError(f"{label} root must not be a symlink: {absolute}")
            if not absolute.is_dir() and not (label == "modules" and installed_layout):
                raise CapabilityError(f"{label} root must exist: {absolute}")
        self.roots = {"repo": repo.resolve(), "vault": vault.resolve(), "modules": modules.resolve(), "config": (Path(os.environ.get("FOXRUN_HOME", str(repo.parent if installed_layout else Path.home()/".foxrun"))) / "config").resolve()}
        self.roots["personal"] = self.roots["repo"].parent / "profile/agents"
        self.sources: dict[str, dict[str, Any]] = {}
        self.existence_sources: dict[str, dict[str, Any]] = {}

    def safe_path(self, root_name: str, path: Path, *, require_file: bool = True) -> tuple[Path, str]:
        root = self.roots[root_name]
        absolute = Path(os.path.abspath(path.expanduser()))
        try:
            absolute.relative_to(root)
        except ValueError as error:
            raise CapabilityError(f"source path escapes {root_name} root: {path}") from error
        try:
            resolved = absolute.resolve(strict=True)
        except FileNotFoundError as error:
            raise CapabilityError(f"source is missing: {path}") from error
        try:
            relative = resolved.relative_to(root)
        except ValueError as error:
            raise CapabilityError(f"source symlink escapes {root_name} root: {path}") from error
        if require_file and not resolved.is_file():
            raise CapabilityError(f"source is not a regular file: {path}")
        label = root_name + ":" + relative.as_posix()
        return resolved, label

    def text(self, root_name: str, path: Path) -> tuple[str, str]:
        resolved, label = self.safe_path(root_name, path)
        size = resolved.stat().st_size
        if size > MAX_SOURCE_BYTES:
            raise CapabilityError(f"source exceeds {MAX_SOURCE_BYTES} bytes: {label}")
        body = resolved.read_text(encoding="utf-8")
        self.sources[label] = {
            "path": label,
            "bytes": size,
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
        }
        return body, label

    def existence(self, root_name: str, path: Path) -> str:
        resolved, label = self.safe_path(root_name, path)
        mode = resolved.stat().st_mode
        self.existence_sources[label] = {
            "path": label,
            "bytes": resolved.stat().st_size,
            "executable": bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)),
            "evidence": "path metadata only; file content not read",
        }
        return label

    def external_existence(self, label: str, evidence: dict[str, Any]) -> None:
        self.existence_sources[label] = {"path": label, **evidence}

    def snapshot(self) -> dict[str, Any]:
        parsed = [self.sources[key] for key in sorted(self.sources)]
        existence = [self.existence_sources[key] for key in sorted(self.existence_sources)]
        encoded = json.dumps({"parsed": parsed, "existence": existence}, sort_keys=True, separators=(",", ":")).encode()
        return {
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "parsed_sources": parsed,
            "existence_sources": existence,
        }


def yaml_line_map(text: str, offset: int = 0) -> dict[tuple[Any, ...], int]:
    try:
        node = yaml.compose(text)
    except yaml.YAMLError as error:
        raise CapabilityError("unsupported YAML: " + str(error)) from error
    lines: dict[tuple[Any, ...], int] = {}

    def walk(current: Node | None, path: tuple[Any, ...]) -> None:
        if current is None:
            return
        if isinstance(current, MappingNode):
            seen: set[str] = set()
            for key_node, value_node in current.value:
                if not isinstance(key_node, ScalarNode):
                    raise CapabilityError("unsupported YAML mapping key")
                key = key_node.value
                if key in seen:
                    line = key_node.start_mark.line + 1 + offset
                    raise CapabilityError(f"duplicate YAML key {key!r} at line {line}")
                seen.add(key)
                child = path + (key,)
                lines[child] = key_node.start_mark.line + 1 + offset
                walk(value_node, child)
        elif isinstance(current, SequenceNode):
            for index, value_node in enumerate(current.value):
                child = path + (index,)
                lines[child] = value_node.start_mark.line + 1 + offset
                walk(value_node, child)

    walk(node, ())
    return lines


def yaml_value(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise CapabilityError("unsupported YAML: " + str(error)) from error


def identity_frontmatter(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise CapabilityError("identity frontmatter must start with ---")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise CapabilityError("identity frontmatter has no closing ---") from error
    return "\n".join(lines[1:end]) + "\n", 1


def load_agent_new(repo: Path, source_path: Path) -> Any:
    """Load the existing validator without importing its runtime paths module."""
    module_name = "_capabilities_agent_new_" + hashlib.sha256(str(source_path).encode()).hexdigest()[:12]
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise CapabilityError("agent_new.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    stub = types.ModuleType("paths")
    stub.roots = lambda: {"system": Path(os.environ.get("FOXRUN_HOME", str(Path.home()/".foxrun"))).expanduser()}
    previous_paths = sys.modules.get("paths")
    stub.hermes_available = lambda: False
    sys.modules["paths"] = stub
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise CapabilityError("agent_new.py loader import failed: " + str(error)) from error
    finally:
        if previous_paths is None:
            sys.modules.pop("paths", None)
        else:
            sys.modules["paths"] = previous_paths
        sys.modules.pop(module_name, None)
    if not callable(getattr(module, "load_identity", None)):
        raise CapabilityError("agent_new.py has no callable load_identity")
    return module


def load_agents(reader: SourceReader, loader: Any) -> tuple[dict[str, Agent], list[dict[str, str]]]:
    agents: dict[str, Agent] = {}
    gaps: list[dict[str, str]] = []
    directory = reader.roots["repo"]
    if not directory.is_dir():
        raise CapabilityError("repo:agents directory is missing")
    names = {p.stem for folder in (directory, reader.roots["personal"]) for p in folder.glob("*.md")}
    for name in sorted(names):
        if reader.installed_layout and name in {"README", "soul"}:
            continue
        path = system_paths.resolve_seat(name, home=directory.parent, shipped_dir=directory)
        if path is None:
            if (directory / (name + ".md")).is_symlink():
                raise CapabilityError("seat source escapes safe file rules: " + name)
            continue
        try:
            text, source = reader.text("personal" if path.parent == reader.roots["personal"] else "repo", path)
            front, offset = identity_frontmatter(text)
            data = yaml_value(front)
            lines = yaml_line_map(front, offset)
            if not isinstance(data, dict):
                raise CapabilityError("identity frontmatter is not a mapping")
            data = loader.resolve_capabilities(data, reader.roots["config"] / "catalog.yaml")
            agent_id = data.get("id")
            if isinstance(agent_id, str) and agent_id in agents:
                raise CapabilityError(f"duplicate agent id: {agent_id}")
            missing = sorted(IDENTITY_REQUIRED - set(data))
            if not any(key in data for key in IDENTITY_DATE_KEYS):
                missing.append("timestamp")
            if missing:
                raise CapabilityError("missing identity fields: " + ", ".join(missing))
            if not isinstance(agent_id, str) or not ID_RE.fullmatch(agent_id):
                raise CapabilityError(f"invalid agent id: {agent_id!r}")
            if path.stem != agent_id:
                raise CapabilityError(f"identity id does not match filename: {agent_id}")
            for field in ("display_name", "role", "summary"):
                if not isinstance(data[field], str) or not data[field].strip():
                    raise CapabilityError(f"invalid identity field: {field}")
            for field in ("skills", "tools", "runtimes"):
                if not isinstance(data[field], list) or not all(isinstance(value, str) for value in data[field]):
                    raise CapabilityError(f"unsupported identity list: {field}")
            try:
                loaded = loader.load_identity(agent_id, reader.roots["repo"])
            except Exception as error:
                raise CapabilityError("existing identity loader rejected source: " + str(error)) from error
            if loaded.data != data:
                raise CapabilityError("existing identity loader returned different frontmatter")
            agents[agent_id] = Agent(data, source, lines)
        except CapabilityError as error:
            if "duplicate agent id" in str(error) or "duplicate YAML key" in str(error) or "unsupported YAML" in str(error) or "escapes" in str(error):
                raise
            gaps.append({"item": path.name, "reason": str(error), "source": "repo:" + path.name + ":1"})
    return agents, gaps


def load_yaml_file(reader: SourceReader, root_name: str, path: Path) -> tuple[Any, dict[tuple[Any, ...], int], str]:
    text, source = reader.text(root_name, path)
    return yaml_value(text), yaml_line_map(text), source


def load_teams(reader: SourceReader) -> tuple[list[Team], list[dict[str, str]]]:
    teams: list[Team] = []
    gaps: list[dict[str, str]] = []
    clients: set[str] = set()
    workspaces: set[str] = set()
    directory = reader.roots["repo"] / "execution" / "teams"
    if not directory.is_dir():
        return [], [{"item": "teams", "reason": "team registry is missing", "source": "gap:no team registry"}]
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.suffix not in {".yaml", ".yml"}:
            continue
        try:
            data, lines, source = load_yaml_file(reader, "repo", path)
            if not isinstance(data, dict):
                raise CapabilityError("team file is not a mapping")
            client, workspace = data.get("client"), data.get("workspace")
            members = data.get("members")
            if not isinstance(client, str) or not ID_RE.fullmatch(client):
                raise CapabilityError("team client is invalid")
            if not isinstance(workspace, str) or not workspace:
                raise CapabilityError("team workspace is invalid")
            if not isinstance(members, dict):
                raise CapabilityError("team members is not a mapping")
            if not all(isinstance(values, list) and all(isinstance(value, str) for value in values) for values in members.values()):
                raise CapabilityError("team member groups must be string lists")
            if client in clients:
                raise CapabilityError(f"duplicate team client: {client}")
            canonical_workspace = str(Path(workspace).expanduser().resolve())
            if canonical_workspace in workspaces:
                raise CapabilityError(f"duplicate team workspace: {canonical_workspace}")
            clients.add(client)
            workspaces.add(canonical_workspace)
            teams.append(Team(data, source, lines))
        except CapabilityError as error:
            if str(error).startswith("duplicate team") or "duplicate YAML key" in str(error) or "unsupported YAML" in str(error) or "escapes" in str(error):
                raise
            gaps.append({"item": path.name, "reason": str(error), "source": "repo:execution/teams/" + path.name + ":1"})
    return teams, gaps


def workspace_binding(workspace: Path, teams: list[Team], agents: dict[str, Agent]) -> dict[str, Any]:
    matches = [team for team in teams if Path(str(team.data["workspace"])).expanduser().resolve() == workspace]
    if len(matches) > 1:
        raise CapabilityError("multiple team bindings match workspace")
    if not matches:
        return {"state": "unknown", "team": None, "assigned": set(), "gaps": ["no exact team workspace binding"]}
    team = matches[0]
    assigned: list[str] = []
    lead = team.data.get("lead")
    if isinstance(lead, str) and lead:
        assigned.append(lead)
    elif lead is not None:
        raise CapabilityError("team lead has unsupported shape")
    for values in team.data["members"].values():
        assigned.extend(values)
    duplicates = sorted({value for value in assigned if assigned.count(value) > 1})
    if duplicates:
        raise CapabilityError("duplicate team member ids: " + ", ".join(duplicates))
    unknown = sorted(set(assigned) - set(agents))
    gaps = ["assigned identity is undefined: " + value for value in unknown]
    return {"state": "bound", "team": team, "assigned": set(assigned), "gaps": gaps}


def parse_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def load_workflows(reader: SourceReader) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    workflows: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    ids: set[str] = set()
    directory = reader.roots["repo"] / "execution" / "workflows"
    if not directory.is_dir():
        return [], [{"item": "workflows", "reason": "workflow registry is missing", "source": "gap:no workflow registry"}]
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.suffix != ".md":
            continue
        text, source = reader.text("repo", path)
        workflow_id = path.stem
        if workflow_id in ids:
            raise CapabilityError("duplicate workflow id: " + workflow_id)
        ids.add(workflow_id)
        lines = text.splitlines()
        title = next((line[2:].strip() for line in lines if line.startswith("# ")), workflow_id)
        header_index = None
        headers: list[str] = []
        for index, line in enumerate(lines):
            cells = parse_table_row(line)
            if cells and {"Step", "Identity", "Input", "Output", "Return"}.issubset(cells):
                header_index, headers = index, cells
                break
        if header_index is None or header_index + 1 >= len(lines):
            gaps.append({"item": workflow_id, "reason": "workflow table is unsupported or missing", "source": f"{source}:1"})
            continue
        separator = parse_table_row(lines[header_index + 1])
        if separator is None or len(separator) != len(headers):
            gaps.append({"item": workflow_id, "reason": "workflow table separator is unsupported", "source": f"{source}:{header_index + 2}"})
            continue
        unsupported = [header for header in headers if header not in {"Step", "Identity", "Input", "Output", "Return", "Skill"}]
        steps = []
        for index in range(header_index + 2, len(lines)):
            cells = parse_table_row(lines[index])
            if cells is None:
                if steps:
                    break
                continue
            if len(cells) != len(headers):
                gaps.append({"item": workflow_id, "reason": "workflow row has unsupported column count", "source": f"{source}:{index + 1}"})
                continue
            row = dict(zip(headers, cells))
            identity_match = WORKFLOW_IDENTITY.fullmatch(row["Identity"])
            steps.append({
                "step": row["Step"], "identity_display": row["Identity"],
                "identity_id": identity_match.group(1) if identity_match else None,
                "input": row["Input"], "output": row["Output"], "return": row["Return"],
                "skill": row.get("Skill"), "source": f"{source}:{index + 1}",
                "identity_parse": "exact" if identity_match else "uncheckable",
            })
        workflows.append({
            "id": workflow_id, "title": title, "source": f"{source}:1", "steps": steps,
            "has_skill_column": "Skill" in headers, "unsupported_columns": unsupported,
        })
    return workflows, gaps


def source_line(agent: Agent, field: str, index: int | None = None) -> str:
    key = (field,) if index is None else (field, index)
    return f"{agent.source}:{agent.lines.get(key, 1)}"


def shelf_status(shelf: Path, skill_id: str) -> tuple[str, str]:
    absolute = Path(os.path.abspath(shelf.expanduser()))
    if not absolute.exists():
        return "uncheckable", "explicit shelf root is missing"
    if not absolute.is_dir():
        return "uncheckable", "explicit shelf root is not a directory"
    trusted = absolute.resolve()
    candidate = trusted / skill_id / "SKILL.md"
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(trusted)
    except ValueError:
        return "uncheckable", "skill path crosses the trusted shelf boundary"
    return ("available", "SKILL.md exists; body not read") if candidate.is_file() else ("missing", "SKILL.md is not present")


def python_main_line(text: str, source: str) -> int | None:
    try:
        tree = ast.parse(text, filename=source)
    except SyntaxError as error:
        raise CapabilityError(f"Python source is uncheckable: {source}:{error.lineno or 1}") from error
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq) or len(test.comparators) != 1:
            continue
        values = (test.left, test.comparators[0])
        names = [value.id for value in values if isinstance(value, ast.Name)]
        strings = [value.value for value in values if isinstance(value, ast.Constant) and isinstance(value.value, str)]
        if names == ["__name__"] and strings == ["__main__"]:
            return node.lineno
    return None


def module_commands(reader: SourceReader) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    commands: list[dict[str, str]] = []
    gaps: list[dict[str, str]] = []
    modules_root = reader.roots["modules"]
    if not modules_root.is_dir():
        return [], [{"item": "modules", "reason": "module directory missing", "source": "gap:no module directory"}]
    command_ids: set[str] = set()
    for module in sorted((path for path in modules_root.iterdir() if path.is_dir()), key=lambda path: path.name):
        manifest_path = module / "install.json"
        if not manifest_path.exists():
            continue
        text, manifest_source = reader.text("modules", manifest_path)
        try:
            manifest = json.loads(text)
        except json.JSONDecodeError as error:
            gaps.append({"item": module.name, "reason": "install.json is uncheckable: " + str(error), "source": f"{manifest_source}:1"})
            continue
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files", []), list):
            gaps.append({"item": module.name, "reason": "install.json has unsupported shape", "source": f"{manifest_source}:1"})
            continue
        tools = module / "tools"
        found = 0
        if tools.is_dir():
            readmes: list[tuple[str, str]] = []
            for readme in sorted(tools.glob("README*.md"), key=lambda path: path.name):
                readme_text, readme_source = reader.text("modules", readme)
                readmes.append((readme_text, readme_source))
            for wrapper in sorted(tools.iterdir(), key=lambda path: path.name):
                if wrapper.is_dir() or wrapper.name.startswith(("test_", ".")) or wrapper.suffix not in {"", ".py", ".sh"}:
                    continue
                resolved, wrapper_label = reader.safe_path("modules", wrapper)
                executable = bool(resolved.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
                entry_line = 1
                source_kind = "executable wrapper"
                if wrapper.suffix == ".py":
                    python_text, wrapper_label = reader.text("modules", wrapper)
                    main_line = python_main_line(python_text, wrapper_label)
                    if main_line is None:
                        continue
                    entry_line = main_line
                    source_kind = "Python __main__ entry point"
                elif not executable:
                    continue
                command_id = module.name + ":" + (wrapper.stem if wrapper.suffix else wrapper.name)
                if command_id in command_ids:
                    raise CapabilityError("duplicate module command id: " + command_id)
                command_ids.add(command_id)
                if wrapper.suffix != ".py":
                    wrapper_label = reader.existence("modules", wrapper)
                invocation = ("python3 " if wrapper.suffix == ".py" else "") + str(wrapper)
                readme_sources = []
                for readme_text, readme_source in readmes:
                    for line_number, line in enumerate(readme_text.splitlines(), 1):
                        if wrapper.name in line:
                            readme_sources.append(f"{readme_source}:{line_number}")
                            break
                commands.append({
                    "id": command_id, "command": wrapper.stem if wrapper.suffix else wrapper.name,
                    "module": module.name, "manifest": f"{manifest_source}:1",
                    "wrapper": f"{wrapper_label}:{entry_line}", "source_kind": source_kind,
                    "invocation": invocation,
                    "readme": "; ".join(readme_sources) if readme_sources else "not declared",
                })
                found += 1
        if found == 0:
            gaps.append({
                "item": module.name, "reason": "no supported CLI entry point is inventoried",
                "source": f"{manifest_source}:1",
            })
    return commands, gaps


def escape(value: Any) -> str:
    text = "" if value is None else str(value)
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 32)
    text = html.escape(text, quote=False).replace("\n", " / ")
    for character in ("\\", "|", "!", "[", "]", "(", ")", "*", "_", "`", "#"):
        text = text.replace(character, "\\" + character)
    return text.strip()


def table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(escape(cell) for cell in row) + " |" for row in rows)
    return lines


def assignment_state(binding: dict[str, Any], agent_id: str | None) -> str:
    if agent_id is None:
        return "uncheckable identity syntax"
    if binding["state"] == "unknown":
        return "unknown: no workspace binding"
    return "assigned by team binding" if agent_id in binding["assigned"] else "defined; not assigned by team binding"


def load_decisions(reader: SourceReader) -> dict[str, dict[str, Any]]:
    path = reader.roots["vault"] / "system-workspace" / "docs" / "capability-decisions.jsonl"
    if not path.is_file() and reader.installed_layout:
        return {}
    text, source = reader.text("vault", path)
    wanted = {"pr-capabilities-md", "workflow"}
    found: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("id") in wanted:
            found[row["id"]] = {"status": row.get("status"), "source": f"{source}:{line_number}"}
    return found


def build_model(repo: Path, vault: Path, workspace: Path, shelf: Path, *, installed_layout: bool = False) -> tuple[dict[str, Any], SourceReader]:
    reader = SourceReader(repo, vault, roots()["modules"], installed_layout=installed_layout)
    try:
        workspace_resolved = workspace.resolve(strict=True)
    except FileNotFoundError as error:
        raise CapabilityError("workspace must exist: " + str(workspace)) from error
    if not workspace_resolved.is_dir():
        raise CapabilityError("workspace is not a directory")
    try:
        workspace_resolved.relative_to(reader.roots["vault"])
    except ValueError as error:
        raise CapabilityError("workspace escapes the authorized vault root") from error

    loader_path, _ = reader.safe_path("repo", tool_path(reader.roots["repo"], "agent_new.py"))
    loader_text, loader_source = reader.text("repo", loader_path)
    loader_gaps = []
    if "def load_identity(" not in loader_text or "def team_data(" not in loader_text:
        loader_gaps.append({"item": "agent_new.py", "reason": "identity/team loader functions are uncheckable", "source": f"{loader_source}:1"})
    loader = load_agent_new(reader.roots["repo"], loader_path)

    policy, _, policy_source = load_yaml_file(reader, "config", reader.roots["config"] / "models.yaml")
    if not isinstance(policy, dict) or not isinstance(policy.get("tiers"), dict):
        loader_gaps.append({"item": "policy.yaml", "reason": "tier mapping is unsupported", "source": f"{policy_source}:1"})

    agents, agent_gaps = load_agents(reader, loader)
    if isinstance(policy, dict) and isinstance(policy.get("tiers"), dict):
        for agent in agents.values():
            if agent.data["tier"] not in policy["tiers"]:
                agent_gaps.append({"item": agent.data["id"], "reason": "identity tier is undefined", "source": source_line(agent, "tier")})
    teams, team_gaps = load_teams(reader)
    binding = workspace_binding(workspace_resolved, teams, agents)
    workflows, workflow_gaps = load_workflows(reader)

    skill_registry, skill_lines, skill_source = load_yaml_file(reader, "config", reader.roots["config"] / "catalog.yaml")
    if not isinstance(skill_registry, dict) or not isinstance(skill_registry.get("gaps", []), list):
        skill_registry = {"gaps": []}
        agent_gaps.append({"item": "skills.yaml", "reason": "skill registry shape is unsupported", "source": f"{skill_source}:1"})

    template_path = reader.roots["modules"] / "base" / "templates-v2" / "CAPABILITIES.md"
    if template_path.is_file() or not installed_layout:
        template_text, template_source = reader.text("modules", template_path)
    else:
        template_text, template_source = reader.text("repo", reader.roots["repo"] / "docs" / "capabilities-template.md")
        loader_gaps.append({"item": "CAPABILITIES template", "reason": "installed layout has no module template; bundled template used", "source": f"{template_source}:1"})
    template_headings = [line[3:].strip() for line in template_text.splitlines() if line.startswith("## ")]
    if template_headings[:len(SECTIONS)] != list(SECTIONS):
        loader_gaps.append({"item": "CAPABILITIES template", "reason": "nine ordered sections are unsupported", "source": f"{template_source}:1"})

    decisions = load_decisions(reader)
    for decision_id in ("pr-capabilities-md", "workflow"):
        row = decisions.get(decision_id)
        if row is None or row["status"] != "ruled":
            loader_gaps.append({"item": decision_id, "reason": "required ruled decision is uncheckable", "source": "gap:decision not ruled in selected registry"})

    commands, command_gaps = module_commands(reader)

    skills: dict[str, dict[str, Any]] = {}
    for agent_id, agent in agents.items():
        for index, skill_id in enumerate(agent.data["skills"]):
            if not SAFE_SKILL_ID.fullmatch(skill_id) or skill_id in {".", ".."}:
                agent_gaps.append({"item": skill_id, "reason": "skill id is unsupported", "source": source_line(agent, "skills", index)})
                continue
            row = skills.setdefault(skill_id, {"id": skill_id, "defined_by": [], "needed_by": [], "sources": [], "source_records": []})
            row["defined_by"].append(agent_id)
            source = source_line(agent, "skills", index)
            row["sources"].append(source)
            row["source_records"].append({"agent": agent_id, "source": source})
    gap_ids: set[str] = set()
    for index, gap in enumerate(skill_registry.get("gaps", [])):
        if not isinstance(gap, dict) or not isinstance(gap.get("id"), str) or not isinstance(gap.get("needed_by", []), list):
            agent_gaps.append({"item": "skills.yaml gap", "reason": "skill gap shape is unsupported", "source": f"{skill_source}:{skill_lines.get(('gaps', index), 1)}"})
            continue
        skill_id = gap["id"]
        needed_by = gap.get("needed_by", [])
        if not SAFE_SKILL_ID.fullmatch(skill_id) or skill_id in {".", ".."}:
            raise CapabilityError(f"invalid skill gap id: {skill_id!r}")
        if skill_id in gap_ids:
            raise CapabilityError("duplicate skill gap id: " + skill_id)
        if not all(isinstance(value, str) and ID_RE.fullmatch(value) for value in needed_by):
            raise CapabilityError("invalid skill gap needed_by list: " + skill_id)
        gap_ids.add(skill_id)
        row = skills.setdefault(skill_id, {"id": skill_id, "defined_by": [], "needed_by": [], "sources": [], "source_records": []})
        row["needed_by"].extend(needed_by)
        gap_source = f"{skill_source}:{skill_lines.get(('gaps', index), 1)}"
        row["sources"].append(gap_source)
        row["source_records"].extend({"agent": value, "source": gap_source} for value in needed_by)
    for row in skills.values():
        row["defined_by"] = sorted(set(row["defined_by"]))
        row["needed_by"] = sorted(set(row["needed_by"]))
        row["sources"] = sorted(set(row["sources"]))
        row["shelf_state"], row["shelf_evidence"] = shelf_status(shelf, row["id"])
        reader.external_existence("shelf:" + row["id"], {
            "state": row["shelf_state"],
            "evidence": row["shelf_evidence"],
            "scope": "explicit shelf path existence only; SKILL.md body not read",
        })

    mcps: dict[str, dict[str, Any]] = {}
    for agent_id, agent in agents.items():
        for index, tool_id in enumerate(agent.data["tools"]):
            row = mcps.setdefault(tool_id, {"id": tool_id, "defined_by": [], "sources": [], "source_records": []})
            row["defined_by"].append(agent_id)
            source = source_line(agent, "tools", index)
            row["sources"].append(source)
            row["source_records"].append({"agent": agent_id, "source": source})
    for row in mcps.values():
        row["defined_by"] = sorted(set(row["defined_by"]))
        row["sources"] = sorted(set(row["sources"]))

    return {
        "workspace": workspace_resolved.name,
        "workspace_path": str(workspace_resolved),
        "agents": agents,
        "binding": binding,
        "workflows": workflows,
        "skills": skills,
        "mcps": mcps,
        "commands": commands,
        "gaps": loader_gaps + agent_gaps + team_gaps + workflow_gaps + command_gaps + [
            {"item": "team binding", "reason": gap, "source": "gap:workspace binding"} for gap in binding["gaps"]
        ],
        "decision_sources": decisions,
    }, reader


def render_markdown(model: dict[str, Any], snapshot: dict[str, Any], timestamp: str) -> str:
    agents: dict[str, Agent] = model["agents"]
    binding = model["binding"]
    assigned = binding["assigned"] if binding["state"] == "bound" else set()
    binding_text = (
        f"bound by {binding['team'].source}" if binding["state"] == "bound"
        else "unknown: no exact team workspace binding"
    )
    lines = [
        "---", "type: capabilities", f"workspace: {json.dumps(model['workspace'], ensure_ascii=False)}", f"timestamp: {timestamp}",
        "generated: true", "generated_by: agent-team capabilities candidate",
        f"source_snapshot: {snapshot['sha256']}", "---", MARKER,
        f"# CAPABILITIES.md — {escape(model['workspace'])}", "",
        "> PRIVATE PREVIEW. Exact source declarations only. Runtime availability remains unverified.",
        f"> Workspace assignment: {escape(binding_text)}.", "",
    ]
    visible_gaps = model["gaps"] if binding["state"] == "bound" else [
        {"item": "team binding", "reason": "no exact team workspace binding", "source": "repo:execution/teams/"}
    ]
    if visible_gaps:
        lines += ["### Coverage limits", ""]
        for gap in visible_gaps:
            lines.append(f"- **{escape(gap['item'])}:** {escape(gap['reason'])} ({escape(gap['source'])})")
        lines.append("")

    lines += ["## Workflows", ""]
    workflow_rows = []
    for workflow in model["workflows"]:
        exact_ids = [step["identity_id"] for step in workflow["steps"] if step["identity_parse"] == "exact"]
        if not workflow["steps"] or len(exact_ids) != len(workflow["steps"]) or not set(exact_ids).issubset(assigned):
            continue
        for step in workflow["steps"]:
            skill = step["skill"] if workflow["has_skill_column"] and step["skill"] else "uncheckable: source has no Skill value"
            if not workflow["has_skill_column"]:
                skill = "missing Skill column; implementation uncheckable"
            state = "candidate for exact team; workspace installation unverified"
            if workflow["unsupported_columns"]:
                state += "; unsupported columns: " + ", ".join(workflow["unsupported_columns"])
            workflow_rows.append([
                "not declared", f"{workflow['title']} / {step['step']}", step["identity_display"],
                step["input"], step["output"], step["return"], skill, state, step["source"],
            ])
    if workflow_rows:
        lines += table(["Function", "Workflow / step", "Identity", "Input", "Output", "Return", "Skill", "Assignment / implementation", "Source"], workflow_rows)
    else:
        lines.append("Unknown: no workflow has only exact identities from this workspace team.")
        lines.append("Source registry: `repo:execution/workflows/`; team registry: `repo:execution/teams/`.")
    lines.append("")

    lines += ["## Agents", ""]
    agent_rows = []
    for agent_id, agent in sorted(agents.items()):
        if agent_id not in assigned:
            continue
        agent_rows.append([
            "not declared", agent.data["display_name"], agent.data["role"], agent.data["return_default"] or "not declared",
            "defined", "assigned by exact team binding", source_line(agent, "role"),
        ])
    if agent_rows:
        lines += table(["Function", "Agent", "Owns", "Returns to", "Definition", "Workspace assignment", "Source"], agent_rows)
    else:
        lines += ["Unknown: no exact workspace team binding.", "Source registry: `repo:execution/teams/`."]
    lines.append("")

    gap_sections = {
        "Reports": "not inventoried by selected safe sources; this does not mean absent",
        "Schedules": "not inventoried by selected safe sources; this does not mean absent",
    }
    for section in ("Reports",):
        lines += [f"## {section}", "", gap_sections[section], "", "Source: `gap:no selected reports registry`.", ""]

    lines += ["## Skills", ""]
    skill_rows = []
    for skill_id, row in sorted(model["skills"].items()):
        assigned_by = sorted(set(row["defined_by"]) & assigned)
        needed_by = sorted(set(row["needed_by"]) & assigned)
        if not assigned_by and not needed_by:
            continue
        related = sorted(set(assigned_by + needed_by))
        related_sources = sorted({item["source"] for item in row["source_records"] if item["agent"] in assigned})
        assignment = "declared for exact team via " + ", ".join(related) + "; runtime unverified"
        skill_rows.append([
            "not declared", skill_id,
            ", ".join(assigned_by) or "not defined; gap only",
            ", ".join(needed_by) or "none declared",
            row["shelf_state"] + ": " + row["shelf_evidence"], assignment,
            "; ".join(related_sources),
        ])
    if skill_rows:
        lines += table(["Function", "Skill", "Defined by", "Needed by", "Shelf evidence", "Workspace assignment", "Source"], skill_rows)
    else:
        lines += ["Unknown: no skills can be scoped without an exact workspace team binding.", "Source registry: `repo:execution/skills.yaml`; team registry: `repo:execution/teams/`."]
    lines.append("")

    lines += ["## Schedules", "", gap_sections["Schedules"], "", "Source: `gap:no selected schedules registry`.", ""]

    lines += ["## MCPs", ""]
    mcp_rows = []
    for tool_id, row in sorted(model["mcps"].items()):
        assigned_by = sorted(set(row["defined_by"]) & assigned)
        if not assigned_by:
            continue
        related_sources = sorted({item["source"] for item in row["source_records"] if item["agent"] in assigned})
        assignment = "declared for exact team via " + ", ".join(assigned_by)
        mcp_rows.append([
            "not declared", tool_id, ", ".join(assigned_by), assignment,
            "runtime-unverified; no connectivity or config read", "; ".join(related_sources),
        ])
    if mcp_rows:
        lines += table(["Function", "Connection", "Defined by", "Workspace assignment", "Runtime state", "Source"], mcp_rows)
    else:
        lines += ["Unknown: no MCP declarations can be scoped without an exact workspace team binding.", "Source registry: `repo:`; team registry: `repo:execution/teams/`."]
    lines.append("")

    lines += ["## CLIs", ""]
    cli_rows = [[
        "not declared", row["command"], row["module"], row["invocation"],
        "available: " + row["source_kind"], "runtime-unverified; command was not executed",
        "unverified: selected manifests do not declare workspace command installation",
        row["manifest"] + "; " + row["wrapper"] + "; README: " + row["readme"],
    ] for row in model["commands"]]
    lines += table(["Function", "Command", "Module", "Invocation", "Source availability", "Runtime", "Workspace installation", "Source"], cli_rows)
    lines.append("")

    for section, source in (("Hooks", "gap:no selected hooks registry"), ("Plugins", "gap:no selected plugins registry")):
        lines += [f"## {section}", "", "not inventoried by selected safe sources; this does not mean absent", "", f"Source: `{source}`.", ""]
    return "\n".join(lines).rstrip() + "\n"


def manifest_for(model: dict[str, Any], snapshot: dict[str, Any], timestamp: str, output_text: str) -> dict[str, Any]:
    return {
        "format": 1,
        "generated_at": timestamp,
        "workspace": model["workspace"],
        "workspace_path": model["workspace_path"],
        "source_snapshot": snapshot,
        "output_sha256": hashlib.sha256(output_text.encode()).hexdigest(),
        "meaning": "defined, assigned, and runtime-unverified states remain separate",
    }


def manifest_path(output: Path) -> Path:
    return output.with_name(output.name + ".manifest.json")


def lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def reject_symlink_components(path: Path, label: str) -> None:
    absolute = lexical_absolute(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise CapabilityError(f"{label} crosses a symlink component: {current}")
        if not os.path.lexists(current):
            break


def require_regular_unaliased(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise CapabilityError(f"{label} is missing: {path}") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise CapabilityError(f"{label} is not a regular file: {path}")
    if metadata.st_nlink != 1:
        raise CapabilityError(f"{label} has a filesystem alias: {path}")


def authenticate_existing_preview(output: Path, sidecar: Path, new_manifest: dict[str, Any]) -> None:
    output_exists = os.path.lexists(output)
    sidecar_exists = os.path.lexists(sidecar)
    if not output_exists and not sidecar_exists:
        return
    if output_exists != sidecar_exists:
        raise CapabilityError("refusing incomplete generated preview pair")
    require_regular_unaliased(output, "existing output")
    require_regular_unaliased(sidecar, "existing sidecar")
    output_bytes = output.read_bytes()
    if MARKER.encode() not in output_bytes:
        raise CapabilityError("refusing to overwrite authored output: " + str(output))
    try:
        stored = json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise CapabilityError("existing sidecar is not a valid generated manifest") from error
    if not isinstance(stored, dict) or stored.get("format") != 1:
        raise CapabilityError("existing sidecar has an unsupported generated format")
    if stored.get("output_sha256") != hashlib.sha256(output_bytes).hexdigest():
        raise CapabilityError("existing sidecar does not authenticate the output bytes")
    if stored.get("workspace_path") != new_manifest.get("workspace_path"):
        raise CapabilityError("existing sidecar belongs to a different workspace")


def atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_preview(output: Path, text: str, manifest: dict[str, Any]) -> None:
    output = lexical_absolute(output)
    sidecar = manifest_path(output)
    reject_symlink_components(output.parent, "output parent")
    output.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink_components(output.parent, "output parent")
    if output.is_symlink() or sidecar.is_symlink():
        raise CapabilityError("refusing symlink output or sidecar")
    authenticate_existing_preview(output, sidecar, manifest)
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    atomic_write(output, text.encode())
    atomic_write(sidecar, manifest_bytes)


def validate_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CapabilityError("timestamp must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise CapabilityError("timestamp must include a timezone")
    return value


def run(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser()
    sidecar = manifest_path(output)
    if args.check:
        if not output.is_file() or not sidecar.is_file():
            print("drift: preview or manifest missing", file=sys.stderr)
            return 1
        stored = json.loads(sidecar.read_text(encoding="utf-8"))
        timestamp = validate_timestamp(str(stored.get("generated_at", "")))
    else:
        timestamp = validate_timestamp(args.timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    model, reader = build_model(
        Path(args.repo).expanduser(), Path(args.vault).expanduser(),
        Path(args.workspace).expanduser(), Path(args.skill_shelf).expanduser(),
        installed_layout=args.installed_layout,
    )
    snapshot = reader.snapshot()
    text = render_markdown(model, snapshot, timestamp)
    manifest = manifest_for(model, snapshot, timestamp, text)
    if args.check:
        current_text = output.read_text(encoding="utf-8")
        current_manifest = json.loads(sidecar.read_text(encoding="utf-8"))
        if current_text != text or current_manifest != manifest:
            print("drift: generated preview or source snapshot changed", file=sys.stderr)
            return 1
        print("ok: no drift")
        return 0
    write_preview(output, text, manifest)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--skill-shelf", required=True)
    parser.add_argument("--timestamp")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--installed-layout", action="store_true", help="Allow absent legacy modules/decisions and use the bundled template; report gaps")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv))
    except (CapabilityError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print("capabilities failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
