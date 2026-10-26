#!/usr/bin/env python3
"""Add, change, or remove one sourced glossary row, then rebuild its glossary.

python3 base/words.py --home HOME --portfolio PORTFOLIO add|change \
  --workspace system --group GROUP --word WORD --meaning MEANING --source SOURCE [--where WHERE]
python3 base/words.py --home HOME --portfolio PORTFOLIO remove \
  --workspace system --group GROUP --word WORD --source REASON
System rows live in config/words.tsv; local rows in WORKSPACE/config/glossary-words.tsv.
Python 3.9 standard library only.
"""
import argparse
import csv
import io
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from base import published_pages

FIELDS = ('workspace', 'group', 'word', 'meaning', 'where', 'source')
LOCAL_FIELDS = {'word', 'meaning', 'group', 'source'}


def regular(path, root):
    """Refuse links before reading or replacing a managed path."""
    path.relative_to(root)
    for item in (path,) + tuple(path.parents):
        if item.is_symlink():
            raise ValueError('linked path: ' + str(item))
        if item == root:
            break
    if path.exists() and not path.is_file():
        raise ValueError('not a regular file: ' + str(path))


def key(row):
    return tuple(row[name].strip().casefold() for name in ('workspace', 'group', 'word'))


def validate(values, require_meaning=True):
    seen = set()
    for row in values:
        required = ('workspace', 'group', 'word', 'source') + (('meaning',) if require_meaning else ())
        if any(not row[name].strip() for name in required):
            raise ValueError(', '.join(required) + ' are required')
        if any(any(char in row[name] for char in '\t\r\n\x00') for name in FIELDS):
            raise ValueError('word fields must be single-line TSV cells')
        if key(row) in seen:
            raise ValueError('duplicate word in workspace and group: ' + row['word'])
        seen.add(key(row))


def read_rows(path, workspace):
    if not path.exists():
        return list(FIELDS), []
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        fields = reader.fieldnames or []
        required = set(FIELDS) if workspace == 'system' else LOCAL_FIELDS
        if len(fields) != len(set(fields)) or not required.issubset(fields) or set(fields) - set(FIELDS):
            raise ValueError('invalid word TSV header: ' + str(path))
        values = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in values):
        raise ValueError('invalid word TSV row width: ' + str(path))
    # Keep the column order of older workspace files; append their missing columns.
    fields += [name for name in FIELDS if name not in fields]
    for row in values:
        row.setdefault('workspace', workspace)
        row.setdefault('where', '')
        if workspace != 'system' and row['workspace'] != workspace:
            raise ValueError('workspace row belongs to another workspace')
    validate(values)
    return fields, values


def write_word(home, portfolio, operation, row):
    if operation not in ('add', 'change', 'remove'):
        raise ValueError('unknown word operation: ' + operation)
    if operation == 'remove':
        row = {name: row.get(name, '') for name in FIELDS}
    home, portfolio = Path(home).absolute(), Path(portfolio).absolute()
    workspace = row['workspace']
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', workspace):
        raise ValueError('invalid workspace')
    root = home if workspace == 'system' else portfolio / workspace
    if not root.is_dir():
        raise ValueError('workspace home does not exist: ' + str(root))
    target = root / ('config/words.tsv' if workspace == 'system' else 'config/glossary-words.tsv')
    regular(target, home if workspace == 'system' else portfolio)
    fields, values = read_rows(target, workspace)
    validate([row], require_meaning=operation != 'remove')
    matches = [index for index, value in enumerate(values) if key(value) == key(row)]
    if operation == 'add' and matches:
        raise ValueError('duplicate word in workspace and group: ' + row['word'])
    if operation in ('change', 'remove') and not matches:
        raise ValueError('no word to ' + operation + ' in workspace and group: ' + row['word'])
    before = values[matches[0]] if matches else None
    if operation == 'remove':
        del values[matches[0]]
    elif matches:
        values[matches[0]] = dict(row)
    else:
        # Keep each group together for the existing page generator.
        siblings = [index for index, value in enumerate(values)
                    if key(value)[:2] == key(row)[:2]]
        values.insert(siblings[-1] + 1 if siblings else len(values), dict(row))
    validate(values)
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t', lineterminator='\n')
    writer.writeheader()
    writer.writerows(values)
    # Build in memory first: generator failures must leave the rows and pages intact.
    products = published_pages.pages(home, portfolio,
        word_rows=values if workspace == 'system' else None,
        local_word_rows={workspace: values} if workspace != 'system' else None)
    outputs = {target: stream.getvalue()}
    outputs.update({path: body for path, body in products.items() if path.parent in (root, root / 'config')})
    for path in outputs:
        regular(path, home if workspace == 'system' else portfolio)
    originals = {path: path.read_bytes() if path.exists() else None for path in outputs}
    written = []
    try:
        for path, body in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            written.append(path)
            path.write_text(body, encoding='utf-8')
    except OSError:
        for path in reversed(written):
            if originals[path] is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(originals[path])
        raise
    print({'add': 'Added', 'change': 'Changed', 'remove': 'Removed'}[operation] + ': ' + str(target))
    print('FROM: ' + json.dumps(before, ensure_ascii=False, sort_keys=True))
    print('TO: ' + json.dumps(None if operation == 'remove' else row, ensure_ascii=False, sort_keys=True))
    if operation == 'remove':
        print('SOURCE: ' + row['source'])
    print('Rebuilt: ' + str(root / 'GLOSSARY.md'))
    return None if operation == 'remove' else row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', required=True, type=Path)
    parser.add_argument('--portfolio', required=True, type=Path)
    commands = parser.add_subparsers(dest='operation', required=True)
    for operation in ('add', 'change', 'remove'):
        command = commands.add_parser(operation)
        for field in FIELDS:
            required = field != 'where' and (operation != 'remove' or field != 'meaning')
            command.add_argument('--' + field, required=required, default='' if not required else None)
    args = parser.parse_args(argv)
    try:
        write_word(args.home, args.portfolio, args.operation, {name: getattr(args, name) for name in FIELDS})
    except (OSError, ValueError, KeyError) as error:
        print('FAIL words: ' + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
