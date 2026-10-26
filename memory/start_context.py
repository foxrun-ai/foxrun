#!/usr/bin/env python3
"""Build fresh shared pages, the seat part, and the function part; record each start as one line (T755)."""
from contextlib import closing
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from base import paths, simple_yaml
from base.tracker import local_path, tracker
from memory import state

SEAT_LINES = 40  # the most lines of the seat part
CUT_NOTE = 'Cut to fit the start budget. Read the full file: '


def compact_state(text, limit, source=None):
    """Trim optional tables by section. Never remove Always, event counts, or question commands.

    When the required sections still exceed the limit: with a source, cut to the limit and end with
    one line that names the full file (the caller then does not advance that marker); without one, raise.
    """
    blocks = []
    for line in text.rstrip().splitlines():
        if line.startswith('## ') or not blocks:
            blocks.append([])
        blocks[-1].append(line)

    def joined():
        return '\n\n'.join('\n'.join(block).strip('\n') for block in blocks)

    if len(joined().splitlines()) <= limit:
        return joined()
    # Open has aggregate counts above it. The newest individual review rows are optional.
    for index, block in enumerate(blocks):
        if block[0] == '## Open':
            cut = next((n for n,line in enumerate(block)
                        if re.match(r'\d+ tasks? (?:are|is) in review\.', line)), len(block))
            blocks[index] = block[:cut]
    if len(joined().splitlines()) <= limit:
        return joined()
    # Keep every exact event count and unknown-order warning; remove only the decision examples.
    for index, block in enumerate(blocks):
        if block[0].startswith('## New since '):
            blocks[index] = [line for line in block if not line.startswith('|')]
    if len(joined().splitlines()) <= limit:
        return joined()
    for index, block in enumerate(blocks):
        if block[0] == '## Open':
            blocks[index] = ['## Open', '', 'Open totals appear above. Read the question commands below for details.']
    if len(joined().splitlines()) <= limit:
        return joined()
    # The printed context can omit generated-file metadata. STATE.md itself keeps that metadata.
    prefix = blocks[0]
    if prefix and prefix[0] == '---':
        close = prefix.index('---', 1)
        blocks[0] = prefix[close+1:]
    if len(joined().splitlines()) > limit:
        if source is None:
            raise ValueError('required state sections exceed the start budget; markers were not advanced')
        kept = joined().splitlines()[:max(limit, 1)-1]
        while kept and not kept[-1].strip():
            kept.pop()
        return '\n'.join(kept+[CUT_NOTE+str(source)])
    return joined()


def context_state(scope, moment, since, seat):
    text = state.render(scope, moment, since)
    if scope == 'system':
        facts = [state.scope_facts(tracker(name), name, since,
                 tracker(name).parent != paths.system_home(), exact=True) for name in state.workspaces()]
    else:
        facts = [state.scope_facts(tracker(scope), scope, since,
                 tracker(scope).parent != paths.system_home(), exact=True)]
    counts = [(label,sum(row[key] for row in facts)) for label,key in
              [('NEW TASKS','new_tasks'),('MOVED TO IN REVIEW','to_review'),('DECISIONS','decision_count'),('RUNS','runs')]]
    lines = ['## New since '+state.stamp(since),'',
             'This part shows exact event times since the previous work of '+seat+'.','']
    lines += state.count_block(counts)
    decisions = sorted({entry for row in facts for entry in row['decisions']}, key=lambda entry:entry[1] or '',reverse=True)[:5]
    if decisions:
        lines += ['','| Decision | Ruled |','|---|---|']
        lines += ['| '+state.clean(title,70)+' | '+(at or '')[:10]+' |' for title,at in decisions]
    unknown = sum(row['date_only'] for row in facts)
    if unknown:
        lines += ['','Rows with unknown order: '+str(unknown)]
    begin = text.index('## New since ')
    end = text.index('## Ask the rows',begin)
    return text[:begin]+'\n'.join(lines)+'\n\n'+text[end:]


def selected_tasks(workspace, function=None):
    database = tracker(workspace)
    with closing(state.readonly(database)) as db:
        if function:
            if not re.fullmatch(r'[a-z][a-z0-9_-]*', function):
                raise ValueError('invalid function id')
            if not state.has(db, 'functions') or not db.execute('SELECT 1 FROM functions WHERE id=?', (function,)).fetchone():
                raise ValueError('unknown function: '+function)
            if 'function' not in state.columns(db, 'tasks'):
                raise ValueError('tasks have no function column')
        rows = [dict(row) for row in db.execute('SELECT * FROM tasks ORDER BY id')]
        own = database.parent != paths.system_home()
        return [row for row in rows if (own or state.in_workspace(row, workspace, state.default_workspace()))
                and (not function or row.get('function') == function or
                     (isinstance(row.get('tags'), str) and 'ownership-alarm' in row['tags'].split(',')))]


def function_part(workspace, function, seat, moment, tasks, markers, named=True):
    key = seat+'|'+workspace+'|'+(function or '*')
    since, _ = state.parse_when(markers.get(key))
    ended, _ = state.last_run_end(tracker(workspace), seat, workspace,
                                  tracker(workspace).parent != paths.system_home())
    if not function and ended is not None and (since is None or ended > since):
        since = ended
    since = since or moment-timedelta(days=state.DAYS)
    ids = {row['id'] for row in tasks}
    events = 0
    unknown = []
    database = tracker(workspace)
    with closing(state.readonly(database)) as db:
        if state.has(db, 'activity'):
            for subject, at in db.execute("SELECT subject_id,at FROM activity WHERE subject_type='task'"):
                if subject in ids and state.newer(at, since, True, unknown):
                    events += 1
        quote = lambda value: "'"+str(value).replace("'", "''")+"'"
        command = "SELECT id,title,status FROM tasks t WHERE status NOT IN ('done','canceled','superseded')"
        if function:
            command += (' AND (function='+quote(function)+
                        " OR instr(','||replace(coalesce(tags,''),' ','')||',',',ownership-alarm,')>0)")
        if database.parent == paths.system_home():
            # Split tags as in in_workspace(): explicit workspace tags win; untagged rows use the default.
            split = ("WITH RECURSIVE tag_rows(task,tag,rest) AS ("
                     "SELECT id,'',coalesce(tags,'')||',' FROM tasks UNION ALL "
                     "SELECT task,trim(substr(rest,1,instr(rest,',')-1),char(9)||char(10)||char(11)||char(12)||char(13)||' '),"
                     "substr(rest,instr(rest,',')+1) FROM tag_rows WHERE rest<>'') ")
            tagged = "EXISTS(SELECT 1 FROM tag_rows WHERE task=t.id AND tag="+quote('workspace:'+workspace)+")"
            untagged = "NOT EXISTS(SELECT 1 FROM tag_rows WHERE task=t.id AND tag LIKE 'workspace:%')"
            command = split+command+' AND ('+tagged+' OR ('+untagged+' AND '+quote(workspace)+'='+quote(state.default_workspace())+'))'
        label = 'Function: '+function if function else 'Workspace tasks'
        lines = ['## '+label, 'Seat: '+(seat if named else 'none named'), 'New since: '+state.stamp(since),
                 'New task events: '+str(events), 'Events with unknown order: '+str(len(unknown)),
                 'Always: Keep money, sends, deletes, and production changes behind approval.', 'Open tasks:']
        opened = [row for row in tasks if row.get('status') not in state.CLOSED]
        from base import person
        def alarm_for_lead(row):
            tags = row.get('tags')
            return (isinstance(tags, str) and 'ownership-alarm' in tags.split(',') and
                    (row.get('owner') == seat or seat in person.leads()))
        opened.sort(key=lambda row: not alarm_for_lead(row))
        lines += ['  '+row['id']+': '+state.clean(row.get('title'), 70)+' ['+row['status']+']' for row in opened[:7]] or ['  none']
        if len(opened)>7:
            lines.append('  '+str(len(opened)-7)+' more tasks; use the command below.')
        lines += ['Question: What is open'+(' in '+function if function else '')+'?',
                  'Command: sqlite3 -readonly '+str(database)+' "'+command+';"']
        return '\n'.join(lines), key


def session_context(workspace, session):
    folder = local_path(paths.workspace(workspace), 'history/handoffs')
    matches = []
    for candidate in folder.glob('*.md'):
        path = local_path(folder, candidate.name)
        if not path.is_file() or path.name.endswith('.coverage.md'):
            continue
        text = path.read_text(encoding='utf-8')
        if not text.startswith('---\n') or '\n---\n' not in text[4:]:
            continue
        metadata = dict(line.split(':', 1) for line in text.split('\n---\n',1)[0][4:].splitlines() if ':' in line)
        metadata = {key:value.strip().strip('"\'') for key,value in metadata.items()}
        if metadata.get('session') == session:
            matches.append((path.stat().st_mtime_ns, path.name, metadata))
    context = {}
    records = []
    # T755: one line per start in runs/<date>/sessions.jsonl; the older start folders stay readable at depth 1.
    from memory import runs as run_home
    for index, value in enumerate(run_home.sessions()):
        if value.get('workspace') == workspace and value.get('session') == session:
            records.append((str(value.get('at') or ''), index, value))
    folder_runs = local_path(paths.system_home(), 'runs')
    for candidate in folder_runs.glob('*/start-context.json'):
        try:
            path = local_path(folder_runs, str(candidate.relative_to(folder_runs)))
            value = json.loads(path.read_text())
            if isinstance(value, dict) and value.get('workspace') == workspace and value.get('session') == session:
                records.append((state.stamp(datetime.fromtimestamp(path.stat().st_mtime).astimezone()), -1, value))
        except (OSError, ValueError, TypeError):
            continue
    if records:
        newest = max(records, key=lambda row: (row[0], row[1]))[2]
        context.update({key: newest.get(key) for key in ('workspace', 'seat', 'function', 'session')})
    if matches:
        context.update(max(matches)[2])
    return context


def seat_file(workspace, seat):
    """Use the shared resolver, retaining the workspace team's priority."""
    return paths.resolve_seat(seat, workspace_root=paths.workspace(workspace))

def seat_part(workspace, seat):
    """The seat's summary and its Judgment section, at most SEAT_LINES lines. One line when no file."""
    if not seat:
        return 'No seat named.'
    path = seat_file(workspace, seat)
    if path is None:
        return 'Seat '+seat+': no seat file (agents/'+seat+'.md, '+workspace+'/team/'+seat+'.md).'
    text = path.read_text(encoding='utf-8')
    meta, body = {}, text
    if text.startswith('---\n') and '\n---\n' in text[4:]:
        front, body = text[4:].split('\n---\n', 1)
        try:
            meta = simple_yaml.safe_load(front)
        except ValueError:
            meta = {}
        meta = meta if isinstance(meta, dict) else {}
    lines = ['## Seat: '+state.clean(meta.get('display_name') or seat, 60)+' ('+seat+')', 'File: '+str(path)]
    summary = meta.get('summary') or meta.get('role')
    if summary:
        lines.append('Summary: '+state.clean(summary, 240))
    judgment, inside = [], False
    for line in body.splitlines():
        if re.match(r'#{1,3} ', line):
            if inside:
                break
            inside = line.strip() == '## Judgment'
            continue
        if inside:
            judgment.append(line.rstrip())
    while judgment and not judgment[0]:
        judgment.pop(0)
    while judgment and not judgment[-1]:
        judgment.pop()
    boot = re.search(r'^#{2,3} Boot reads$', body, re.M) is not None
    tail = ['Boot reads: under Boot reads in the file above. Run them before work.'] if boot else []
    if not judgment:
        return '\n'.join(lines+['Judgment: the file has no Judgment section.']+tail)
    room = SEAT_LINES-len(lines)-1-len(tail)
    if len(judgment) > room:
        rest = len(judgment)-(room-1)
        judgment = judgment[:room-1]+['('+str(rest)+' more lines under Judgment in the file above.)']
    return '\n'.join(lines+['Judgment:']+judgment+tail)


def handoff_part(workspace, seat, function, tasks):
    if not os.environ.get('FOXRUN_SESSION') and not any(row.get('status') not in state.CLOSED for row in tasks):
        return ''
    folder = local_path(paths.workspace(workspace), 'history/handoffs')
    candidates = []
    for candidate in folder.glob('*.md'):
        path = local_path(folder, candidate.name)
        if not path.is_file() or path.name.endswith('.coverage.md'):
            continue
        text = path.read_text(encoding='utf-8')
        metadata = {}
        if text.startswith('---\n') and '\n---\n' in text[4:]:
            metadata = dict(line.split(':', 1) for line in text.split('\n---\n',1)[0][4:].splitlines() if ':' in line)
            metadata = {key:value.strip().strip('"\'') for key,value in metadata.items()}
        session = os.environ.get('FOXRUN_SESSION')
        if session and metadata.get('session') != session:
            continue
        if not session and metadata.get('seat') and metadata['seat'] != seat:
            continue
        if not session and metadata.get('function') and metadata['function'] != function:
            continue
        candidates.append((path.stat().st_mtime_ns, path.name, path, text))
    if not candidates:
        return ''
    _, _, path, text = max(candidates)
    # A blank last kept line would end the part with a newline and add a line past the 200-line budget.
    return ('## Last handoff: '+str(path)+'\n'+'\n'.join(text.splitlines()[:20])).rstrip('\n')


def start_context(workspace, function=None, seat=None, run_dir=None, native_context=None):
    named = seat or os.environ.get('FOXRUN_SEAT')
    seat = named or 'worker'  # The run folder and markers keep one id; the page says no seat was named.
    if not re.fullmatch(r'[a-z][a-z0-9_-]*', seat):
        raise ValueError('invalid seat id')
    moment = state.now()
    tasks = selected_tasks(workspace, function)
    home = paths.system_home()
    runs = local_path(home, 'runs')
    marker_path = local_path(home, 'runs/state-markers.json')
    runs.mkdir(parents=True, exist_ok=True)
    if run_dir:
        value = Path(run_dir).expanduser()
        if not value.is_absolute():
            value = home/value
        value.relative_to(runs)
        folder = local_path(home, str(value.relative_to(home)))
        folder.mkdir(parents=True, exist_ok=True)
        if (folder/'start-page.md').exists():
            # Compaction gets a new copy and never destroys the previous start output.
            folder = Path(tempfile.mkdtemp(prefix='compact-', dir=str(folder)))
    else:
        # T755: a session start is one line in runs/<date>/sessions.jsonl, not a folder.
        folder = None
    lock = local_path(home, 'runs/.state-markers.json.lock')
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise ValueError('another start writes markers; retry after it ends')
    os.close(descriptor)
    try:
        markers = state.read_markers()
        fresh = [state.render('system',moment), state.render(workspace,moment)]
        function_key = function or '*'
        specific = []
        for scope in ('system', workspace):
            since, _ = state.parse_when(markers.get(seat+'|'+scope+'|'+function_key))
            since = since or moment-timedelta(days=state.DAYS)
            text = context_state(scope,moment,since,seat)
            specific.append(text)
        # The shared pages hold rows for every reader. The function part stays only in this run.
        targets = [local_path(home, 'STATE.md'), local_path(paths.workspace(workspace),'STATE.md')]
        for target, text in zip(targets,fresh):
            state.write_once(target,text)
        function_text, key = function_part(workspace,function,seat,moment,tasks,markers,bool(named))
        handoff = handoff_part(workspace,seat,function,tasks)
        name = state.person_name()
        identity = 'Person: '+name+'\nWorkspace: '+workspace
        # A native seat start already prints the whole identity file; the seat part would repeat it.
        seat_text = None if native_context else seat_part(workspace, named)
        from base.agent_catalog import model_policy
        policy = model_policy(home)
        model_lines = ['Models: ' + str(home / 'config/models.yaml')]
        for tier, runtimes in policy['tiers'].items():
            model_lines.append(tier + ': ' + ', '.join(runtime + '=' + entry['model']
                               for runtime, entry in runtimes.items() if entry))
        model_lines += ['Allowed: ' + ', '.join(policy['allowed']), 'Banned: ' + ', '.join(policy['banned'])]
        head = [identity, '\n'.join(model_lines)] + ([seat_text] if seat_text else [])
        # T260: the lessons every agent reads, from the system data.db (memory/lessons.py, at most 16 lines).
        from memory.lessons import start_part as lessons_part
        lessons_text = lessons_part(local_path(home, 'data.db'), workspace, named)
        head += [lessons_text] if lessons_text else []
        fixed = head + [function_text] + ([handoff] if handoff else [])
        # Reserve the complete function command and exact handoff before allocating shared sections.
        shared_budget = 200 - sum(len(part.splitlines()) for part in fixed) - (len(fixed)+1)
        def shared_parts(budget, cut=False):
            system_budget = budget//2
            return [compact_state(specific[0],system_budget,targets[0] if cut else None),
                    compact_state(specific[1],budget-system_budget,targets[1] if cut else None)]
        shared = None
        if native_context:
            native_budget = shared_budget-len(native_context.rstrip().splitlines())-1
            if native_budget > 0:
                try:
                    shared = shared_parts(native_budget)
                except ValueError:
                    # A long required seat identity must not disable the installed native start.
                    pass
        # A state section that still does not fit is cut with a pointer to its STATE.md; start never fails here.
        shared = shared or shared_parts(shared_budget, cut=True)
        cut = [part.splitlines()[-1].startswith(CUT_NOTE) for part in shared]
        text = '\n\n'.join(head+shared+[function_text]
                            + ([handoff] if handoff else []))+'\n'
        # 2026-10-24, B-20261023-start-page-201-lines-blank-handoff-line: the 200-line budget is soft. The page always prints; over budget it ends with a warning.
        size = len(text.splitlines())
        if size>200:
            text += 'Warning: start page is {} lines, over the 200-line budget.\n'.format(size)
        if native_context:
            # Keep the bound identity and Boot reads intact beside the bounded memory readout.
            text = native_context.rstrip()+'\n\n'+text
        record = {'workspace':workspace, 'seat':named, 'function':function, 'session':os.environ.get('FOXRUN_SESSION'),
                  'lines':len(text.splitlines())}
        if folder is not None:
            state.write_once(folder/'start-page.md',text)
            state.write_once(folder/'start-context.json',json.dumps({key:record[key] for key in
                             ('workspace','seat','function','session')})+'\n')
            record['run_dir'] = str(folder)
        from memory import runs as run_home
        run_home.record_session(record, moment=moment)
        # Advance a marker only for a state part that printed in full; a cut part shows again next start.
        if not cut[1]:
            markers[key] = state.stamp(moment)
        if not cut[0]:
            markers[seat+'|system|'+function_key] = state.stamp(moment)
        state.write_once(marker_path,json.dumps(markers,indent=2,sort_keys=True)+'\n')
        # The check reads this signal without depending on the database.
        from memory.health import beat
        beat(seat)
        sys.stdout.write(text)
    finally:
        lock.unlink()
    return 0
