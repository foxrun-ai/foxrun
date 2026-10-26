#!/usr/bin/env python3
"""Recover workspace, seat, and function from an ordinary or native session payload."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('FOXRUN_HOME',str(ROOT))
from base import paths
from memory.start_context import session_context


def recover(workspace=None, function=None, seat=None, run_dir=None, hook=None, session=None):
    from foxrun import workspace_name
    data = hook or {}
    if isinstance(data.get('data'),dict):
        data=data['data']
    if not workspace and isinstance(data.get('cwd'),str):
        try:
            relative=Path(data['cwd']).resolve().relative_to(paths.portfolio())
            if relative.parts:
                workspace=relative.parts[0]
        except ValueError:
            pass
    workspace=workspace_name(workspace)
    session=session or data.get('session_id') or data.get('thread_id') or data.get('sessionId') or os.environ.get('FOXRUN_SESSION')
    context={}
    if isinstance(session,str) and session:
        os.environ['FOXRUN_SESSION']=session
        context=session_context(workspace,session)
    function=function or os.environ.get('FOXRUN_FUNCTION') or data.get('function') or context.get('function')
    seat=seat or os.environ.get('FOXRUN_SEAT') or data.get('seat') or context.get('seat')
    run_dir=run_dir or os.environ.get('FOXRUN_RUN_DIR')
    return workspace,function,seat,run_dir


def start():
    from foxrun import main
    arguments=list(sys.argv[1:])
    payload=sys.stdin.read() if not sys.stdin.isatty() else ''
    try:
        data=json.loads(payload) if payload.strip() else {}
        if not isinstance(data,dict):
            data={}
    except ValueError:
        data={}
    if data.get('hook_event_name')=='pre_llm_call':
        # Hermes shell hook: it fires every turn; only the first turn gets the start page, as context.
        if not (data.get('extra') or {}).get('is_first_turn'):
            print('{}')
            return 0
        from contextlib import redirect_stdout
        from io import StringIO
        output=StringIO()
        with redirect_stdout(output):
            result=run_start(main,arguments,data)
        print(json.dumps({'context':output.getvalue()}) if result==0 else '{}')
        return 0
    return run_start(main,arguments,data)


def run_start(main,arguments,data):
    values={}
    for index,arg in enumerate(arguments):
        for name in ('workspace','function','seat','run-dir'):
            flag='--'+name
            if arg.startswith(flag+'='):
                values[name]=arg.split('=',1)[1]
            elif arg==flag and index+1<len(arguments):
                values[name]=arguments[index+1]
    resolved=recover(values.get('workspace'),values.get('function'),values.get('seat'),values.get('run-dir'),data)
    for name,value in zip(('workspace','function','seat','run-dir'),resolved):
        if name not in values and value:
            arguments+=['--'+name,value]
    return main(['start']+arguments)


if __name__=='__main__':
    raise SystemExit(start())
