#!/usr/bin/env python3
"""Render a managed Markdown page with the sourced Foxrun page style, offline."""
import argparse
import html
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

def render(text, css):
    lines = text.splitlines()
    if lines and lines[0].strip() == '---':
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), 0)
        lines = lines[end + 1:]
    output, table, fence, items = [], False, False, False
    def inline(value):
        # Raw HTML and executable URLs remain inert. Only local and HTTPS links become links.
        value = html.escape(value)
        def link(m):
            target = html.unescape(m[2])
            if ':' in target.split('/')[0] and not target.startswith('https://'):
                return m[1]
            return '<a href="' + html.escape(target, quote=True) + '">' + m[1] + '</a>'
        value = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, value)
        return re.sub(r'`([^`]+)`', r'<code>\1</code>', value)
    for line in lines + ['']:
        if line.lstrip().startswith(('```', '~~~')):
            output.append('</code></pre>' if fence else '<pre><code>')
            fence = not fence
            continue
        if fence:
            output.append(html.escape(line) + '\n')
            continue
        if table and not line.strip().startswith('|'):
            output.append('</tbody></table></div>'); table = False
        if items and not re.match(r'^\s*(?:[-*]|\d+\.)\s+', line):
            output.append('</ul>'); items = False
        if line.strip().startswith('|'):
            cells = [v.strip() for v in line.strip().strip('|').split('|')]
            if all(re.fullmatch(r':?-+:?', v) for v in cells):
                continue
            if not table:
                output.append('<div class="table-scroll" tabindex="0"><table><tbody>'); table = True
                cell = 'th'
            else:
                cell = 'td'
            output.append('<tr>' + ''.join('<'+cell+'>'+inline(v)+'</'+cell+'>' for v in cells) + '</tr>')
        elif re.match(r'^#{1,6}\s', line):
            mark, value = line.split(' ', 1); n = len(mark)
            output.append('<h%d>%s</h%d>' % (n, inline(value), n))
        elif re.match(r'^\s*(?:[-*]|\d+\.)\s+', line):
            if not items:output.append('<ul>'); items = True
            output.append('<li>' + inline(re.sub(r'^\s*(?:[-*]|\d+\.)\s+', '', line)) + '</li>')
        elif line.strip():
            output.append('<p>' + inline(line) + '</p>')
    if fence:output.append('</code></pre>')
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Foxrun Page</title><style>'+css+'</style><main>'+ '\n'.join(output) + '</main></html>'

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('page', type=Path)
    args = parser.parse_args(argv)
    from lint import protected
    if protected(args.page) or args.page.is_symlink():
        parser.error('Protected or linked page.')
    print(render(args.page.read_text(), (ROOT / 'config/lint/brand.css').read_text()))
    return 0

if __name__ == '__main__':
    sys.exit(main())
