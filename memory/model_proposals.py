#!/usr/bin/env python3
"""Select a tool-free inference adapter from models.yaml; keep its output only as proposals.

An adapter reads one JSON request on stdin and writes {"proposals": "Markdown"} on stdout.
The adapter is trusted installed transport code, never an interactive agent with file or database tools.
The adapter receives runtime and model names in the request. It receives no workspace paths or credentials.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from base.simple_yaml import safe_load
from base.tracker import local_path
from memory import state


def selection(home):
    file = local_path(home, 'config/models.yaml')
    config = safe_load(file.read_text()) if file.is_file() else {}
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError('models.yaml must be a map')
    dream = config.get('dream') or {}
    if not isinstance(dream, dict):
        raise ValueError('models.yaml dream must be a map')
    chosen = dream.get('model')
    if not chosen:
        return None
    rows = config.get('models', [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('models.yaml models must be a list of maps')
    matches = [row for row in rows if row.get('id') == chosen]
    if len(matches) != 1:
        raise ValueError('dream model must select exactly one model row')
    row = matches[0]
    if not row.get('runtime') or not row.get('adapter'):
        return None  # A model with no installed transport is not set up yet.
    if not all(isinstance(row.get(key), str) and row[key].strip() for key in ('runtime','model','adapter')):
        raise ValueError('runtime, model, and adapter must be text')
    for field in ('runtime','model'):
        if len(row[field]) > 200 or '\n' in row[field]:
            raise ValueError('invalid model setting')
    relative = row['adapter']
    if not relative.startswith('memory/adapters/') or not relative.endswith('.py'):
        raise ValueError('adapter must be installed Python transport under memory/adapters/')
    if any(part.lower() in {'.env','secrets','credentials','auth.json'} for part in Path(relative).parts):
        raise ValueError('protected adapter path')
    adapter = local_path(home, relative)
    if not adapter.is_file():
        return None
    return dict(row, adapter_path=adapter)


def adapter_output(chosen, request):
    # A transport gets an empty working folder and a small environment, with no agent tools or inherited auth.
    environment = {'PATH':os.defpath, 'PYTHONDONTWRITEBYTECODE':'1'}
    with tempfile.TemporaryDirectory(prefix='dream-inference-', dir=str(chosen['adapter_path'].parents[2]/'runs')) as folder:
        completed = subprocess.run([sys.executable, '-B', str(chosen['adapter_path'])],
                                   input=json.dumps(request), text=True, capture_output=True,
                                   cwd=folder, env=environment, timeout=120)
    if completed.returncode:
        raise ValueError('model adapter failed')  # Never copy transport stderr or auth messages into receipts.
    if len(completed.stdout.encode('utf-8')) > 1024*1024:
        raise ValueError('model output exceeds 1 MiB')
    result = json.loads(completed.stdout)
    if not isinstance(result, dict) or set(result) != {'proposals'} or not isinstance(result['proposals'], str):
        raise ValueError('adapter must return only a proposals string')
    if not result['proposals'].strip():
        raise ValueError('model proposals are empty')
    return result['proposals']


def model_half(home, date, steps, dry_run=False, adapter=None):
    result = {'state':'skipped-no-model','line':'skipped: no model','failures':[], 'proposal':None}
    try:
        chosen = selection(home)
        if chosen is None:
            return result
        result['runtime'], result['model'] = chosen['runtime'], chosen['model']
        if dry_run:
            result.update(state='not-run', line='dry run: model configured; not called')
            return result
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):
            raise ValueError('invalid proposal date')
        datetime.strptime(date,'%Y-%m-%d')
        path = local_path(home,'memory/proposals/'+date+'.md')
        if path.exists():
            if not path.is_file():
                raise ValueError('proposal path is not a file')
            result.update(state='kept',line='nightly proposals already exist; original kept',proposal=str(path.relative_to(home)))
            return result
        request = {'job':'dream', 'date':date, 'runtime':chosen['runtime'], 'model':chosen['model'],
                   'instructions':'Return proposed improvements for human review. You have no tools. Never apply a change.',
                   'code_half':[{'step':row['step'], 'result':row['result'], 'purpose':row['purpose']} for row in steps]}
        # All details are fixed step labels and outcomes. Raw transcripts, pages, rows, and secrets are never read here.
        content = (adapter or adapter_output)(chosen, request)
        if not isinstance(content,str) or not content.strip():
            raise ValueError('model proposals must be nonempty text')
        body = '# Dream proposals: '+date+'\n\nFor review. No page or row was changed by the model half.\n\n'+content.rstrip()+'\n'
        path.parent.mkdir(parents=True,exist_ok=True)
        # Atomic, exclusive publication: a second call never overwrites that night's file.
        fd, temporary = tempfile.mkstemp(prefix='.dream-proposals-',dir=str(path.parent))
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                stream.write(body);stream.flush();os.fsync(stream.fileno())
            os.chmod(temporary,0o444)
            try:
                os.link(temporary,str(path))
            except FileExistsError:
                result.update(state='kept',line='nightly proposals already exist; original kept',proposal=str(path.relative_to(home)))
                return result
        finally:
            os.unlink(temporary)
        result.update(state='pass',line='model wrote proposals for review',proposal=str(path.relative_to(home)))
    except (OSError,ValueError,TypeError,subprocess.SubprocessError):
        result.update(state='fail',line='model half failed; code half is kept',failures=['model adapter or configuration failed'])
    return result
