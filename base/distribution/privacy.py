#!/usr/bin/env python3
"""Scan every shipped byte and archive. Never print a matched private value."""
from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
import argparse
import bz2
from collections import Counter
import csv
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tarfile
import unicodedata
import zipfile
import zlib

MAX_BYTES = 32_000_000
MAX_EXPANDED_BYTES = 64_000_000
MAX_MEMBERS = 1000
MAX_DEPTH = 5
PATTERNS = {
    'private-owner': re.compile(r'(?<![\w])(?:' + '|'.join(re.escape(t) for t in _fox_person.private_terms()) + r')(?![\w])', re.I),
    'email': re.compile(r'(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?!\w)', re.I),
    'phone': re.compile(r'(?<![\w])(?:(?:\+?1[- .]?)?(?:\([2-9][0-9]{2}\)[- .]?|[2-9][0-9]{2}[- .])[0-9]{3}[- .]?[0-9]{4}|\+[1-9][0-9 ()-]{7,18}[0-9]|[1-9][0-9]{9,14}|[2-9][0-9]{2}[- .][0-9]{4})(?![\w])'),
    'street-address': re.compile(r'\b[0-9]{1,6}[A-Za-z]?(?:[-/][0-9]{1,6})?[ \t]+(?:[A-Za-z0-9.]+[ \t]+){0,7}(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl|Terrace|Ter|Circle|Cir|Parkway|Pkwy|Highway|Hwy|Trail|Trl)\b', re.I),
    'key': re.compile(r'(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{12,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)', re.I),
    'key-assignment': re.compile(r'\b(?:api|access|secret|private)[_-]?(?:key|token)["\']?\s*[:=]\s*["\']?[A-Za-z0-9_+/=-]{20,}', re.I),
    'money': re.compile(r'(?:\$\s*[-+]?\s*\d[\d,]*(?:\.\d+)?|\b(?:USD|CAD|AUD|EUR|GBP)\s+[-+]?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s+(?:USD|CAD|AUD|EUR|GBP|dollars?)\b)', re.I),
    'money-field': re.compile(r'\b(?:amount|price|cost|budget)(?:[_-](?:minor|micro|usd))?["\']?\s*[:=]\s*["\']?[-+]?\d+(?:\.\d+)?', re.I),
    'private-home': re.compile(r'/(?:Users|home)/[^/\s"\']+'),
}
PROTECTED = re.compile(r'(?:^\.|credential|secret|token|(?:^|[-_.])auth(?:[-_.]|$)|settings?|\.pem$|\.key$|\.p12$)', re.I)
SKIP = {'archive', 'System', 'node_modules', '__pycache__', 'runtime', 'runtimes', 'mcp', 'config', 'configs'}
TEXT_SUFFIXES = {'.md', '.txt', '.json', '.jsonl', '.csv'}
BRAND_FIELDS = {'brand', 'brands', 'brandname', 'productbrand', 'vendor', 'manufacturer'}
PRODUCT_FIELDS = {'product', 'products', 'productname', 'productnames', 'producttitle', 'itemname', 'itemtitle'}
SKU_FIELDS = {'sku', 'skus', 'sellersku', 'merchantsku', 'productsku', 'variantsku', 'sourcesku'}

def safe_files(root, databases=False, all_names=False):
    if root.is_symlink() or not root.is_dir() or any(p.is_symlink() for p in root.parents):
        raise ValueError('Private reference root must be an ordinary directory.')
    import os
    for base, dirs, names in os.walk(root, followlinks=False):
        directory = Path(base)
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not PROTECTED.search(d) and not (directory / d).is_symlink())
        for name in sorted(names):
            path = directory / name
            if PROTECTED.search(name) or path.is_symlink():
                continue
            suffixes = TEXT_SUFFIXES | ({'.sqlite', '.db'} if databases else set())
            if path.suffix.lower() in suffixes or all_names:
                if path.stat().st_size > MAX_BYTES:
                    raise ValueError('A private reference exceeds the size limit; sweep refused.')
                yield path

def reference_values(people, business):
    values = {'real-person': set(), 'business-brand': set(), 'business-product': set(), 'business-sku': set()}
    money = set()
    def kind(key, context=False):
        key = re.sub(r'[^a-z0-9]', '', key.casefold())
        if key in BRAND_FIELDS: return 'business-brand'
        if key in SKU_FIELDS: return 'business-sku'
        if key in PRODUCT_FIELDS or (context and key in {'name', 'title'}): return 'business-product'
        return None
    def add(reason, value):
        if not reason: return
        if isinstance(value, list):
            for item in value: add(reason, item)
        elif isinstance(value, str):
            value = unicodedata.normalize('NFKC', value).strip().strip('"\'')
            if reason == 'business-sku' and re.search(r'[,;\n]| / ', value):
                for item in re.split(r'[,;\n]| / ', value):
                    add(reason, item.strip().strip(chr(96)+'*'))
                return
            if value and any(c.isalnum() for c in value) and value.casefold() not in {'null', 'none', 'unknown', 'missing', 'n/a', 'na', 'tbd', 'not set', 'product', 'sku', 'brand'} and not any(c in value for c in '\n\r{}<>'):
                values[reason].add(value)
    for path in safe_files(people, all_names=True):
        stem = re.sub(r'[-_]+', ' ', path.stem).strip()
        text = path.read_text(encoding='utf-8') if path.suffix.lower() in TEXT_SUFFIXES else ''
        person = bool(re.search(r'^type:\s*["\']?person["\']?\s*$', text, re.M))
        if not person and stem.casefold() in {'index', 'people', 'readme', 'agents', 'claude', 'schema', 'concepts', 'log', 'home'}:
            continue
        add('real-person', stem)
        for match in re.finditer(r'^(?:name|full_name):\s*["\']?([^\n"\']+)|^#\s+([A-Z][^\n#]+)', text, re.M):
            add('real-person', match.group(1) or match.group(2))
    if not values['real-person']: raise ValueError('No person names were loaded; sweep refused.')
    def object_values(value, context=False):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.casefold() in {'columns', 'properties', 'schema', 'definitions', 'field_types'}:
                    continue
                add(kind(key, context), item)
                child_context = (context or bool(re.search(r'product|catalog', key, re.I)))
                if key.casefold() in {'variants', 'options', 'images', 'metafields', 'values'}:
                    child_context = False
                object_values(item, child_context)
        elif isinstance(value, list):
            for item in value: object_values(item, context)
    for path in safe_files(business, databases=True):
        context = bool(re.search(r'product|catalog', path.stem, re.I))
        if path.suffix.lower() in {'.db', '.sqlite'}:
            db = _fox_person.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                    table_sql = '"' + table.replace('"', '""') + '"'
                    fields = [row[1] for row in db.execute('PRAGMA table_info(' + table_sql + ')')]
                    context_table = bool(re.search(r'product|variant|catalog|sku', table, re.I))
                    for key in fields:
                        reason = kind(key, context_table)
                        if reason:
                            column_sql = '"' + key.replace('"', '""') + '"'
                            for (value,) in db.execute('SELECT DISTINCT ' + column_sql + ' FROM ' + table_sql + ' WHERE ' + column_sql + ' IS NOT NULL'):
                                add(reason, value)
            except sqlite3.Error as error:
                raise ValueError('A business database cannot be read; sweep refused.') from error
            finally:
                db.close()
            continue
        text = path.read_text(encoding='utf-8')
        money.update(match.group(0) for match in PATTERNS['money'].finditer(text))
        if path.suffix.lower() == '.json':
            try: object_values(json.loads(text), context)
            except json.JSONDecodeError: pass
        elif path.suffix.lower() == '.jsonl':
            for line in text.splitlines():
                try: object_values(json.loads(line), context)
                except json.JSONDecodeError: pass
        elif path.suffix.lower() == '.csv':
            for row in csv.DictReader(io.StringIO(text)):
                for key, value in row.items():
                    if key: add(kind(key, context), value)
        # Prose and schema examples are not product rows. Use product frontmatter and data tables.
        metadata = text.split('---', 2)[1] if text.startswith('---\n') and len(text.split('---', 2)) == 3 else ''
        product_note = bool(re.search(r'^type:\s*["\']?(?:product|sku|brand)["\']?\s*$', metadata, re.M))
        if product_note or context:
            for match in re.finditer(r'^\s*([A-Za-z][A-Za-z _-]{0,35}):\s*([^\n]+)', metadata, re.M):
                add(kind(match.group(1), product_note or context), match.group(2))
        lines = text.splitlines()
        for index, line in enumerate(lines[:-1]):
            if '|' not in line or not re.fullmatch(r'[\s|:-]+', lines[index + 1]): continue
            header = [cell.strip().strip(chr(96)+'*_') for cell in line.strip().strip('|').split('|')]
            if {re.sub(r'[^a-z]', '', cell.casefold()) for cell in header} & {'field', 'column', 'property', 'sqltype', 'fieldtype', 'storagetype'}:
                continue
            if not context and not any(kind(cell) in {'business-sku', 'business-brand'} for cell in header):
                continue
            kinds = [kind(cell, context) for cell in header]
            if not any(kinds): continue
            for body in lines[index + 2:]:
                cells = [cell.strip().strip(chr(96)+'*_') for cell in body.strip().strip('|').split('|')]
                if '|' not in body or len(cells) != len(header): break
                for field, reason, value in zip(header, kinds, cells):
                    # A numeric SKUs column is a count, not an identifier.
                    if field.casefold() == 'skus' and value.replace(',', '').isdigit():
                        continue
                    add(reason, value)
    return values, money

class ReferencePatterns(list):
    pass

def references(people, business):
    values, money = reference_values(people, business)
    expressions = ReferencePatterns()
    expressions.counts = {reason: len(names) for reason, names in values.items()}
    expressions.values = values
    for reason, names in sorted(values.items()):
        alternatives = []
        for name in sorted(names):
            parts = re.split(r'[\s_-]+', name)
            alternatives.append(r'[\s_-]+'.join(re.escape(part) for part in parts))
        if alternatives:
            expressions.append((reason, re.compile(r'(?<![\w])(?:' + '|'.join(alternatives) + r')(?![\w])', re.I)))
    return expressions, money, len(values['real-person'])

def text_views(raw):
    views = [raw.decode('latin-1'), raw.decode('utf-8', errors='replace')]
    if b'\0' in raw or raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        views.extend(raw.decode(codec, errors='replace') for codec in ('utf-16-le', 'utf-16-be'))
    result = set()
    for value in views:
        value = unicodedata.normalize('NFKC', value).replace('\0', '').replace('\\n', '\n').replace('\\r', '\n')
        lines = []
        for line in value.splitlines():
            if re.match(r'^\s*[A-Za-z_]\w*=\$\(', line):
                line = re.sub(r'"\$[0-9]"', '"POSITIONAL"', line)
            lines.append(line)
        result.add('\n'.join(lines))
    return result

def inspect_text(raw, label, expressions, money):
    reasons = set()
    for text in text_views(raw):
        for reason, expression in PATTERNS.items():
            if expression.search(text): reasons.add(reason)
        for reason, expression in expressions:
            if expression.search(text): reasons.add(reason)
        if any(value in text for value in money): reasons.add('business-money')
    return [{'path': label, 'line': 0, 'reason': reason} for reason in sorted(reasons)]

def safe_archive_name(value):
    path = PurePosixPath(value.rstrip('/'))
    if not value or path.is_absolute() or '..' in path.parts or path.as_posix() != value.rstrip('/') or '\\' in value:
        raise ValueError('Unsafe archive member path.')

def inspect_bytes(raw, label, expressions, money, depth=0, budget=None, name=''):
    if budget is None: budget = {'bytes': 0, 'members': 0}
    if len(raw) > MAX_BYTES or depth > MAX_DEPTH: raise ValueError('Archive or shipped file exceeds the scan limit.')
    budget['bytes'] += len(raw)
    if budget['bytes'] > MAX_EXPANDED_BYTES: raise ValueError('Expanded archive exceeds the scan limit.')
    findings = inspect_text(raw, label, expressions, money)
    lower = name.casefold()
    is_tar = (len(raw) >= 512 and raw[257:262] == b'ustar') or lower.endswith('.tar')
    if not is_tar and len(raw) >= 512:
        try:
            tarfile.TarInfo.frombuf(raw[:512], 'utf-8', 'surrogateescape')
            is_tar = True
        except tarfile.HeaderError:
            pass
    is_zip = not is_tar and (zipfile.is_zipfile(io.BytesIO(raw)) or raw.startswith((b'PK\x03\x04', b'PK\x05\x06')) or lower.endswith('.zip'))
    compression = ('gzip' if raw.startswith(b'\x1f\x8b') or lower.endswith(('.gz', '.tgz'))
                   else 'bzip2' if raw.startswith(b'BZh') or lower.endswith(('.bz2', '.tbz2'))
                   else 'xz' if raw.startswith(b'\xfd7zXZ\0') or lower.endswith(('.xz', '.txz')) else None)
    try:
        if is_zip:
            end = raw.rfind(b'PK\x05\x06')
            if end < 0 or end + 22 > len(raw) or end + 22 + int.from_bytes(raw[end+20:end+22], 'little') != len(raw):
                raise ValueError('ZIP trailing bytes or end record differ.')
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                findings += inspect_text(archive.comment, label+'!comment', expressions, money)
                ordered = sorted(archive.infolist(), key=lambda member: member.header_offset)
                prefix_end = ordered[0].header_offset if ordered else archive.start_dir
                if prefix_end < 0:
                    raise ValueError('ZIP member offset differs.')
                if prefix_end:
                    findings += inspect_bytes(raw[:prefix_end], label+'!prefix', expressions, money, depth+1, budget)
                for position, member in enumerate(ordered):
                    offset = member.header_offset
                    if raw[offset:offset+4] != b'PK\x03\x04':
                        raise ValueError('ZIP local header differs.')
                    header_size = 30 + int.from_bytes(raw[offset+26:offset+28], 'little') + int.from_bytes(raw[offset+28:offset+30], 'little')
                    content_end = offset + header_size + member.compress_size
                    next_offset = ordered[position+1].header_offset if position+1 < len(ordered) else archive.start_dir
                    descriptor = raw[content_end:next_offset]
                    if member.flag_bits & 8:
                        if descriptor.startswith(b'PK\x07\x08'): descriptor = descriptor[4:]
                        width = 8 if len(descriptor) == 20 else 4
                        if (len(descriptor) not in (12,20) or int.from_bytes(descriptor[:4], 'little') != member.CRC or
                            int.from_bytes(descriptor[4:4+width], 'little') != member.compress_size or
                            int.from_bytes(descriptor[4+width:], 'little') != member.file_size):
                            raise ValueError('ZIP data descriptor differs.')
                    elif content_end != next_offset:
                        raise ValueError('ZIP contains unlisted local bytes.')
                seen = set()
                for index, member in enumerate(archive.infolist(), 1):
                    budget['members'] += 1
                    if budget['members'] > MAX_MEMBERS or member.file_size > MAX_BYTES or member.flag_bits & 1:
                        raise ValueError('ZIP member is encrypted or exceeds the scan limit.')
                    if member.filename in seen: raise ValueError('Duplicate ZIP member.')
                    seen.add(member.filename)
                    safe_archive_name(member.filename)
                    member_label = label+'!member#'+str(index)
                    findings += inspect_text(member.filename.encode('utf-8')+member.comment+member.extra, member_label+':metadata', expressions, money)
                    if (member.external_attr >> 16) & 0o170000 == 0o120000: raise ValueError('Linked ZIP member.')
                    if not member.is_dir():
                        with archive.open(member) as handle: content = handle.read(MAX_BYTES+1)
                        if len(content) != member.file_size: raise ValueError('ZIP member size differs.')
                        findings += inspect_bytes(content, member_label, expressions, money, depth+1, budget, member.filename)
        elif is_tar:
            end = 0
            with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
                findings += inspect_text(json.dumps(archive.pax_headers, sort_keys=True).encode(), label+'!metadata', expressions, money)
                seen = set()
                for index, member in enumerate(archive, 1):
                    budget['members'] += 1
                    if budget['members'] > MAX_MEMBERS or member.size > MAX_BYTES: raise ValueError('TAR member exceeds the scan limit.')
                    if member.name in seen: raise ValueError('Duplicate TAR member.')
                    seen.add(member.name)
                    safe_archive_name(member.name)
                    member_label = label+'!member#'+str(index)
                    metadata = json.dumps({'name':member.name,'uname':member.uname,'gname':member.gname,'pax':member.pax_headers},sort_keys=True).encode()
                    findings += inspect_text(metadata, member_label+':metadata', expressions, money)
                    end = max(end, member.offset_data+((member.size+511)//512)*512)
                    if member.isdir(): continue
                    if not member.isfile() or member.issparse(): raise ValueError('Linked or unsupported TAR member.')
                    handle = archive.extractfile(member)
                    if handle is None: raise ValueError('Unreadable TAR member.')
                    with handle: content = handle.read(MAX_BYTES+1)
                    if len(content) != member.size: raise ValueError('TAR member size differs.')
                    findings += inspect_bytes(content, member_label, expressions, money, depth+1, budget, member.name)
            if len(raw)%512 or len(raw) < end+1024 or any(raw[end:]):
                findings.append({'path':label,'line':0,'reason':'archive-trailing-bytes'})
        elif compression:
            if compression == 'gzip':
                decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
                content = decoder.decompress(raw, MAX_BYTES+1)
            elif compression == 'bzip2':
                decoder = bz2.BZ2Decompressor()
                content = decoder.decompress(raw,max_length=MAX_BYTES+1)
            else:
                decoder = lzma.LZMADecompressor(memlimit=MAX_EXPANDED_BYTES)
                content = decoder.decompress(raw,max_length=MAX_BYTES+1)
            if len(content)>MAX_BYTES or not decoder.eof or decoder.unused_data:
                raise ValueError('Compressed archive is incomplete, has trailing bytes, or exceeds the scan limit.')
            findings += inspect_bytes(content,label+'!unpacked',expressions,money,depth+1,budget,name.removesuffix('.gz').removesuffix('.bz2').removesuffix('.xz'))
        elif (lower.endswith(('.7z','.rar','.zst','.zstd','.zipx','.lz4','.cab','.lz')) or
              raw.startswith((b'7z\xbc\xaf\x27\x1c', b'Rar!\x1a\x07', b'\x28\xb5\x2f\xfd', b'\x04\x22\x4d\x18', b'MSCF', b'LZIP'))):
            raise ValueError('Unsupported archive; sweep refused.')
    except (tarfile.TarError,zipfile.BadZipFile,RuntimeError,EOFError,OSError,zlib.error,lzma.LZMAError) as error:
        raise ValueError('Unreadable or unsupported archive; sweep refused.') from error
    return findings

def safe_path(root, relative):
    value = PurePosixPath(relative)
    if not relative or value.is_absolute() or '..' in value.parts or value.as_posix()!=relative or '\\' in relative:
        raise ValueError('Unsafe shipped path.')
    path = root.joinpath(*value.parts)
    for parent in [path,*path.parents]:
        if parent==root.parent: break
        if parent.is_symlink(): raise ValueError('Linked shipped path.')
    if not path.is_file() or PROTECTED.search(path.name): raise ValueError('Missing or protected shipped file.')
    if path.stat().st_size>MAX_BYTES: raise ValueError('Shipped file exceeds the scan limit.')
    return path

def canonical_archive(expected):
    output = io.BytesIO()
    with tarfile.open(fileobj=output,mode='w',format=tarfile.USTAR_FORMAT) as archive:
        for name,raw in sorted(expected.items()):
            member = tarfile.TarInfo(name)
            member.size=len(raw); member.mtime=0
            member.mode=0o755 if name.startswith('base/commands/') else 0o644
            archive.addfile(member,io.BytesIO(raw))
    return output.getvalue()

def sweep(root,manifest_path,people,business,loaded_references=None):
    root=root.resolve()
    if manifest_path.is_symlink() or manifest_path.stat().st_size>MAX_BYTES: raise ValueError('Linked or oversized manifest.')
    manifest_raw=manifest_path.read_bytes(); manifest=json.loads(manifest_raw); entries=manifest.get('files')
    if not isinstance(entries,list) or not entries: raise ValueError('The shipped file list is empty.')
    expressions,money,name_count=loaded_references or references(people,business)
    findings=inspect_bytes(manifest_raw,'manifest.json',expressions,money)
    expected={}
    for index,entry in enumerate(entries,1):
        path=safe_path(root,entry['path']); name=entry['archive_path']; safe_archive_name(name)
        if name.endswith('/') or name in expected: raise ValueError('Unsafe or duplicate archive path.')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256'] or len(raw)!=entry['bytes']: raise ValueError('Shipped file hash or length differs.')
        expected[name]=raw; label='shipped-file#'+str(index)
        findings+=inspect_text((entry['path']+'\n'+name).encode(),label+':name',expressions,money)
        findings+=inspect_bytes(raw,label,expressions,money,name=name)
    bootstrap=manifest.get('bootstrap')
    if not bootstrap: raise ValueError('Bootstrap is absent from the shipped file list.')
    raw=safe_path(root,bootstrap['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=bootstrap['sha256'] or len(raw)!=bootstrap['bytes']: raise ValueError('Bootstrap hash or length differs.')
    findings+=inspect_text(bootstrap['path'].encode(),'bootstrap:name',expressions,money)
    findings+=inspect_bytes(raw,'bootstrap',expressions,money,name=bootstrap['path'])
    archive_relative=manifest['archive']['url']
    if PurePosixPath(archive_relative).name!=archive_relative or '\\' in archive_relative: raise ValueError('Archive must be a local file beside the manifest.')
    archive_path=manifest_path.parent/archive_relative
    if archive_path.is_symlink() or archive_path.stat().st_size>MAX_BYTES: raise ValueError('Linked or oversized archive.')
    raw_archive=archive_path.read_bytes()
    if hashlib.sha256(raw_archive).hexdigest()!=manifest['archive']['sha256'] or len(raw_archive)!=manifest['archive']['bytes']: raise ValueError('Archive hash or length differs.')
    findings+=inspect_text(archive_relative.encode(),'release-archive:name',expressions,money)
    findings+=inspect_bytes(raw_archive,'release-archive',expressions,money,name=archive_relative)
    if raw_archive!=canonical_archive(expected): findings.append({'path':'release-archive','line':0,'reason':'archive-not-canonical'})
    unique=sorted({(f['path'],f['line'],f['reason']) for f in findings})
    counts=getattr(expressions,'counts',Counter(reason for reason,_ in expressions))
    return {'result':'FAIL' if unique else 'PASS','files':len(entries)+3,'real_person_names_checked':name_count,
            'private_reference_counts':dict(sorted(counts.items())),
            'findings':[{'path':path,'line':line,'reason':reason} for path,line,reason in unique]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path); p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--people',type=Path,required=True); p.add_argument('--business',type=Path,required=True)
    args=p.parse_args()
    try: report=sweep(args.root,args.manifest,args.people,args.business)
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as error:
        print('FAIL privacy sweep: input, archive, or scan boundary refused ('+type(error).__name__+')')
        return 1
    for finding in report['findings']: print('FAIL '+finding['path']+' '+finding['reason'])
    print(report['result']+' privacy sweep: '+str(report['files'])+' byte-scanned inputs; '+str(len(report['findings']))+' findings')
    return 1 if report['findings'] else 0

if __name__=='__main__': raise SystemExit(main())
