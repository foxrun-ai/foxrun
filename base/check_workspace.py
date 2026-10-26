#!/usr/bin/env python3
"""Read-only workspace checker. Python 3.10+, standard library only.

Run: python3 check_workspace.py WORKSPACE --output-prefix OUTSIDE_WORKSPACE/name
Without --output-prefix, print JSON. Exit 0: clean; 1: findings; 2: run error.
Existing output files are preserved; use .new before their extension instead.

Rules follow foxrun/docs/data-model-definition/workspace-spec.md (2026-09-18).
This checks the target shape, not permission to migrate the current workspace.
Optional --function NAME flags declare additional flat function report names.

Generated files need a sibling FILE.md.sources.json receipt for byte verification:
{"output_sha256":"<hash>","sources":[{"path":"notes/input.md","sha256":"<hash>"}]}
Source paths are workspace-relative. Receipts certify saved bytes, not generator
correctness. Missing receipts are unchecked findings, never silent passes.
No generator, skill, command from a document, or outside service is invoked.
"""

from __future__ import annotations

import argparse
_product_root = next(p for p in __import__('pathlib').Path(__file__).resolve().parents if (p / 'base/person.py').is_file())
__import__('sys').path.insert(0, str(_product_root))
from base import person as _fox_person
from base.paths import resolve_portfolio_path
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import unquote


SPEC = "foxrun/docs/data-model-definition/workspace-spec.md"
CONTRACTS = ("AGENTS.md", "CLAUDE.md", "RESOLVER.md", "SCHEMA.md", "CONCEPTS.md", "DESIGN.md", "BRAND.md")
FOLDERS = {"history", "config", "team", "skills", "tools", "ops", "src", "notes", "specs", "wiki", "raw"}
RUNTIME = {".agents", ".claude", ".codex"}

SKIP_DIRS = {"archive", "System", "node_modules", "__pycache__", "skills", "credentials", "secrets"}
SECRET = re.compile(r"(^\.env|credential|secret|token|(^|[-_.])auth([-_.]|$)|\.pem$|\.key$|\.p12$)", re.I)
WIKI = re.compile(r"(?<!!)\[\[([^\]\n]+)\]\]|!\[\[([^\]\n]+)\]\]")
KEY = re.compile(r"^(?:([\w-]+)|\"([\w-]+)\"|'([\w-]+)')\s*:\s*(.*?)\s*$")


def protected(path: Path, root: Path) -> bool:
    """Reject traversal into hidden, sensitive, archived, or linked surfaces."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    current = root
    for part in parts:
        current /= part
        if part.startswith(".") or part in SKIP_DIRS or SECRET.search(part) or current.is_symlink():
            return True
    return False


def read_bytes(path: Path, root: Path) -> bytes:
    if protected(path, root):
        raise ValueError("protected source")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("not a regular file")
        return handle.read()


def scalar(value: str) -> str:
    value = re.sub(r"\s+#.*$", "", value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def frontmatter(text: str) -> tuple[dict, str, list[str], int]:
    """Read top-level scalar fields; do not claim full YAML validation."""
    lines = text.splitlines()
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return {}, text, ["Frontmatter is absent."], 0
    end = next((i for i in range(1, len(lines)) if lines[i].strip() in {"---", "..."}), None)
    if end is None:
        return {}, text, ["Frontmatter has no closing delimiter."], 0
    fields, errors = {}, []
    for line in lines[1:end]:
        match = KEY.match(line)
        if match:
            key = next(group for group in match.groups()[:3] if group is not None)
            if key in fields:
                errors.append(f"Duplicate frontmatter field: {key}.")
            fields[key] = scalar(match.group(4))
    return fields, "\n".join(lines[end + 1:]), errors, end + 1


def prose_lines(body: str):
    """Keep line numbers; omit fenced code, HTML comments, and inline code."""
    body = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), body, flags=re.S)
    fence = None
    for number, line in enumerate(body.splitlines(), 1):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            yield number, ""
        elif fence:
            yield number, ""
        else:
            yield number, re.sub(r"(`+).*?\1", "", line)


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def record_tables(lines):
    for i in range(len(lines) - 1):
        header = cells(lines[i][1])
        divider = cells(lines[i + 1][1])
        if "|" not in lines[i][1] or not any(c.strip(" *_").casefold() == "status" for c in header):
            continue
        if len(header) != len(divider) or not all(re.fullmatch(r":?-{3,}:?", c) for c in divider):
            continue
        rows = 0
        for _, line in lines[i + 2:]:
            if "|" not in line or len(cells(line)) != len(header):
                break
            rows += 1
        if rows > 15:
            yield lines[i][0], rows


def inventory(root: Path):
    files, skipped = set(), []

    def onerror(error):
        skipped.append({"path": str(Path(error.filename).relative_to(root)), "reason": "directory unreadable"})

    for parent, dirs, names in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
        parent = Path(parent)
        for name in sorted(dirs):
            path = parent / name
            if protected(path, root):
                dirs.remove(name)
                skipped.append({"path": path.relative_to(root).as_posix(), "reason": "excluded directory or symlink"})
        dirs.sort()
        for name in sorted(names):
            path = parent / name
            if protected(path, root):
                skipped.append({"path": path.relative_to(root).as_posix(), "reason": "protected file or symlink"})
            elif path.is_file():
                files.add(path.relative_to(root).as_posix())
    return files, skipped


def check(workspace: Path, workspace_type="ecom", functions=()) -> dict:
    root = resolve_portfolio_path(workspace)
    if root.is_symlink() or root != root.resolve() or not root.is_dir():
        raise ValueError("Workspace must be an existing directory without symlink parents.")
    if any(p in RUNTIME or p in SKIP_DIRS or SECRET.search(p) for p in root.parts[1:]):
        raise ValueError("Workspace is inside a protected path.")
    name = root.name
    function_names = set(functions) | set(_fox_person.workspace_setting(name, 'functions', []))
    if any(not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", f) for f in function_names):
        raise ValueError("Function names must use lowercase words separated by hyphens.")
    findings = []

    def add(code, path, message, severity="warning", **details):
        findings.append(dict(code=code, severity=severity, path=path, message=message, **details))

    files, skipped = inventory(root)
    docs = {}
    for rel in sorted(files):
        if not rel.lower().endswith(".md"):
            continue
        try:
            raw = read_bytes(root / rel, root)
            text = raw.decode("utf-8-sig")
        except (OSError, ValueError, UnicodeError) as exc:
            add("unreadable", rel, f"Cannot inspect this document: {type(exc).__name__}.", "unchecked")
            continue
        fields, body, errors, offset = frontmatter(text)
        lines = [(n + offset, line) for n, line in prose_lines(body)]
        docs[rel] = dict(fields=fields, text=text, raw=raw, lines=lines)
        for error in errors:
            add("frontmatter_invalid", rel, error)
        for key in ("type", "workspace", "timestamp"):
            value = fields.get(key, "")
            if not value or value.casefold() in {"null", "~"}:
                add("frontmatter_missing", rel, f"Frontmatter needs {key}.", field=key)
            elif value[0] in "[{|>&*!":
                add("frontmatter_unverified", rel, f"{key} needs a plain scalar value.", "unchecked", field=key)
        if fields.get("workspace") and fields["workspace"] != name:
            add("frontmatter_workspace_drift", rel, "Workspace field differs from the folder name.", expected=name, actual=fields["workspace"])
        if fields.get("timestamp"):
            try:
                stamp = datetime.fromisoformat(fields["timestamp"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("timezone missing")
            except ValueError:
                add("frontmatter_timestamp_invalid", rel, "Timestamp needs an ISO datetime with a timezone.")
        if Path(rel).name == "CONTEXT.md":
            add("context_file", rel, "CONTEXT.md is outside the target contract set.")
        if Path(rel).name in CONTRACTS or fields.get("type") in {"contract", "agents", "schema", "resolver", "concepts", "brand", "design"}:
            count = len(text.splitlines())
            if count > 80:
                add("contract_too_long", rel, f"Contract has {count} lines; the limit is 80.", lines=count, limit=80)
        for line, rows in record_tables(lines):
            add("records_in_markdown", rel, f"Status table has {rows} data rows; it resembles records.", line=line, rows=rows)

    required = list(CONTRACTS)
    if workspace_type == "personal":
        required = [p for p in required if p not in {"BRAND.md", "DESIGN.md"}]
    for contract in required:
        if contract not in files:
            add("required_contract_missing", contract, "Required contract is absent or inaccessible.", "error")
    generated = {"index.md", "CAPABILITIES.md", f"{name}.md"} | {f"{f}.md" for f in function_names}
    for rel in sorted(generated):
        if rel not in files:
            add("required_generated_file_missing", rel, "Required generated map or report is absent or inaccessible.", "error")
    allowed_files = set(CONTRACTS) | generated | {f"{name}.sqlite", "log.jsonl", ".mcp.json"}
    allowed_files |= {rel + ".sources.json" for rel in generated}
    allowed_dirs = FOLDERS | RUNTIME
    root_entries = sorted(root.iterdir(), key=lambda p: p.name)
    for entry in root_entries:
        allowed = allowed_dirs if entry.is_dir() else allowed_files
        if entry.name not in allowed:
            add("root_entry_not_allowed", entry.name, "Root entry is outside the target workspace spec.")
    for folder in ("docs/plans", "docs/guides", "docs/templates"):
        if (root / folder).is_dir():
            add("document_folder_not_allowed", folder, "This document folder is outside the target workspace spec.")

    by_name = defaultdict(set)
    for rel in files:
        by_name[Path(rel).name].add(rel)
        if rel.lower().endswith(".md"):
            by_name[Path(rel).stem].add(rel)

    def resolve(target, origin):
        target = unquote(target.split("|", 1)[0].split("#", 1)[0].strip())
        if not target:
            return "found", {origin}
        if re.match(r"^[a-zA-Z][\w+.-]*:", target):
            return "external", set()
        # Explicit paths outside the workspace can be checked for existence only.
        candidates = [root / target, root / Path(origin).parent / target, root.parent / target]
        if target.startswith("~/"):
            candidates = [Path(target).expanduser()]
        for candidate in candidates:
            candidate = Path(os.path.abspath(candidate))
            for path in (candidate, candidate.with_suffix(".md") if not candidate.suffix else candidate):
                if protected(path, root.parent):
                    continue
                if path.is_file() or path.is_dir():
                    if path.is_relative_to(root):
                        return "found", {path.relative_to(root).as_posix()}
                    return "external", set()
        matches = by_name.get(target, set()) if "/" not in target else set()
        if len(matches) == 1:
            return "found", matches
        if matches:
            return "ambiguous", matches
        if all(protected(Path(os.path.abspath(p)), root.parent) for p in candidates):
            return "protected", set()
        return "missing", set()

    incoming = set()
    for rel, doc in docs.items():
        for line, content in doc["lines"]:
            for match in WIKI.finditer(content):
                target = match.group(1) or match.group(2)
                state, matches = resolve(target, rel)
                incoming.update(matches - {rel})
                if state == "missing":
                    add("broken_wikilink", rel, "No matching target exists in the checked scope.", target=target, line=line)
                elif state in {"protected", "ambiguous"}:
                    add("wikilink_unverified", rel, f"Wikilink target is {state}.", "unchecked", target=target, line=line)
            for match in re.finditer(r"(?<!!)\[[^\]]*\]\(<?([^\s)>]+)>?(?:\s+[^)]*)?\)", content):
                _, matches = resolve(match.group(1), rel)
                incoming.update(matches - {rel})
    for rel in sorted(set(docs) - incoming - set(CONTRACTS) - generated):
        add("orphan_candidate", rel, "No incoming link from another scanned document; outside links were not searched.")

    index = docs.get("index.md")
    if index:
        for entry in root_entries:
            if protected(entry, root) or entry.name == "index.md":
                continue
            if not re.search(r"(?<![\w.-])" + re.escape(entry.name) + r"(?![\w.-])", index["text"]):
                add("index_entry_missing", "index.md", "Root entry is missing from the index.", target=entry.name)

    generated |= {rel for rel, doc in docs.items() if doc["fields"].get("generated", "").lower() == "true" or "generated_by" in doc["fields"]}
    verified = []
    for rel in sorted(generated & docs.keys()):
        receipt = rel + ".sources.json"
        if receipt not in files:
            add("generated_unverified", rel, "No source-hash receipt exists; generated output cannot be verified.", "unchecked", receipt=receipt)
            continue
        try:
            data = json.loads(read_bytes(root / receipt, root))
            if not isinstance(data, dict) or not isinstance(data.get("sources"), list) or not data["sources"]:
                raise ValueError("nonempty sources list required")
            if not re.fullmatch(r"[0-9a-f]{64}", str(data.get("output_sha256", ""))):
                raise ValueError("output_sha256 required")
            hashes = []
            for source in data["sources"]:
                if not isinstance(source, dict) or not isinstance(source.get("path"), str):
                    raise ValueError("source path required")
                source_path = Path(os.path.abspath(root / source["path"]))
                if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", ""))):
                    raise ValueError("source sha256 required")
                actual = hashlib.sha256(read_bytes(source_path, root)).hexdigest()
                hashes.append((source["path"], source["sha256"], actual))
            drift = False
            for source, expected, actual in hashes:
                if expected != actual:
                    drift = True
                    add("generated_source_drift", rel, "A declared source differs from its generation receipt.", source=source)
            if hashlib.sha256(docs[rel]["raw"]).hexdigest() != data["output_sha256"]:
                drift = True
                add("generated_output_drift", rel, "Generated file differs from its generation receipt.")
            if not drift:
                verified.append(rel)
        except (OSError, ValueError, TypeError) as exc:
            add("generated_unverified", rel, f"Source receipt cannot be verified: {type(exc).__name__}.", "unchecked", receipt=receipt)

    if index:
        try:
            receipt = json.loads(read_bytes(root / "index.md.sources.json", root))
            snapshot_path = receipt["schema_snapshot"]
            if "index.md" not in verified or snapshot_path not in {s["path"] for s in receipt["sources"]}:
                raise ValueError("verified schema source required")
            snapshot = json.loads(read_bytes(root / snapshot_path, root))
            if snapshot["workspace"] != name or not snapshot["tables"]:
                raise ValueError("nonempty workspace schema required")
            seen = set()
            for table in snapshot["tables"]:
                table_name = table["name"]
                if not re.fullmatch(r"[a-z_][a-z0-9_]*", table_name) or table_name in seen:
                    raise ValueError("unique table names required")
                seen.add(table_name)
                rows = read_bytes(root / ("data/" + table_name + ".jsonl"), root).splitlines()
                for row in rows:
                    value = json.loads(row)
                    if not isinstance(value, dict) or ("workspace" in value and value["workspace"] != name):
                        raise ValueError("export row workspace differs")
                if len(rows) != table["count"] or not table.get("sql"):
                    raise ValueError("table schema or export count differs")
                expected = "| " + table_name + " | " + str(len(rows)) + " | data/" + table_name + ".jsonl |"
                if expected not in index["text"].splitlines():
                    raise ValueError("index table count differs")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            add("index_database_unverified", "index.md", "Database schema and export counts need a verified index source receipt: " + type(exc).__name__ + ".", "unchecked")

    findings.sort(key=lambda f: (f["code"], f["path"], f.get("line", 0), f.get("target", "")))
    counts = Counter(f["code"] for f in findings)
    return {
        "format": "workspace-check/v1", "workspace": name, "workspace_path": str(root),
        "workspace_type": workspace_type, "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "spec": SPEC, "read_only": True, "status": "findings" if findings else "clean",
        "summary": {"files_scanned": len(files), "markdown_scanned": len(docs), "findings": len(findings),
                    "by_severity": dict(sorted(Counter(f["severity"] for f in findings).items())), "by_check": dict(sorted(counts.items()))},
        "scope": ["Check the 2026-09-18 draft spec; do not migrate the workspace.",
                  "Skip hidden folders, skills, archives, System, credentials, and symlinks; do not open native settings.",
                  "Orphans are candidates based on incoming links within scanned Markdown only.",
                  "Wikilinks check file targets, not heading or block anchors; basename lookup covers this workspace only.",
                  "Index coverage checks visible root entries; database details remain unchecked.",
                  "Frontmatter checks top-level scalar fields, duplicates, workspace, and timestamp; this is not a full YAML validator.",
                  "Generated receipts verify source and output bytes; generators are never executed.",
                  "The scan is live, not an atomic snapshot; concurrent edits may affect findings."],
        "generated_byte_verified": verified, "skipped": skipped, "findings": findings,
    }


def attach_contract_lint(report: dict, lint_report: dict) -> None:
    """Attach opt-in lint findings without changing the default check path."""
    for finding in lint_report["findings"]:
        report["findings"].append(
            {
                "code": "contract_lint_" + finding["rule"],
                "severity": finding["severity"],
                "path": finding["file"],
                "line": finding["line"],
                "target": finding["target"],
                "message": finding["state"] + ": " + finding["resolution_evidence"],
            }
        )
    report["findings"].sort(
        key=lambda item: (
            item["code"], item["path"], item.get("line", 0), item.get("target", "")
        )
    )
    report["summary"]["findings"] = len(report["findings"])
    report["summary"]["by_severity"] = dict(
        sorted(Counter(item["severity"] for item in report["findings"]).items())
    )
    report["summary"]["by_check"] = dict(
        sorted(Counter(item["code"] for item in report["findings"]).items())
    )
    report["status"] = "findings" if report["findings"] else "clean"
    report["contract_lint"] = lint_report


def markdown(report: dict) -> str:
    def escape(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("`", "'")

    summary = report["summary"]
    lines = ["---", "type: report", 'workspace: ' + _fox_person.workspace('system'), f"timestamp: {report['checked_at']}",
             "status: draft", "tags: [workspace-check, foundation]", "---", "", f"# Workspace check: {report['workspace']}",
             "", "## At a glance", "", "```text", "┌──────────────────┐   ┌──────────────────┐",
             "│ Workspace files  │ → │ Read-only checks │", "└──────────────────┘   └────────┬─────────┘",
             "                               ↓", "                      ┌──────────────────┐",
             "                      │ Findings report  │", "                      └──────────────────┘", "```", "",
             "| Check | Result |", "| --- | --- |", f"| Workspace | `{escape(report['workspace_path'])}` |",
             f"| Files scanned | {summary['files_scanned']} |", f"| Markdown files | {summary['markdown_scanned']} |",
             f"| Findings | {summary['findings']} |", f"| Unchecked findings | {summary['by_severity'].get('unchecked', 0)} |",
             f"| Excluded paths | {len(report['skipped'])} |", "| Workspace changes | None |", "",
             f"Checked at {report['checked_at']} against `{SPEC}`.", "",
             "Findings describe gaps against the target draft. They do not authorize changes.", "", "## Counts", "",
             "| Finding | Count |", "| --- | ---: |"]
    lines.extend(f"| {key} | {value} |" for key, value in summary["by_check"].items())
    lines += ["", "## Scope", ""] + [f"- {s}" for s in report["scope"]]
    lines += ["", "## Findings", "", "Full paths and details are in the companion JSON report.", ""]
    for code, total in summary["by_check"].items():
        lines += [f"### {code} ({total})", "", "| Path | Finding |", "| --- | --- |"]
        entries = [f for f in report["findings"] if f["code"] == code]
        for entry in entries[:20]:
            detail = entry["message"]
            if "target" in entry:
                detail += " Target: " + entry["target"]
            location = entry["path"] + (f":{entry['line']}" if "line" in entry else "")
            lines.append(f"| `{escape(location)}` | {escape(detail)} |")
        if total > 20:
            lines += ["", f"The JSON report contains {total - 20} additional findings for this check."]
        lines.append("")
    return "\n".join(lines) + "\n"


def save_reports(report: dict, prefix: Path) -> list[Path]:
    root = Path(report["workspace_path"])
    prefix = Path(os.path.abspath(prefix.expanduser()))
    if prefix.parent.resolve().is_relative_to(root):
        raise ValueError("Reports must be outside the checked workspace.")
    if not prefix.parent.is_dir():
        raise ValueError("Output directory must already exist.")
    paths = [Path(str(prefix) + suffix) for suffix in (".json", ".md")]
    if any(p.exists() or p.is_symlink() for p in paths):
        paths = [p.with_name(p.stem + ".new" + p.suffix) for p in paths]
    if any(p.exists() or p.is_symlink() for p in paths):
        raise FileExistsError("Output and .new output already exist; nothing was overwritten.")
    payloads = [json.dumps(report, indent=2, ensure_ascii=False) + "\n", markdown(report)]
    for path, payload in zip(paths, payloads):
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    return paths


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--workspace-type", choices=("ecom", "personal"), default="ecom")
    parser.add_argument("--function", action="append", default=[], dest="functions")
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--contract-lint-rules", type=Path)
    parser.add_argument("--contract-lint-vault-root", type=Path)
    parser.add_argument("--contract-lint-skill-root", action="append", type=Path, default=[])
    parser.add_argument("--contract-lint-command-inventory", type=Path)
    parser.add_argument("--contract-lint-approval-source", type=Path)
    args = parser.parse_args(argv)
    try:
        lint_options = (
            args.contract_lint_vault_root,
            args.contract_lint_skill_root,
            args.contract_lint_command_inventory,
            args.contract_lint_approval_source,
        )
        if any(lint_options) and not args.contract_lint_rules:
            raise ValueError("contract lint options require --contract-lint-rules")
        if args.contract_lint_rules and not args.contract_lint_vault_root:
            raise ValueError("contract lint requires --contract-lint-vault-root")
        report = check(args.workspace, args.workspace_type, args.functions)
        if args.contract_lint_rules:
            from contract_lint import scan as contract_lint_scan

            attach_contract_lint(
                report,
                contract_lint_scan(
                    rules_path=args.contract_lint_rules,
                    vault_root=args.contract_lint_vault_root,
                    workspace=args.workspace,
                    skill_roots=args.contract_lint_skill_root,
                    command_inventory=args.contract_lint_command_inventory,
                    approval_source=args.contract_lint_approval_source,
                ),
            )
        if args.output_prefix:
            paths = save_reports(report, args.output_prefix)
            print(json.dumps({"reports": [str(p) for p in paths], **report["summary"]}, indent=2))
        else:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if report["findings"] else 0
    except (OSError, ValueError) as exc:
        print(f"Workspace check failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
