#!/usr/bin/env python3
"""Read-only contract lint for explicit files, a workspace, or the whole vault."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import sys
from urllib.parse import unquote


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from base.paths import resolve_portfolio_path

FORMAT = "foxrun-contract-lint/v1"
RULES_FORMAT = "foxrun-contract-lint-rules/v1"
REFERENCE_DEFINITION = re.compile(
    r"^[ \t]{0,3}\[([^\]\n]+)\]:[ \t]*(?:<([^>\n]+)>|(\S+?))"
    r"(?:[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^\)\n]*\)))?[ \t]*$"
)
CLAUDE_IMPORT = re.compile(r"^\s*@([^\s]+)\s*$")
DOLLAR_SKILL = re.compile(r"\$([a-z][a-z0-9-]*)")
SLASH_SKILL = re.compile(r"/[a-z][a-z0-9-]*")
APPROVAL = re.compile(r"approval://([A-Za-z0-9._:-]*[A-Za-z0-9_-])")
FRONTMATTER_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")
COMMAND_TOKEN = re.compile(r"^[A-Za-z0-9_.+-]+$")
LOWER_COMMAND = re.compile(r"[a-z0-9_][a-z0-9_.+-]*")
PLACEHOLDER = re.compile(r"<[^>]+>|\{\{?[^}]+\}?\}|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")
# Text in angle brackets with no space next to a bracket: a placeholder, never a shell redirect.
ANGLE = re.compile(r"<[^<>\s](?:[^<>\n]*[^<>\s])?>")
PATH_SEGMENT = r"(?:[A-Za-z0-9_.+@%~*-]|" + ANGLE.pattern + r"|\{\{?[^{}\n]+\}?\})+"
PATHISH = re.compile(r"(?:~/|\.{1,2}/|/)?(?:" + PATH_SEGMENT + r"/)*(?:" + PATH_SEGMENT + r")?")
# One prose token per match. Inline code is cut out first; every other character is skipped.
TOKEN = re.compile(
    r"(?P<image>!\[[^\]\n]*\]\([^)\n]*\))"
    r"|(?P<wikilink>!?\[\[(?P<wikitarget>[^\]\n]+)\]\])"
    r"|(?P<link>\[[^\]\n]*\]\(\s*(?:<(?P<angled>[^>\n]+)>|(?P<target>[^\s)>]+))(?:\s+[^)]*)?\))"
    r"|(?P<fullref>\[(?P<reftext>[^\]\n]+)\]\[(?P<reflabel>[^\]\n]*)\])"
    r"|(?P<shortref>\[(?P<shortlabel>[^\]\n]+)\])"
    r"|(?P<word>(?:" + ANGLE.pattern + r"|[^\s`|()\[\]\",;“”<])+)"
)
SHELL_SYNTAX = re.compile(r"\$\(|`|&&|\|\||[;<>]")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})([^`]*)$")
SHELL_FENCES = {"bash", "sh", "shell", "zsh"}
SHELL_CONTROL_WORDS = {"case", "do", "done", "elif", "else", "esac", "fi", "for", "if", "in", "then", "until", "while"}
SHELL_BUILTINS = {".", "alias", "bg", "builtin", "cd", "command", "declare", "disown", "eval", "exec", "exit", "export", "fg", "hash", "history", "jobs", "local", "popd", "pushd", "read", "readonly", "return", "set", "shift", "source", "trap", "type", "typeset", "ulimit", "umask", "unalias", "unset", "wait"}
SCRIPT_INTERPRETERS = {"bash", "node", "perl", "python", "python3", "ruby", "sh", "zsh"}
INLINE_SOURCE_COMMANDS = {".", "source"}
# A plain word is a file pointer only with one of these endings. Inline code accepts more.
PLAIN_FILE_SUFFIXES = ("md", "py", "sh", "sql", "json", "jsonl", "toml", "yaml", "yml", "sqlite")
CODE_FILE_SUFFIXES = PLAIN_FILE_SUFFIXES + ("txt", "csv", "js", "mjs", "ts", "rb", "pl", "html", "css", "db", "plist", "png", "jpg", "svg", "pdf")
# The word right before inline code that makes it a command, and before a plain file name that makes it a pointer.
RUN_CUES = {"run"}
FILE_CUES = {"read", "open"}
# Words that may sit between the paths listed after an absent-path cue.
ABSENT_LIST_WORDS = {"a", "an", "and", "any", "local", "new", "or", "the"}
BARE_NAME_EXCLUDED = {"js", "mjs", "ts", "rb", "pl"}
# One-segment absolute paths that are system folders, never slash skills.
SYSTEM_DIRS = {"bin", "dev", "etc", "home", "lib", "mnt", "opt", "proc", "root", "sbin", "sys", "tmp", "usr", "var"}


class LintError(ValueError):
    """The requested scan cannot run within its declared boundaries."""


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(path: Path) -> Path:
    """Resolve safe portfolio aliases; keep refused links for diagnostics."""
    try:
        return resolve_portfolio_path(path)
    except ValueError:
        # Keep refused links visible to the existing boundary diagnostics.
        return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _symlink_component(path: Path) -> Path | None:
    path = _canonical(path)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return current
    return None


def load_json(path: Path, label: str):
    path = _canonical(path)
    if _symlink_component(path) or not path.is_file():
        raise LintError("missing or unsafe " + label + ": " + str(path))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LintError("invalid " + label + ": " + str(path)) from error


def load_rules(path: Path) -> tuple[dict, str]:
    path = _canonical(path)
    rules = load_json(path, "rules")
    raw = path.read_bytes()
    if not isinstance(rules, dict) or rules.get("format") != RULES_FORMAT:
        raise LintError("unsupported rules format")
    required = {
        "format",
        "recognized_contracts",
        "size_policy",
        "stale_names",
        "parser_limits",
        "protected_parts",
        "protected_file_patterns",
    }
    optional = {"banned_words", "live_spec_dirs", "spec_policy", "declared_absent_headings", "absent_path_cues", "banned_word_prohibition_cues", "instruction_verbs"}
    if not required.issubset(rules) or set(rules) - required - optional:
        raise LintError("rules fields are invalid")
    for key in ("declared_absent_headings", "absent_path_cues", "banned_word_prohibition_cues", "instruction_verbs"):
        values = rules.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.split() for value in values):
            raise LintError(key + " must contain nonempty phrases")
    banned = rules.get("banned_words", [])
    if not isinstance(banned, list) or any(not isinstance(word, str) or not word.strip() for word in banned):
        raise LintError("banned_words must contain nonempty literal words")
    contracts = rules["recognized_contracts"]
    if not isinstance(contracts, dict) or not contracts:
        raise LintError("recognized_contracts must be a nonempty object")
    for name, policy in contracts.items():
        if (
            not isinstance(name, str)
            or not name.endswith(".md")
            or not isinstance(policy, dict)
            or set(policy) != {"required", "frontmatter_status", "max_lines", "tool_inventory"}
            or not isinstance(policy["required"], bool)
            or policy["frontmatter_status"] not in {"allow", "forbid"}
            or (
                policy["max_lines"] is not None
                and (
                    isinstance(policy["max_lines"], bool)
                    or not isinstance(policy["max_lines"], int)
                    or policy["max_lines"] < 1
                )
            )
            or policy["tool_inventory"] not in {"allow", "pointer_only", "prohibit"}
        ):
            raise LintError("invalid contract policy: " + repr(name))
    limit = rules["parser_limits"].get("max_file_bytes")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise LintError("parser_limits.max_file_bytes is invalid")
    return rules, sha256_bytes(raw)


def _roots(values: list[Path], label: str) -> list[Path]:
    result = []
    seen = set()
    for value in values:
        path = _canonical(value)
        if _symlink_component(path) or not path.is_dir():
            raise LintError(label + " must be an existing non-symlink directory: " + str(path))
        resolved = path.resolve(strict=True)
        if resolved in seen:
            raise LintError("duplicate " + label + ": " + str(resolved))
        seen.add(resolved)
        result.append(resolved)
    return result


def _within(path: Path, roots: list[Path]) -> Path | None:
    absolute = _canonical(path)
    return next((root for root in roots if absolute == root or absolute.is_relative_to(root)), None)


def _has_symlink(path: Path, root: Path) -> bool:
    path = _canonical(path)
    root = _canonical(root)
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _protected(path: Path, root: Path, rules: dict) -> str | None:
    path = _canonical(path)
    root = _canonical(root)
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return "outside declared roots"
    protected_parts = set(rules["protected_parts"])
    patterns = [re.compile(value, re.IGNORECASE) for value in rules["protected_file_patterns"]]
    if any(part in protected_parts for part in parts):
        return "protected path part"
    if any(pattern.search(part) for part in parts for pattern in patterns):
        return "secret or native configuration pattern"
    if _has_symlink(path, root):
        return "symlink boundary"
    return None


def _read_contract(path: Path, roots: list[Path], rules: dict, any_name: bool = False) -> tuple[str, str]:
    """Read one contract. With `any_name` (the --as form) the file may have any name and sit anywhere."""
    path = _canonical(path)
    root = _within(path, roots) or (path.parent if any_name else None)
    if root is None:
        raise LintError("contract is outside declared roots: " + str(path))
    reason = _protected(path, root, rules)
    if reason:
        raise LintError("contract crosses " + reason + ": " + str(path))
    if document_policy(path, rules) is None and not any_name:
        raise LintError("unrecognized contract filename: " + path.name)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise LintError("contract is not a regular file: " + str(path))
        raw = stream.read(rules["parser_limits"]["max_file_bytes"] + 1)
    if len(raw) > rules["parser_limits"]["max_file_bytes"]:
        raise LintError("contract exceeds parser byte limit: " + str(path))
    try:
        return raw.decode("utf-8-sig"), sha256_bytes(raw)
    except UnicodeError as error:
        raise LintError("contract is not UTF-8: " + str(path)) from error


def _frontmatter(lines: list[str]) -> tuple[dict[str, tuple[str, int]], int, list[dict]]:
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return {}, 0, []
    end = next((index for index in range(1, len(lines)) if lines[index].strip() in {"---", "..."}), None)
    if end is None:
        return {}, 0, [{"line": 1, "message": "frontmatter has no closing delimiter"}]
    fields = {}
    errors = []
    for index, line in enumerate(lines[1:end], start=2):
        match = FRONTMATTER_KEY.match(line)
        if not match:
            continue
        key, value = match.groups()
        if key in fields:
            errors.append({"line": index, "message": "duplicate frontmatter key: " + key})
        else:
            fields[key] = (value.strip().strip("'\""), index)
    return fields, end + 1, errors


def _finding(file: str, line: int, rule: str, severity: str, target: str, state: str, evidence: str) -> dict:
    return {
        "file": file,
        "line": line,
        "rule": rule,
        "severity": severity,
        "target": target,
        "state": state,
        "resolution_evidence": evidence,
    }


def _reference(kind: str, target: str, line: int, syntax: str) -> dict:
    return {"kind": kind, "target": target, "line": line, "syntax": syntax}


def _literal_command_path(value: str) -> bool:
    if value.startswith("-") or any(character in value for character in "(),…"):
        return False
    return value.startswith(("~/", "./", "../", "/")) or value.endswith((".py", ".sh", ".js", ".mjs", ".ts", ".rb", ".pl"))


def _path_shape(value: str, suffixes: tuple[str, ...]) -> str | None:
    """Say what one unbroken piece of text is: 'path', 'soft' (a slash and no path signal), or None."""
    if not value or "//" in value or not PATHISH.fullmatch(value):
        return None
    core = value.replace("<", "").replace(">", "")
    last = core.rstrip("/").rsplit("/", 1)[-1]
    stem, dot, suffix = last.rpartition(".")
    suffixed = bool(stem and dot) and suffix.casefold() in suffixes
    if "/" not in core:
        # A bare name such as Node.js is a product name, not a script: script endings need a folder.
        return "path" if suffixed and suffix.casefold() not in BARE_NAME_EXCLUDED else None
    if core.startswith(("~/", "./", "../")):
        return "path"
    if core.startswith("/"):
        body = core.strip("/")
        return "path" if body and ("/" in body or suffixed or body in SYSTEM_DIRS) else None
    if core.endswith("/") or suffixed or "*" in core or PLACEHOLDER.search(value):
        return "path"
    return "soft"


def _reference_label(value: str) -> str:
    return " ".join(value.split()).casefold()


def _external_or_anchor(target: str) -> bool:
    target = target.strip()
    return target.startswith("#") or bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target))


def _fence_closes(match: re.Match | None, marker: str) -> bool:
    return bool(
        match
        and match.group(1)[0] == marker[0]
        and len(match.group(1)) >= len(marker)
        and not match.group(2).strip()
    )


def _inline_code_spans(line: str) -> list[tuple[int, int]]:
    runs = list(re.finditer(r"`+", line))
    spans = []
    pending = {}
    for run in runs:
        length = len(run.group(0))
        opening = pending.pop(length, None)
        if opening is None:
            pending[length] = run
        else:
            spans.append((opening.start(), run.end()))
    return spans


def _escaped_at(line: str, index: int) -> bool:
    backslashes = 0
    while index > backslashes and line[index - backslashes - 1] == "\\":
        backslashes += 1
    return backslashes % 2 == 1


def _quoted_spans(line: str) -> list[tuple[int, int]]:
    """Spans inside straight or curly double quotes. A banned word there is a mention, not a use."""
    spans = []
    straight = curly = None
    for index, character in enumerate(line):
        if character == '"':
            if straight is None:
                straight = index
            else:
                spans.append((straight, index + 1))
                straight = None
        elif character == "“" and curly is None:
            curly = index
        elif character == "”" and curly is not None:
            spans.append((curly, index + 1))
            curly = None
    return spans


def _tokens(line: str) -> list[tuple[str, str, re.Match | None]]:
    """Split one prose line into tokens. Every character belongs to at most one token."""
    code = sorted(_inline_code_spans(line))
    starts = {start: end for start, end in code}
    tokens = []
    index = 0
    while index < len(line):
        if index in starts:
            end = starts[index]
            ticks = len(line[index:end]) - len(line[index:end].lstrip("`"))
            tokens.append(("code", line[index + ticks:end - ticks], None))
            index = end
            continue
        match = TOKEN.match(line, index)
        if match and match.lastgroup != "word":
            if _escaped_at(line, index):
                index = match.end()
                continue
            if any(match.start() < end and start < match.end() and not (match.start() <= start and end <= match.end()) for start, end in code):
                match = None
        if not match:
            index += 1
            continue
        tokens.append((match.lastgroup, match.group(0), match))
        index = match.end()
    return tokens


def _reference_definitions(lines: list[str]) -> dict[str, list[tuple[str, int]]]:
    definitions: dict[str, list[tuple[str, int]]] = {}
    fence_marker = None
    for number, line in enumerate(lines, start=1):
        fence = FENCE.match(line)
        if fence_marker is not None:
            if _fence_closes(fence, fence_marker):
                fence_marker = None
            continue
        if fence:
            fence_marker = fence.group(1)
            continue
        match = REFERENCE_DEFINITION.match(line)
        if match:
            label = _reference_label(match.group(1))
            target = match.group(2) or match.group(3)
            definitions.setdefault(label, []).append((target, number))
    return definitions


def _literal_command(command: str, shown: str, number: int, syntax: str, add, note, *, fenced: bool) -> None:
    """Check one literal command line. Text in angle brackets is a placeholder, never a redirect."""
    place = "fenced shell" if fenced else "shell"
    bare = ANGLE.sub("X", command)
    dynamic = SHELL_SYNTAX.search(bare) or "|" in bare or "&" in bare or command.endswith("\\")
    if dynamic or (fenced and "$" in bare):
        note(number, "command_syntax_uncheckable", shown, place + " syntax was retained as inert text and was not evaluated")
        return
    try:
        parts = shlex.split(command, posix=True, comments=fenced)
    except ValueError:
        parts = []
    if not parts:
        note(number, "command_syntax_uncheckable", shown, place + " syntax is outside this bounded parser")
        return
    executable = parts[0]
    if executable in SHELL_CONTROL_WORDS:
        note(number, "command_syntax_uncheckable", shown, place + " control syntax is outside this bounded parser")
        return
    if PLACEHOLDER.search(executable):
        note(number, "command_syntax_uncheckable", shown, "the executable is a placeholder")
    elif executable in SHELL_BUILTINS:
        note(number, "command_builtin_uncheckable", executable, "shell builtin availability was not verified and no shell was executed")
    elif COMMAND_TOKEN.fullmatch(executable):
        add("command", executable, number, syntax)
    elif _literal_command_path(executable) or _path_shape(executable, CODE_FILE_SUFFIXES) == "path":
        add("command_path", executable, number, syntax)
    else:
        note(number, "command_syntax_uncheckable", shown, place + " executable is outside this bounded parser")
        return
    arguments = parts[1:]
    if not fenced:
        for argument in arguments:
            if _literal_command_path(argument):
                add("command_path", argument, number, syntax)
    elif executable in SCRIPT_INTERPRETERS and arguments:
        if arguments[0].startswith("-"):
            note(number, "command_syntax_uncheckable", shown, "interpreter option form is outside this bounded script-path parser")
        elif _literal_command_path(arguments[0]):
            add("command_path", arguments[0], number, syntax)
    elif executable in INLINE_SOURCE_COMMANDS and arguments and _literal_command_path(arguments[0]):
        add("command_path", arguments[0], number, syntax)


def _shell_line(value: str, number: int, syntax: str, add, note) -> None:
    command = value.strip()
    if not command or command.startswith("#"):
        return
    if command.startswith("$ "):
        command = command[2:].lstrip()
    _literal_command(command, command, number, syntax, add, note, fenced=True)


def _code_command(value: str, number: int, syntax: str, add, note) -> bool:
    """Read inline code as a command when it has that shape. Return False when it does not.

    The shape: a `$ ` prompt, or a lowercase first word followed by at least one flag,
    placeholder, quoted value, shell operator, or script path. A plain list of words is not a command.
    """
    prompt = value.startswith("$ ")
    command = value[2:].lstrip() if prompt else value
    words = command.split()
    if not words or (not prompt and len(words) < 2):
        return False
    first = words[0]
    if not prompt:
        if not (LOWER_COMMAND.fullmatch(first) or ANGLE.fullmatch(first) or _path_shape(first, CODE_FILE_SUFFIXES) == "path"):
            return False
        rest = command[len(first):]
        if any(character in ANGLE.sub("X", command) for character in "()…"):
            return False
        if not (ANGLE.search(command) or re.search(r"[\"'$;<>|&]|\s-", rest) or any(_literal_command_path(word) for word in words[1:])):
            return False
    _literal_command(command, command, number, syntax, add, note, fenced=False)
    return True


def _code_span(value: str, number: int, syntax: str, add, note, stale_names: set[str], run_cue: bool = False) -> None:
    """Classify one inline code span once: skill, approval, flags, command, path, or not checked.

    `run_cue` says the word Run stands right before the span: then the span is a command.
    """
    value = value.strip()
    if not value:
        return
    if value in stale_names:
        add("skill", value, number, syntax)
        return
    if DOLLAR_SKILL.fullmatch(value):
        add("skill", value[1:], number, syntax)
        return
    approval = APPROVAL.fullmatch(value)
    if approval:
        add("approval", approval.group(1), number, syntax)
        return
    words = [word for word in re.split(r"[\s·,|()…]+", value) if word]
    skills = [word[1:] for word in words if SLASH_SKILL.fullmatch(word) and word[1:] not in SYSTEM_DIRS]
    single = not any(character.isspace() for character in ANGLE.sub("X", value))
    if value.startswith("-") or (single and "://" in value):
        return
    if run_cue and words and len(skills) < len(words):
        if single and _path_shape(value, CODE_FILE_SUFFIXES) == "path":
            add("command_path", value, number, syntax)
        else:
            command = value[2:].lstrip() if value.startswith("$ ") else value
            _literal_command(command, command, number, syntax, add, note, fenced=False)
        return
    if words and len(skills) < len(words) and _code_command(value, number, syntax, add, note):
        return
    for name in skills:
        add("skill", name, number, syntax)
    if words and len(skills) == len(words):
        return
    if single:
        shape = _path_shape(value, CODE_FILE_SUFFIXES)
        if shape:
            add("path", value, number, syntax, soft=shape == "soft", code=True)
            return
    note(number, "inline_code_uncheckable", value, "inline code is not a path, a command, or a skill name")


def _plain_word(raw: str, number: int, add, note, file_cue: bool = False) -> None:
    """Classify one plain word once: approval, skill, import, path, or nothing.

    `file_cue` says Read or Open stands right before the word: then a plain file name is a file pointer.
    """
    text = re.sub(r"['’]s$", "", raw.lstrip("'‘’*").rstrip(".,;:!?*…")).rstrip("'‘’")
    if not text:
        return
    if "://" in text:
        approval = APPROVAL.fullmatch(text)
        if approval:
            add("approval", approval.group(1), number, raw)
        return
    if text.startswith("$"):
        if DOLLAR_SKILL.fullmatch(text):
            add("skill", text[1:], number, raw)
        return
    if text.startswith("@"):
        if _path_shape(text[1:], PLAIN_FILE_SUFFIXES) == "path":
            add("claude_import", text[1:], number, raw)
        return
    if SLASH_SKILL.fullmatch(text) and text[1:] not in SYSTEM_DIRS:
        add("skill", text[1:], number, raw)
        return
    shape = _path_shape(text, PLAIN_FILE_SUFFIXES)
    if shape == "path" and file_cue and "/" not in text and not PLACEHOLDER.search(text):
        add("path", text, number, raw)
    elif shape == "path" and "/" not in text.replace("<", "").replace(">", "").rstrip("/"):
        # One plain word, such as SKILL.md, docs/ or w/: a name, too little to call a path.
        note(number, "plain_name_text", text, "a plain file or folder name with no folder before it is not read as a path; write a path in backticks")
    elif shape == "path":
        add("path", text, number, raw)
    elif shape == "soft" and all(re.search(r"[A-Za-z]", part) for part in text.split("/")):
        note(number, "plain_slash_text", text, "plain text with a slash and no path signal is not read as a path; write a path in backticks")


def _plain_run(tokens: list, number: int, add, note) -> set[int]:
    """Read `Run name` at the start of a line. Return the indexes of the words it used.

    The word after Run is a command when it holds a digit, dot, hyphen, underscore, or plus, or is
    an interpreter name such as python or sh, and a flag or a script path follows it or it ends
    the sentence. `Run the check.` and `Run the tool.py file.` are prose.
    """
    index = 0
    while index < len(tokens) and re.fullmatch(r"[-*+>]|\d+[.)]|\[[ xX]\]", tokens[index][1]):
        index += 1
    if index + 1 >= len(tokens) or tokens[index][0] != "word" or tokens[index][1].casefold() != "run" or tokens[index + 1][0] != "word":
        return set()
    raw = tokens[index + 1][1]
    following = tokens[index + 2] if index + 2 < len(tokens) else None
    ends = following is None or raw[-1] in ".!?"
    name = raw.rstrip(".,;:!?")
    if not COMMAND_TOKEN.fullmatch(name) or not re.search(r"[A-Za-z]", name) or _path_shape(name, PLAIN_FILE_SUFFIXES):
        return set()
    argument = following[1].rstrip(".,;:!?") if following and following[0] == "word" and not ends else ""
    shaped = bool(re.search(r"[0-9_.+-]", name)) or name in SCRIPT_INTERPRETERS
    script = shaped and bool(argument) and _path_shape(argument, PLAIN_FILE_SUFFIXES) == "path"
    if script:
        add("command", name, number, "Run " + raw)
        add("command_path", argument, number, "Run " + raw + " " + following[1])
        return {index + 1, index + 2}
    if shaped and (argument.startswith("-") or ends):
        add("command", name, number, "Run " + raw)
        return {index + 1}
    if shaped:
        note(number, "plain_run_text", name, "plain text after Run is not read as a command; write the command in backticks")
        return {index + 1}
    return set()


def _cue(tokens: list, index: int) -> str:
    """The plain word right before a token, lowercased, or an empty string.

    Colons and emphasis marks between the word and the token are skipped. Any other word ends the search.
    """
    index -= 1
    while index >= 0 and tokens[index][0] == "word" and not tokens[index][1].strip("*_:"):
        index -= 1
    if index >= 0 and tokens[index][0] == "word":
        return tokens[index][1].strip("*_:").casefold()
    return ""


def _absent_paths(tokens: list, cues: list[list[str]]) -> set[int]:
    """Indexes of inline-code paths listed right after a cue such as `Do not create`: they must stay absent."""
    words = [(index, text.strip(".,;:!?*").casefold()) for index, (kind, text, _match) in enumerate(tokens) if kind == "word"]
    found = set()
    for cue in cues:
        for start in range(len(words) - len(cue) + 1):
            if [text for _index, text in words[start:start + len(cue)]] != cue:
                continue
            for index in range(words[start + len(cue) - 1][0] + 1, len(tokens)):
                kind, text, _match = tokens[index]
                if kind == "code" and _path_shape(text.strip(), CODE_FILE_SUFFIXES):
                    found.add(index)
                elif kind != "word" or text.strip(".,;:!?*").casefold() not in ABSENT_LIST_WORDS:
                    break
    return found


def _references(lines: list[str], stale_names: set[str], absent_cues: list[str] | tuple = ()) -> tuple[list[dict], list[dict]]:
    """Pull every reference from the lines. Each span of text is classified once."""
    references = []
    parser_findings = []
    seen = set()
    cues = [cue.casefold().split() for cue in absent_cues]

    def add(kind: str, target: str, line: int, syntax: str, **flags):
        key = (kind, target, line)
        if key not in seen:
            seen.add(key)
            references.append({**_reference(kind, target, line, syntax), **{name: True for name, value in flags.items() if value}})

    def note(line: int, rule: str, target: str, evidence: str):
        parser_findings.append(_finding("", line, rule, "info", target, "uncheckable", evidence))

    def label(number: int, text: str, shown: str, explicit: bool):
        values = definitions.get(_reference_label(text), [])
        if not values and not explicit:
            return
        if len(values) != 1:
            evidence = "reference label is unresolved" if not values else "reference label has duplicate definitions at lines " + ", ".join(str(item[1]) for item in values)
            note(number, "reference_syntax_uncheckable", text, evidence)
        elif not _external_or_anchor(values[0][0]):
            add("markdown", values[0][0], number, shown)

    definitions = _reference_definitions(lines)
    fence_marker = None
    fence_language = None
    for number, line in enumerate(lines, start=1):
        fence = FENCE.match(line)
        if fence_marker is not None:
            if _fence_closes(fence, fence_marker):
                fence_marker = None
                fence_language = None
            elif fence_language in SHELL_FENCES:
                _shell_line(line, number, line, add, note)
            continue
        if fence:
            fence_marker = fence.group(1)
            fence_language = fence.group(2).strip().split(None, 1)[0].casefold() if fence.group(2).strip() else "(unlabeled)"
            if fence_language not in SHELL_FENCES:
                note(number, "fenced_block_uncheckable", fence_language, "fenced content is retained as inert text and is outside this parser")
            continue
        if REFERENCE_DEFINITION.match(line):
            continue
        imported = CLAUDE_IMPORT.match(line)
        if imported:
            add("claude_import", imported.group(1), number, line.strip())
            continue
        tokens = _tokens(line)
        used = _plain_run(tokens, number, add, note)
        absent = _absent_paths(tokens, cues) if cues else set()
        for index, (kind, text, match) in enumerate(tokens):
            if index in absent:
                add("path", text.strip(), number, "`" + text + "`", absent=True)
            elif kind == "code":
                _code_span(text, number, "`" + text + "`", add, note, stale_names, run_cue=_cue(tokens, index) in RUN_CUES)
            elif kind == "wikilink":
                add("wikilink", match.group("wikitarget"), number, text)
            elif kind == "link":
                add("markdown", match.group("angled") or match.group("target"), number, text)
            elif kind == "fullref":
                label(number, match.group("reflabel") or match.group("reftext"), text, True)
            elif kind == "shortref":
                if not line[match.end():match.end() + 1] == ":":
                    label(number, match.group("shortlabel"), text, False)
            elif kind == "word" and index not in used:
                _plain_word(text, number, add, note, file_cue=_cue(tokens, index) in FILE_CUES)
    return references, parser_findings


def _candidate_groups(target: str, source: Path, workspace: Path, vault: Path, note_first: bool = False) -> list[list[Path]]:
    decoded = unquote(target.split("|", 1)[0].split("#", 1)[0].strip())
    if not decoded:
        return [[source]]
    path = Path(decoded).expanduser()
    if path.is_absolute():
        values = [[path]]
    elif decoded.startswith(("./", "../")):
        values = [[source.parent / path]]
    elif path.parts and path.parts[0] == workspace.name:
        values = [[vault / path]]
    else:
        values = [[source.parent / path], [workspace / path], [vault / path]]
    result = []
    seen = set()
    for group in values:
        variants = []
        for value in group:
            absolute = Path(os.path.abspath(value))
            candidates = [absolute]
            if not absolute.suffix and not decoded.endswith("/"):
                candidates.append(absolute.with_suffix(".md"))
            if note_first:
                candidates.reverse()
            for candidate in candidates:
                if candidate not in seen:
                    seen.add(candidate)
                    variants.append(candidate)
        if variants:
            result.append(variants)
    return result


def _resolve_path(ref: dict, source: Path, workspace: Path, vault: Path, roots: list[Path], rules: dict) -> tuple[str, str]:
    """Say whether one path reference is on disk. `source` is where the contract text counts as living."""
    target = ref["target"]
    if PLACEHOLDER.search(target):
        return "uncheckable", "target contains a placeholder"
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) and not target.startswith("approval://"):
        return "uncheckable", "external or unsupported URI scheme"
    if "\x00" in target:
        return "invalid", "target contains NUL"
    raw = target.split("|", 1)[0].split("#", 1)[0].strip()
    if any(character in raw for character in "*?["):
        return "uncheckable", "glob syntax is not expanded"
    folder_only = raw.endswith("/")
    checked = []
    outside = []
    protected = []
    for group in _candidate_groups(target, source, workspace, vault, note_first=ref["kind"] == "wikilink"):
        for candidate in group:
            if candidate == source:
                return "resolved", "this file"
            root = _within(candidate, roots)
            if root is None:
                outside.append(str(candidate))
                continue
            reason = _protected(candidate, root, rules)
            if reason:
                protected.append(str(candidate) + " " + reason)
                continue
            checked.append(str(candidate))
            if candidate.is_dir() or (candidate.is_file() and not folder_only):
                return "resolved", str(candidate)
    if protected:
        return "uncheckable", "target is in a protected tree and was not opened: " + "; ".join(protected)
    if not checked and outside:
        return "uncheckable", "target is outside declared roots: " + ", ".join(outside)
    if ref["kind"] == "wikilink" and "/" not in raw:
        return "uncheckable", "basename lookup would require an undeclared vault crawl"
    if "/" not in raw and source.parent == vault:
        # The Portfolio contract speaks for every workspace: a bare file name may live in any of them.
        homes = sorted(
            entry.name for entry in os.scandir(vault)
            if entry.is_dir(follow_symlinks=False) and not entry.name.startswith(".")
            and not _protected(Path(entry.path), vault, rules) and (Path(entry.path) / raw).is_file()
        )
        if homes:
            return "resolved", "at the root of workspace folders: " + ", ".join(homes)
    if ref.get("soft"):
        return "uncheckable", "inline code with a slash and no path signal is not on disk; it was not read as a path"
    return "missing", "not on disk; checked: " + ", ".join(checked)


def _skill_state(name: str, skill_roots: list[Path]) -> tuple[str, str]:
    if not skill_roots:
        return "uncheckable", "no skill shelf was declared"
    matches = []
    boundaries = []
    for root in skill_roots:
        path = root / name / "SKILL.md"
        if _has_symlink(path, root):
            if path.exists() or (root / name).is_symlink() or path.is_symlink():
                boundaries.append(str(path))
        elif path.is_file():
            matches.append(str(path))
    if boundaries:
        return "uncheckable", "skill path crosses a symlink boundary: " + ", ".join(boundaries)
    if len(matches) == 1:
        return "resolved", matches[0]
    if len(matches) > 1:
        return "uncheckable", "skill exists in multiple declared shelves: " + ", ".join(matches)
    return "missing", "checked declared skill shelves: " + ", ".join(str(path) for path in skill_roots)


def _commands(path: Path | None) -> tuple[set[str] | None, str]:
    if path is None:
        return None, "PATH"
    value = load_json(path, "command inventory")
    if not isinstance(value, dict) or set(value) != {"executables"} or not isinstance(value["executables"], list):
        raise LintError("command inventory must contain only an executables list")
    if any(not isinstance(item, str) or not COMMAND_TOKEN.fullmatch(item) for item in value["executables"]):
        raise LintError("command inventory contains an invalid executable name")
    return set(value["executables"]), str(Path(path).expanduser().absolute())


def _approval_bindings(path: Path | None) -> tuple[dict[tuple[str, str], set[str]] | None, str]:
    if path is None:
        return None, "no approval source supplied"
    value = load_json(path, "approval source")
    if not isinstance(value, dict) or set(value) != {"approvals"} or not isinstance(value["approvals"], list):
        raise LintError("approval source must contain only an approvals list")
    bindings: dict[tuple[str, str], set[str]] = {}
    for item in value["approvals"]:
        if not isinstance(item, dict) or set(item) != {"file", "sha256", "approval"}:
            raise LintError("approval source contains an invalid binding")
        file = item["file"]
        digest = item["sha256"]
        approval = item["approval"]
        if (
            not isinstance(file, str)
            or not file
            or Path(file).is_absolute()
            or ".." in Path(file).parts
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(approval, str)
            or not approval
        ):
            raise LintError("approval source contains an invalid binding")
        bindings.setdefault((Path(file).as_posix(), digest), set()).add(approval)
    return bindings, str(_canonical(path))


def _tool_inventory_findings(file: str, lines: list[str], policy: str) -> list[dict]:
    if policy == "allow":
        return []
    findings = []
    for index, line in enumerate(lines):
        match = re.match(r"^#{1,6}\s+(tool inventory|tools|commands|skills|capabilities)\s*$", line.strip(), re.IGNORECASE)
        if not match:
            continue
        rows = 0
        for following in lines[index + 1:]:
            if re.match(r"^#{1,6}\s+", following):
                break
            if re.match(r"^\s*(?:[-*+]\s+|\|)", following):
                rows += 1
        prohibited = policy == "prohibit" and rows > 0
        prohibited = prohibited or (policy == "pointer_only" and rows >= 3)
        if prohibited:
            findings.append(
                _finding(file, index + 1, "tool_inventory_prohibited", "warning", match.group(1), "invalid", f"{policy} policy; observed {rows} inventory rows")
            )
    return findings


def _section_lines(lines: list[str], headings: list[str]) -> dict[int, str]:
    """Each line number inside a section whose heading is exactly one of `headings`, with that heading."""
    known = {heading.casefold(): heading for heading in headings}
    inside = None
    numbers = {}
    for number, line in enumerate(lines, 1):
        match = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if match:
            inside = known.get(match.group(1).casefold())
        elif inside:
            numbers[number] = inside
    return numbers


def _prose_lines(lines: list[str]) -> list[tuple[int, str]]:
    """The lines outside code fences, with their numbers. Fence lines themselves are left out."""
    result = []
    marker = None
    for number, line in enumerate(lines, 1):
        fence = FENCE.match(line)
        if marker is not None:
            if _fence_closes(fence, marker):
                marker = None
        elif fence:
            marker = fence.group(1)
        else:
            result.append((number, line))
    return result


def _banned_word_rows(file: str, lines: list[str], words: list[str], cues: list[str]) -> list[dict]:
    """One row per banned word per line outside code fences. Quotation marks do not hide a banned word.

    One exception: inside double quotes, after a prohibition cue such as `Never say` on the same line,
    the word is being banned, not used.
    """
    rows = []
    patterns = [(word, re.compile(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", re.IGNORECASE)) for word in words]
    cue_pattern = re.compile("|".join(r"\b" + r"\s+".join(re.escape(part) for part in cue.split()) + r"\b" for cue in cues), re.IGNORECASE) if cues else None
    for number, line in _prose_lines(lines):
        line = line.replace("’", "'")
        quoted = _quoted_spans(line)
        cue = cue_pattern.search(line) if cue_pattern else None
        for word, pattern in patterns:
            banned = [bool(cue) and cue.end() <= match.start() and any(start <= match.start() and match.end() <= end for start, end in quoted) for match in pattern.finditer(line)]
            if False in banned:
                rows.append(_finding(file, number, "banned_word", "error", word, "invalid", "word is listed in the contract lint rules"))
            if True in banned:
                rows.append(_finding(file, number, "banned_word_quoted", "info", word, "uncheckable", "in double quotes after a prohibition cue: the line bans the word"))
    return rows


def _sentences(line: str) -> list[str]:
    """Cut one line at a period, exclamation mark, or question mark that is followed by a space and is outside backticks."""
    code = _inline_code_spans(line)
    pieces = []
    start = 0
    for match in re.finditer(r"[.!?]\s+", line):
        if not any(begin <= match.start() < finish for begin, finish in code):
            pieces.append(line[start:match.end()])
            start = match.end()
    pieces.append(line[start:])
    return [piece for piece in pieces if piece.strip()]


def _unchecked_instructions(lines: list[str], rules: dict, stale_names: set[str]) -> list[dict]:
    """Instruction sentences that match no grammar form. They are counted, never failed.

    An instruction sentence is a sentence of a line outside code fences, frontmatter, and reference
    definitions that holds a word of `instruction_verbs` as a plain word outside backticks and link text.
    It matches a form when the lint pulls a reference from it or finds a banned word in it.
    """
    verbs = {verb.casefold() for verb in rules.get("instruction_verbs", [])}
    if not verbs:
        return []
    _fields, body, _errors = _frontmatter(lines)
    prose = [(number, line) for number, line in _prose_lines(lines) if number >= body]
    definitions = [line for _number, line in prose if REFERENCE_DEFINITION.match(line)]
    result = []
    for number, line in prose:
        if REFERENCE_DEFINITION.match(line):
            continue
        for sentence in _sentences(line):
            words = [text.strip(".,;:!?*_'‘’…").casefold() for kind, text, _match in _tokens(sentence) if kind == "word"]
            verb = next((word for word in words if word in verbs), None)
            if verb is None:
                continue
            references, _notes = _references([sentence, *definitions], stale_names, rules.get("absent_path_cues", []))
            banned = _banned_word_rows("", [sentence], rules.get("banned_words", []), rules.get("banned_word_prohibition_cues", []))
            if not any(reference["line"] == 1 for reference in references) and not banned:
                result.append({"line": number, "verb": verb, "sentence": sentence.strip()})
    return result


def scan(
    *,
    rules_path: Path,
    vault_root: Path,
    workspace: Path | None = None,
    paths: list[Path] | None = None,
    skill_roots: list[Path] | None = None,
    command_inventory: Path | None = None,
    approval_source: Path | None = None,
    recursive: bool = False,
    all_contracts: bool = False,
    install_as: Path | None = None,
) -> dict:
    """Lint the selected contracts. `findings` are wrong; `unchecked` could not be checked and never fail."""
    rules, rules_sha256 = load_rules(rules_path)
    vault = _roots([vault_root], "vault root")[0]
    skills = _roots(skill_roots or [], "skill root")
    all_roots = _roots([vault, *skills], "declared root")
    commands, command_evidence = _commands(command_inventory)
    approvals, approval_evidence = _approval_bindings(approval_source)
    if sum((workspace is not None, bool(paths), all_contracts)) != 1:
        raise LintError("select exactly one workspace or one or more explicit contract paths")
    scoped = workspace is not None
    if all_contracts:
        workspace = vault
        selected = discover_contracts(vault, vault, rules)
        missing_contracts = []
    elif workspace is not None:
        workspace = _canonical(workspace)
        if _within(workspace, [vault]) is None or _symlink_component(workspace) or not workspace.is_dir():
            raise LintError("workspace must be an explicit non-symlink directory below the vault root")
        selected = [workspace / name for name in rules["recognized_contracts"] if (workspace / name).is_file()]
        if recursive:
            selected = discover_contracts(workspace, vault, rules)
        missing_contracts = [name for name, policy in rules["recognized_contracts"].items() if policy["required"] and not (workspace / name).is_file()]
    else:
        selected = [_canonical(path) for path in paths or []]
        workspace = next((path.parent for path in selected if _within(path, [vault])), vault)
        missing_contracts = []
    virtual = None
    if install_as is not None:
        # Lint one file as if it sat at another path: a template or a draft is written for the place it installs to.
        if scoped or all_contracts or len(selected) != 1:
            raise LintError("--as needs exactly one --path")
        virtual = _canonical(install_as if Path(install_as).is_absolute() else vault / install_as)
        if _within(virtual, [vault]) is None or _protected(virtual, vault, rules) or virtual.suffix != ".md":
            raise LintError("--as must name a Markdown path below the vault root, outside protected trees")
        if document_policy(virtual, rules) is None and "spec_policy" not in rules:
            raise LintError("--as names an unrecognized contract and the rules hold no spec_policy")
    selected_keys = [str(path) for path in selected]
    if len(selected_keys) != len(set(selected_keys)):
        raise LintError("duplicate explicit contract path")
    for path in selected:
        root = _within(path, all_roots) or (path.parent if virtual else None)
        if root is None:
            raise LintError("contract is outside declared roots: " + str(path))
        reason = _protected(path, root, rules)
        if reason:
            raise LintError("contract crosses " + reason + ": " + str(path))
        if document_policy(path, rules) is None and virtual is None:
            raise LintError("unrecognized contract filename: " + path.name)
    stale = {(row["kind"], row["name"]): row for row in rules["stale_names"] if isinstance(row, dict)}
    stale_names = {name for kind, name in stale if kind == "skill"}
    rows = []
    references = []
    scanned = []
    for name in missing_contracts:
        rows.append(_finding((workspace / name).relative_to(vault).as_posix(), 1, "required_contract_missing", "error", name, "missing", "recognized root contract was absent"))
    for path in sorted(selected, key=lambda item: str(item)):
        if not path.exists():
            rows.append(_finding(str(path), 1, "contract_file_missing", "error", path.name, "missing", "explicit contract path does not exist"))
            continue
        text, digest = _read_contract(path, all_roots, rules, any_name=virtual is not None)
        relative = path.relative_to(vault).as_posix() if path.is_relative_to(vault) else str(path)
        located = virtual or path
        lines = text.splitlines()
        rows.extend(_banned_word_rows(relative, lines, rules.get("banned_words", []), rules.get("banned_word_prohibition_cues", [])))
        instructions = _unchecked_instructions(lines, rules, stale_names)
        scanned.append({"file": relative, "sha256": digest, "lines": len(lines), "unchecked_instructions": len(instructions), "unchecked_instruction_lines": instructions})
        contract_approvals = approvals.get((relative, digest), set()) if approvals is not None else set()
        if not contract_approvals and approvals is None:
            rows.append(_finding(relative, 1, "approval_coverage", "info", relative, "uncheckable", approval_evidence))
        elif not contract_approvals:
            rows.append(_finding(relative, 1, "approval_coverage", "warning", relative, "missing", "no exact path and SHA-256 binding in " + approval_evidence))
        policy = document_policy(located, rules) or rules["spec_policy"]
        fields, _body_line, fm_errors = _frontmatter(lines)
        for error in fm_errors:
            rows.append(_finding(relative, error["line"], "frontmatter_invalid", "warning", located.name, "invalid", error["message"]))
        if policy["frontmatter_status"] == "forbid" and "status" in fields:
            rows.append(_finding(relative, fields["status"][1], "frontmatter_status_forbidden", "warning", fields["status"][0], "invalid", "status belongs in records, not this contract type"))
        if policy["max_lines"] is not None and len(lines) > policy["max_lines"]:
            rows.append(_finding(relative, policy["max_lines"] + 1, "contract_size_policy", rules["size_policy"]["severity"], str(len(lines)), "invalid", rules["size_policy"]["label"] + f"; configured limit={policy['max_lines']}"))
        rows.extend(_tool_inventory_findings(relative, lines, policy["tool_inventory"]))
        refs, parser_findings = _references(lines, stale_names, rules.get("absent_path_cues", []))
        for finding in parser_findings:
            finding["file"] = relative
            rows.append(finding)
        owner = workspace
        if not scoped and located.is_relative_to(vault):
            parts = located.relative_to(vault).parts
            owner = vault / parts[0] if len(parts) > 1 else vault
        may_be_absent = _section_lines(lines, rules.get("declared_absent_headings", []))
        checked = []
        for ref in refs:
            key = (ref["kind"], ref["target"])
            rule = ref["kind"] + "_reference"
            if key in stale and located.name in stale[key].get("contracts", []):
                rule, state, evidence = "stale_" + ref["kind"], "invalid", "use " + stale[key]["replacement"]
            elif ref["kind"] == "skill":
                state, evidence = _skill_state(ref["target"], skills)
            elif ref["kind"] == "command":
                if commands is None:
                    found = shutil.which(ref["target"])
                    state, evidence = ("resolved", found) if found else ("missing", "not present on PATH")
                else:
                    state = "resolved" if ref["target"] in commands else "missing"
                    evidence = "declared command inventory: " + command_evidence
            elif ref["kind"] == "approval":
                if ref["target"] in contract_approvals:
                    state, evidence = "resolved", approval_evidence
                else:
                    state, evidence = "uncheckable", "approval marker is not bound to this file and SHA-256; " + approval_evidence
            else:
                state, evidence = _resolve_path(ref, located, owner, vault, all_roots, rules)
                if ref.get("absent") and state == "missing":
                    state, evidence = "resolved", "absent, as the line requires"
                elif ref.get("absent") and state == "resolved":
                    rule, state, evidence = "forbidden_path_exists", "invalid", "on disk, but the line says not to create it: " + evidence
            checked.append([ref, rule, state, evidence])
        # A path in backticks under a declared-absent heading may be missing. Links, imports, and scripts are always checked.
        for item in checked:
            ref, rule, state, _evidence = item
            if state == "missing" and rule == "path_reference" and ref.get("code") and ref["line"] in may_be_absent:
                item[2:] = ["uncheckable", f"declared under {may_be_absent[ref['line']]}: it may not be on disk yet"]
        for ref, rule, state, evidence in checked:
            if state != "resolved":
                severity = "error" if rule.startswith("stale_") else "info" if state == "uncheckable" else "warning"
                rows.append(_finding(relative, ref["line"], rule, severity, ref["target"], state, evidence))
            references.append({"file": relative, **{name: value for name, value in ref.items() if name not in {"soft", "absent", "code"}}, "state": state, "resolution_evidence": evidence})
    rows.sort(key=lambda item: (item["file"], item["line"], item["rule"], item["target"]))
    references.sort(key=lambda item: (item["file"], item["line"], item["kind"], item["target"]))
    findings = [row for row in rows if row["state"] != "uncheckable"]
    unchecked = [row for row in rows if row["state"] == "uncheckable"]
    counts = Counter(item["state"] for item in rows)
    return {
        "format": FORMAT,
        "read_only": True,
        "rules_sha256": rules_sha256,
        "vault_root": str(vault),
        "workspace": str(workspace),
        "scanned": scanned,
        "parser_limits": rules["parser_limits"],
        "summary": {"contracts": len(scanned), "references": len(references), "findings": len(findings), "unchecked": len(unchecked), "by_state": dict(sorted(counts.items()))},
        "references": references,
        "findings": findings,
        "unchecked": unchecked,
    }


def document_policy(path: Path, rules: dict) -> dict | None:
    if path.name.endswith(".new.md") or path.name.endswith(".md.new"):
        return None
    if path.name in rules["recognized_contracts"]:
        return rules["recognized_contracts"][path.name]
    for directory in rules.get("live_spec_dirs", []):
        parts = Path(directory).parts
        if path.suffix == ".md" and any(path.parts[i:i + len(parts)] == parts for i in range(len(path.parts) - len(parts))):
            return rules["spec_policy"]
    return None


def discover_contracts(start: Path, vault: Path, rules: dict) -> list[Path]:
    """List active contracts without reading hidden, private, or historical trees."""
    selected = []
    history = {"scratch", "outputs", "handoffs", "snapshots", "sources", "drafts", "node_modules", "System"}
    for directory, names, files in os.walk(start, followlinks=False):
        parent = Path(directory)
        names[:] = sorted(name for name in names if not name.startswith(".")
                          and name not in history and not _protected(parent / name, vault, rules))
        for name in sorted(files):
            path = parent / name
            if document_policy(path, rules) is not None and not _protected(path, vault, rules):
                selected.append(path)
    return selected


def print_findings(report: dict, show_unchecked: bool = False) -> None:
    """One line per finding with file and line. Unchecked text is listed only on request."""
    for finding in report["findings"] + (report["unchecked"] if show_unchecked else []):
        print(f"{finding['file']}:{finding['line']}: {finding['rule']}: {finding['target']}: {finding['state']}: {finding['resolution_evidence']}")
    if not report["findings"]:
        print(f"PASS {report['summary']['contracts']} contracts; no findings")
    for item in report["scanned"]:
        print(f"{item['file']}: unchecked instructions: {item['unchecked_instructions']}")
        for row in item["unchecked_instruction_lines"] if show_unchecked else []:
            print(f"{item['file']}:{row['line']}: unchecked_instruction: {row['verb']}: uncheckable: {row['sentence']}")
    if report["unchecked"] and not show_unchecked:
        print(f"{len(report['unchecked'])} not checked; add --unchecked to list them", file=sys.stderr)


def save_report(report: dict, output: Path) -> Path:
    output = _canonical(output)
    if not output.parent.is_dir() or _symlink_component(output.parent):
        raise LintError("report parent must be an existing non-symlink directory")
    protected = [_canonical(Path(report["workspace"])), _canonical(Path(report["vault_root"]))]
    if any(output == root or output.is_relative_to(root) for root in protected):
        raise LintError("report output must be outside scanned roots")
    candidate = output
    if os.path.lexists(candidate):
        candidate = candidate.with_name(candidate.stem + ".new" + candidate.suffix)
    if os.path.lexists(candidate):
        raise FileExistsError("report and .new report exist; nothing was overwritten")
    descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--vault-root", type=Path, required=True)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--workspace", type=Path)
    scope.add_argument("--path", action="append", type=Path, dest="paths")
    scope.add_argument("--all", action="store_true", dest="all_contracts")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--text", action="store_true", help="one line per finding with file and line")
    parser.add_argument("--json", action="store_true", help="print the full structured report")
    parser.add_argument("--skill-root", action="append", type=Path, default=[])
    parser.add_argument("--command-inventory", type=Path)
    parser.add_argument("--approval-source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--as", type=Path, dest="install_as", help="lint the one --path file as if it sat at this path below the vault root")
    parser.add_argument("--unchecked", action="store_true", help="also list the text that could not be checked")
    parser.add_argument("--judgment", action="store_true", help="also run the model judgment pass; off unless given")
    parser.add_argument("--judgment-command", help="the Jev runner command, for example: node /path/to/jev/scripts/jev.mjs")
    parser.add_argument("--judgment-dir", type=Path, help="existing folder outside the vault for the request and the answers")
    parser.add_argument("--judgment-words", action="append", type=Path, default=[], help="a file that holds the approved words; repeat for more")
    parser.add_argument("--judgment-database", type=Path, help="database where the Jev runner records each run")
    args = parser.parse_args(argv)
    try:
        report = scan(
            rules_path=args.rules,
            vault_root=args.vault_root,
            workspace=args.workspace,
            paths=args.paths,
            skill_roots=args.skill_root,
            command_inventory=args.command_inventory,
            approval_source=args.approval_source,
            recursive=args.recursive,
            all_contracts=args.all_contracts,
            install_as=args.install_as,
        )
        if args.judgment:
            import contract_judgment

            try:
                contract_judgment.run(report, command=args.judgment_command, directory=args.judgment_dir, word_files=args.judgment_words, database=args.judgment_database)
            except contract_judgment.JudgmentError as error:
                raise LintError(str(error)) from error
        if args.output:
            path = save_report(report, args.output)
            print(json.dumps({"report": str(path), **report["summary"]}, indent=2))
        elif not args.json or args.text:
            print_findings(report, args.unchecked)
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if report["findings"] else 0
    except (OSError, LintError, FileExistsError) as error:
        print("Contract lint failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
