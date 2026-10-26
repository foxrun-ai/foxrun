#!/usr/bin/env python3
"""Build the system tool map from this install's catalog and tool pages."""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from base.simple_yaml import safe_load


def frontmatter(path):
    """Read only the first YAML document, never the page body."""
    with path.open(encoding='utf-8') as stream:
        if stream.readline().strip() != '---':
            return {}
        lines = []
        for line in stream:
            if line.strip() == '---':
                break
            lines.append(line)
        else:
            return {}
    value = safe_load(''.join(lines))
    return value if isinstance(value, dict) else {}


def cell(value):
    """Keep catalog text inside one Markdown table cell."""
    return re.sub(r'\s+', ' ', str(value or '')).replace('\\', '\\\\').replace('|', '\\|').strip()


def anchor(heading):
    return re.sub(r'[^\w -]', '', heading.lower()).replace(' ', '-')


def build(home, as_of=None):
    """Return a starter page. Only config/tools.yaml selects tool rows."""
    home = Path(home)
    catalog = safe_load((home / 'config/tools.yaml').read_text(encoding='utf-8'))
    if not isinstance(catalog, dict) or not isinstance(catalog.get('tools'), list):
        raise ValueError('config/tools.yaml needs a tools list')
    groups, gaps = {}, []
    tools_root = (home / 'tools').resolve()
    for row in catalog['tools']:
        if not isinstance(row, dict) or not row.get('name'):
            raise ValueError('each tool needs a name')
        if row.get('applies_to', 'global') != 'global':
            continue
        name = cell(row['name'])
        kind = cell(row.get('kind')) or 'unknown'
        source = row.get('page')
        if not isinstance(source, str) or not source.startswith('tools/') or not source.endswith('.md'):
            gaps.append(name + ': no tool page')
            continue
        page = (home / source).resolve()
        if not page.is_relative_to(tools_root) or not page.is_file():
            gaps.append(name + ': ' + cell(source) + ' is missing')
            continue
        meta = frontmatter(page)
        if meta.get('status') == 'off' or meta.get('applies_to', 'global') != 'global':
            continue
        use = cell(meta.get('use')) or 'Other tools'
        purpose = cell(meta.get('what')) or 'see its page'
        link = page.relative_to(tools_root).as_posix()
        groups.setdefault(use, []).append((name, kind, purpose, link))

    date = as_of or datetime.now().astimezone().replace(microsecond=0).isoformat()
    lines = [
        '---', 'type: doc', 'workspace: system', 'timestamp: ' + date, '---',
        '# Capabilities', '',
        '<!-- generated: base/build_caps.py; from config/tools.yaml and tool page front matter -->', '',
        'This page lists declared tools and skills. It does not prove runtime access.', '',
        'Source: [installed tool catalog](../config/tools.yaml) and current tool pages.', '',
        '## Contents', '',
    ]
    headings = sorted((heading for heading in groups if heading != 'Other tools'), key=str.casefold)
    if 'Other tools' in groups:
        headings.append('Other tools')
    headings += ['Catalog gaps', 'Skills']
    lines += ['- [' + heading + '](#' + anchor(heading) + ')' for heading in headings]
    for heading in headings[:-2]:
        lines += ['', '## ' + heading, '', '| Name | Kind | Purpose | Source page |',
                  '| --- | --- | --- | --- |']
        for name, kind, purpose, link in sorted(groups[heading], key=lambda item: item[0].casefold()):
            lines.append('| ' + name + ' | ' + kind + ' | ' + purpose + ' | [' + name + '](' + link + ') |')
    lines += ['', '## Catalog gaps', '']
    lines += sorted(gaps, key=str.casefold) if gaps else ['None. Every row in the catalog has its page.']
    lines += ['', '## Skills', '', '| Name | Source |', '| --- | --- |']
    for path in sorted((home / 'skills').glob('*/SKILL.md'), key=lambda item: item.parent.name.casefold()):
        name = cell(path.parent.name)
        lines.append('| ' + name + ' | [' + name + '](../skills/' + name + '/SKILL.md) |')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', required=True, type=Path)
    parser.add_argument('--output', type=Path, help='Default: <home>/tools/CAPABILITIES.md')
    args = parser.parse_args(argv)
    output = args.output or args.home / 'tools/CAPABILITIES.md'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build(args.home), encoding='utf-8')
    # A catalog or tool-page update also changes workspace TOOLS views.
    script = args.home / 'base/make_workspaces_view.py'
    if script.is_file():
        import subprocess
        portfolio = Path(os.environ.get('FOXRUN_PORTFOLIO', '~/foxrun')).expanduser()
        subprocess.run([sys.executable, '-B', str(script), '--system-home', str(args.home),
                        '--workspace-root', str(portfolio)], check=True)


if __name__ == '__main__':
    main()
