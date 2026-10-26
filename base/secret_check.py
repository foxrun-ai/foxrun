#!/usr/bin/env python3
"""Check staged additions or bounded Git history without disclosing matched values."""
import argparse
import ast
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time

RULES = Path(__file__).with_name('secret-patterns.json')


def patterns():
    rows = json.loads(RULES.read_text())
    if not isinstance(rows, list) or not rows or not any(not r.get('allow') for r in rows):
        raise ValueError('Missing secret patterns')
    for row in rows:
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,50}', row['name']):
            raise ValueError('Invalid pattern name')
    return [(row, re.compile(row['regex'])) for row in rows]


def hash_path(path):
    """Only conventional digest and dependency metadata files allow bare digests."""
    name = Path(path).name.lower()
    return (name.endswith(('manifest.tsv', '.sha256', '.lock', '-lock.json'))
            or name in ('yarn.lock', 'pnpm-lock.yaml', 'npm-shrinkwrap.json',
                        'poetry.lock', 'pipfile.lock', 'cargo.lock', 'gemfile.lock',
                        'integrity.json'))


def synthetic_fixture(path, value):
    """A fixture name alone never hides a provider-shaped credential."""
    parts = re.split(r'[/_.-]+', path.lower())
    if not any(part in ('fake', 'sample', 'test', 'tests', 'fixture', 'fixtures') for part in parts):
        return False
    body = re.sub(r'^(?:github_pat_|gh[pousr]_|sk-(?:(?:ant-api03|ant|proj|svcacct)-)?|'
                  r'xox[baprs]-|AIza|ya29\.)', '', value)
    # Repeated short units are intentional examples, including provider test fixtures.
    if any(len(body) >= width * 4 and body == (body[:width] * (len(body) // width))
           for width in range(1, 5) if len(body) % width == 0):
        return True
    words = r'(?:fake|sample|test|example|dummy|placeholder|not|a|real|secret|token|key|password|value|for|testing|only|invalid|redacted|fixture|[0-9]{1,4})'
    return bool(re.fullmatch(words + r'(?:[-_]' + words + r')*', body, re.IGNORECASE))


def code_expression(text, match, path, embedded=True):
    """Recognize unquoted code in supported source files."""
    suffix = Path(path).suffix.lower()
    if suffix in ('.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx'):
        return (not match.groupdict().get('quote')
                and bool(re.search(r'[().\[\],;{}<>`]|=>|\?\?', match.group('value'))))
    if suffix != '.py':
        return False
    try:
        expression = ast.parse(text[match.start('value'):].strip(), mode='eval').body
    except (SyntaxError, ValueError, RecursionError):
        if not embedded:
            return False
        # Source tests can hold a complete code example inside a string literal.
        try:
            source = ast.parse(text.strip())
        except (SyntaxError, ValueError, RecursionError):
            # A block header needs a body before Python can parse it.
            try:
                source = ast.parse(text.strip() + '\n    pass')
            except (SyntaxError, ValueError, RecursionError):
                return False
        # A whole line of valid Python whose unquoted value sits in no string literal is code,
        # for example a keyword argument inside a call: sort_keys=True).encode()).
        value = match.group('value')
        if not any(isinstance(node, ast.Constant) and isinstance(node.value, str) and value in node.value
                   for node in ast.walk(source)):
            return True
        for node in ast.walk(source):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            for nested in match.re.finditer(node.value):
                if (nested.group('value') == match.group('value')
                        and not nested.groupdict().get('quote')
                        and code_expression(node.value, nested, path, embedded=False)):
                    return True
        return False
    return not isinstance(expression, ast.Constant) and any(
        isinstance(node, (ast.Name, ast.Call, ast.Attribute, ast.Subscript))
        for node in ast.walk(expression))


def names(text, rules, path=''):
    for rule, regex in rules:
        if rule.get('allow'):
            text = regex.sub(' ', text)
    found = []
    for rule, regex in rules:
        if rule.get('allow'):
            continue
        for match in regex.finditer(text):
            value = match.groupdict().get('value') or match.group(0)
            if value.startswith(('op://', '${', '{{', '<', '[REDACTED]')):
                continue
            if (rule.get('expression') and not match.groupdict().get('quote')
                    and code_expression(text, match, path)):
                continue
            if rule['name'] in ('entropy-assignment', 'cookie-value'):
                if re.fullmatch(r'\$[A-Za-z_][A-Za-z0-9_]*', value):
                    continue
            if rule['name'] == 'cookie-value' and value.lower() in ('token', 'auth_token', 'ct0'):
                continue
            if rule['name'] == 'entropy-assignment':
                if (match.groupdict().get('quote')
                        and re.fullmatch(r'(?:[a-z]{2,}|[0-9]+)(?:[-:_,](?:[a-z]{2,}|[0-9]+))+', value)
                        and any(re.fullmatch(r'[a-z]{3,}', part) for part in re.split(r'[-:_,]', value))):
                    continue
                if (match.groupdict().get('quote')
                        and (re.search(r'\.test\.', Path(path).name)
                             or re.search(r'_test\.', Path(path).name)
                             or (Path(path).name.startswith('test_') and Path(path).suffix == '.py')
                             or 'tests' in Path(path).parts)
                        and re.fullmatch(r'[a-z0-9]+', value)):
                    continue
                binding = re.split(r'[:=]', match.group(0), maxsplit=1)[0].strip(' \t\"\'')
                binding = binding.lower().replace('_', '').replace('-', '')
                if (Path(path).suffix.lower() in ('.js', '.ts', '.jsx', '.tsx', '.html')
                        and binding in ('storagekey', 'statekey', 'datakey')
                        and re.fullmatch(r'[a-z]+(?:[_.:-][a-z0-9]+){2,}', value)):
                    continue
                if (binding in ('rowkey', 'importkey')
                        and re.fullmatch(r'[a-z]+(?:[_.:-][a-z0-9]+){2,}', value)):
                    continue
                if value.startswith(('/Users/', '/home/', '/etc/', '/opt/', '~/')):
                    continue
                if re.fullmatch(r'(?:[A-Za-z]{1,16}[-_:])?[0-9a-fA-F]{8}-'
                               r'[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-'
                               r'[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}', value):
                    continue
            if rule['name'] == 'entropy-assignment' and hash_path(path):
                if re.fullmatch(r'[a-fA-F0-9]{64}', value):
                    continue
            if synthetic_fixture(path, value):
                continue
            if rule.get('entropy'):
                counts = Counter(value)
                entropy = -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())
                if entropy < rule['entropy'] or len(counts) < rule['distinct']:
                    continue
            found.append(rule['name'])
            break
    return found


def redact(label, rules):
    """Paths and argument errors must never disclose a token-shaped value either."""
    spans = []
    for rule, regex in rules:
        if rule.get('allow'):
            continue
        for match in regex.finditer(label):
            spans.append(match.span('value') if 'value' in match.groupdict() else match.span())
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    for start, end in reversed(merged):
        label = label[:start] + '[REDACTED]' + label[end:]
    return label


def git(repo, *args):
    return ['git', '-C', str(repo), '-c', 'core.quotePath=true',
            '-c', 'core.fsmonitor=false', '-c', 'protocol.allow=never', *args]


def diff_hits(lines, rules, history=False, deadline=None):
    path, commit, new, old, hunk = '', '', 0, 0, False
    seen = set()
    for raw in lines:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError('History parsing bound reached')
        line = raw.rstrip('\n')
        if line.startswith('\x1e'):
            commit = line[1:]; hunk = False
        elif line.startswith('diff --git '):
            path = ''; hunk = False
        elif not hunk and line.startswith(('+++ ', '--- ')):
            label = line[4:].split('\t', 1)[0]
            if label.startswith('"'):
                label = ast.literal_eval(label).encode('latin1').decode('utf-8', 'surrogateescape')
            if label != '/dev/null':
                path = label[2:] if label.startswith(('a/', 'b/')) else label
        elif line.startswith('@@ '):
            match = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if not match:
                raise ValueError('Invalid diff hunk')
            old, new = map(int, match.groups()); hunk = True
        elif hunk and line.startswith(('+', '-')):
            addition = line[0] == '+'
            number = new if addition else old
            if addition or history:
                for name in names(line[1:], rules, path):
                    key = (path, commit, number, name)
                    if key not in seen:
                        seen.add(key)
                        yield dict(file=redact(path, rules), line=number, commit=commit,
                                   pattern=name, value='[REDACTED]')
            if addition:
                new += 1
            else:
                old += 1
        elif hunk and line.startswith(' '):
            new += 1; old += 1


def staged(repo):
    # A pure move (100% similar) carries no new bytes, so it has no hunks to scan.
    result = subprocess.run(git(repo, 'diff', '--cached', '--no-ext-diff', '--no-textconv',
        '--find-renames=100%', '--no-color', '--text', '--unified=0', '--src-prefix=a/', '--dst-prefix=b/', '--'),
        capture_output=True)
    if result.returncode:
        raise ValueError('Cannot read staged diff')
    return list(diff_hits(result.stdout.decode('utf-8', 'replace').split('\n'), patterns()))


def history(repo, commits=1000, max_bytes=67108864, seconds=30):
    """Read at most max_bytes and seconds. Never retain a raw patch on disk."""
    start = time.monotonic(); deadline = start + seconds
    count = subprocess.run(git(repo, 'rev-list', '--all', '--max-count=' + str(commits + 1), '--count'),
                           capture_output=True, text=True, timeout=seconds)
    if count.returncode:
        raise ValueError('Cannot count Git history')
    total = int(count.stdout.strip() or 0)
    rules = patterns()
    result = dict(repo=redact(str(repo), rules), findings=[], commits_counted=total,
                  count_bounded=total > commits, commit_limit=commits, byte_limit=max_bytes,
                  seconds_limit=seconds, bytes_read=0, bounded=total > commits,
                  limit='commits' if total > commits else '', status='clean')
    if not total:
        return result
    command = git(repo, 'log', '--all', '--root', '-m', '--max-count=' + str(commits),
        '--format=%x1e%H', '-p', '--no-ext-diff', '--no-textconv', '--no-renames',
        '--no-color', '--text', '--unified=0', '--src-prefix=a/', '--dst-prefix=b/', '--')
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    body = bytearray(); limit = ''
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                limit = 'time'; break
            for key, _ in selector.select(min(0.1, seconds)):
                chunk = os.read(key.fd, min(65536, max_bytes - len(body) + 1))
                if not chunk:
                    selector.unregister(key.fileobj); break
                body.extend(chunk)
                if len(body) > max_bytes:
                    limit = 'bytes'; break
            if limit:
                break
    finally:
        if limit:
            process.kill()
        process.wait(); process.stdout.close(); selector.close()
    if process.returncode and not limit:
        raise ValueError('Cannot read Git history')
    if limit:
        # Discard the truncated final line, which may be an incomplete match.
        body = body[:max_bytes].rsplit(b'\n', 1)[0] + b'\n'
    hits = []
    try:
        for hit in diff_hits(body.decode('utf-8', 'replace').split('\n'), rules, True, deadline):
            hits.append(hit)
    except TimeoutError:
        limit = 'time'
    result.update(findings=hits, bytes_read=min(len(body), max_bytes), bounded=bool(limit or total > commits),
                  limit=limit or result['limit'],
                  status='findings' if hits else ('clean within bound' if limit or total > commits else 'clean'))
    return result


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Secret check argument error; no values displayed.\n')


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--history', action='store_true')
    parser.add_argument('--commits', type=int, default=1000)
    parser.add_argument('--max-bytes', type=int, default=67108864)
    parser.add_argument('--seconds', type=float, default=30)
    args = parser.parse_args(argv)
    try:
        if min(args.commits, args.max_bytes, args.seconds) <= 0:
            raise ValueError('History bounds must be positive')
        if args.history:
            result = history(args.repo, args.commits, args.max_bytes, args.seconds)
            print(json.dumps(result, ensure_ascii=True))
            return int(bool(result['findings'] or result['bounded']))
        hits = staged(args.repo)
        for hit in hits:
            print(json.dumps(hit, ensure_ascii=True), file=sys.stderr)
        if hits:
            print('Secret check blocked this commit. Remove the staged value.', file=sys.stderr)
        return int(bool(hits))
    except Exception:
        # Git and parser errors can contain raw source. Never echo their messages.
        print('Secret check failed; commit blocked. No values displayed.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
