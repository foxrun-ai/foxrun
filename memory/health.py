#!/usr/bin/env python3
"""Independent health from dream receipts and lead beats. Database access is not needed."""
from datetime import timedelta
import json
import os
import re
from base import paths, person
from base.tracker import local_path
from memory import state


def beat(seat):
    if not isinstance(seat, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', seat):
        raise ValueError('beat needs a seat id')
    target = local_path(paths.system_home(), 'runs/lead-beats/'+seat+'.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    state.write_once(target, json.dumps({'seat':seat,'at':state.stamp(state.now()),'pid':os.getpid()})+'\n')


def read_object(file):
    value = json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('JSON must be an object')
    return value


def time_value(value):
    if value is not None and not isinstance(value, str):
        raise ValueError('time must be text')
    return state.parse_when(value)


def roster(home):
    """The leads health watches: the standing seats, then the leads in config/person.json."""
    file = local_path(home, 'config/standing-seats.json')
    seats = list(read_object(file).get('seats', {})) if file.is_file() else []
    seats += [seat for seat in person.leads() if seat not in seats]
    if any(not isinstance(seat, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', seat) for seat in seats):
        raise ValueError('lead roster needs seat ids')
    return tuple(seats)


def check_health(write=True):
    home = paths.system_home()
    moment = state.now()
    errors = []
    interval = 86400
    try:
        settings_file = local_path(home, 'config/dream.json')
        settings = read_object(settings_file) if settings_file.is_file() else {}
        interval = settings.get('interval_seconds') or 86400
        if type(interval) is not int or interval < 60:
            raise ValueError('invalid interval')
    except (OSError, ValueError, TypeError):
        interval = 86400
        errors.append('invalid dream settings')
    grace = max(3600, interval//4)
    runs = local_path(home, 'runs')
    found = []
    from memory.runs import nightly_folders
    # T755: dream folders live in runs/nightly/; older ones at the top of runs/ still count.
    for candidate in [folder / 'manifest.json' for folder in nightly_folders(home, '*-dream*')
                      if (folder / 'manifest.json').is_file()]:
        try:
            file = local_path(home, str(candidate.relative_to(home)))
            value = read_object(file)
            if value.get('job') != 'dream' or value.get('word') != 'run':
                continue
            at, exact = time_value(value.get('started_at'))
            ended, _ = time_value(value.get('finished_at'))
            if at is None or not exact:
                raise ValueError('manifest has no start time')
            if 'model_half' in value and not isinstance(value['model_half'], dict):
                raise ValueError('invalid model half')
            if 'code_half' in value and not isinstance(value['code_half'], dict):
                raise ValueError('invalid code half')
            found.append((at, file.stat().st_mtime_ns, str(file), value))
        except (OSError, ValueError, TypeError):
            errors.append('invalid dream manifest: '+candidate.parent.name)
    latest = max(found, default=None, key=lambda row:(row[0],row[1],row[2]))
    job = {'last_started_at':None,'last_finished_at':None,'finished':False,
           'result':None,'stale':True,'manifest':None,'model':None,'code_half':None,'model_half':None}
    if latest:
        at, _, file, value = latest
        ended, exact = time_value(value.get('finished_at'))
        finished = ended is not None and exact and ended >= at and value.get('result') in ('pass','fail')
        job.update(last_started_at=value['started_at'], last_finished_at=value.get('finished_at'),
                   finished=finished,result=value.get('result'),stale=moment-at > timedelta(seconds=interval+grace),
                   manifest=file,model=value.get('model'),code_half=value.get('code_half'),model_half=value.get('model_half'))
    leads = {}
    try:
        seats = roster(home)
    except (OSError, ValueError, TypeError):
        seats = ()
        errors.append('invalid lead roster')
    for seat in seats:
        try:
            file = local_path(home, 'runs/lead-beats/'+seat+'.json')
            value = read_object(file) if file.is_file() else {}
            if value and value.get('seat') != seat:
                raise ValueError('beat seat mismatch')
            at, _ = time_value(value.get('at'))
            leads[seat] = {'last_beat':value.get('at'), 'signal':'start or explicit beat',
                           'stale':at is None or moment-at > timedelta(seconds=interval+grace)}
        except (OSError, ValueError, TypeError):
            leads[seat] = {'last_beat':None,'signal':'invalid','stale':True}
            errors.append('invalid lead beat: '+seat)
    failed = bool(errors) or not job['finished'] or job['stale'] or job['result'] != 'pass'
    data = {'checked_at':state.stamp(moment),'dream':job,'leads':leads,
            'errors':errors,'ok':not failed,'lead_beats_ok':bool(leads) and all(not row['stale'] for row in leads.values())}
    if write:
        state.write_once(local_path(home, 'health.json'),json.dumps(data,indent=2,sort_keys=True)+'\n')
    print('Health: dream '+('pass' if not failed else 'fail')+'; '+str(sum(row['last_beat'] is not None for row in leads.values()))+' lead beats recorded')
    return int(failed)
