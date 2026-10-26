"""The configured person who owns one installation. Standard library only."""
import json
import os
from pathlib import Path
import re
import sqlite3
from base import paths

DEFAULT_LEADS = ('architect', 'chief-of-staff')
_RAW_CONNECT = sqlite3.connect


class PersonError(ValueError):
    pass


def configuration():
    file = paths.system_home() / 'config/person.json'
    if not file.exists():
        return {}
    if file.is_symlink():
        raise PersonError('config/person.json must not be a symbolic link')
    data = json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise PersonError('config/person.json must contain a JSON object')
    return data


def name():
    value = os.environ.get('FOXRUN_PERSON') or configuration().get('name')
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', value):
        raise PersonError('Set FOXRUN_PERSON to your name, or write {"name": "your-name"} in ' +
                          str(paths.system_home() / 'config/person.json'))
    return value


def display_name():
    return name().capitalize()


def leads():
    seats = configuration().get('leads', list(DEFAULT_LEADS))
    if not isinstance(seats, list) or not seats or any(
            not isinstance(s, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', s) for s in seats):
        raise PersonError('config/person.json leads must be a non-empty list of seat names')
    return tuple(seats)


def sql_literal(value):
    return "'" + value.replace("'", "''") + "'"


def workspace(role='default'):
    config = configuration()
    roster = configured_workspaces() or []
    fallback = roster[0] if roster else 'workspace'
    value = config.get(role + '_workspace', config.get('default_workspace', fallback))
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9-]+', value):
        raise PersonError(role + '_workspace must be a workspace id')
    return value


def workspace_setting(workspace_id, key, default=None):
    return configuration().get('workspace_settings', {}).get(workspace_id, {}).get(key, default)


def render_sql(sql):
    if '_workspace@' in sql:
        for role in ('system','shop','personal','career','venture','runtime'):
            token = '@' + role + '_workspace@'
            if token in sql:
                sql = sql.replace(token, workspace(role).replace("'", "''"))
    if '@import_' in sql:
        for key, value in configuration().get('import_marks', {}).items():
            sql = sql.replace('@import_' + key + '@', str(value).replace("'", "''"))

    """Materialize identity at schema creation; stored data remains unchanged."""
    if '@person@' in sql:
        # Only comparisons that already fold their left side fold the configured name.
        for match in reversed(list(re.finditer(r'\blower\s*\(', sql, re.I))):
            index = match.end()
            depth = 1
            while index < len(sql) and depth:
                if sql[index] == '(':
                    depth += 1
                elif sql[index] == ')':
                    depth -= 1
                index += 1
            right = re.match(r"(\s*(?:=|<>|!=)\s*)'@person@'", sql[index:])
            if right:
                start = index + len(right.group(1))
                sql = sql[:start] + "'@person_lower@'" + sql[index + right.end():]
        sql = sql.replace('@person_lower@', name().lower())
        sql = sql.replace("@person@", name())
    if '@Person@' in sql:
        sql = sql.replace("@Person@", display_name())
    return sql


def configure_values(value):
    if isinstance(value, dict):
        result = {k: configure_values(v) for k, v in value.items()}
        if result.get('column') in ('workspace', 'workspace_tags') or result.get('workspace_value_set'):
            configured = configured_workspaces()
            if configured is not None:
                if not isinstance(configured, list) or any(not isinstance(w, str) or not re.fullmatch(r'[a-z0-9-]+', w) for w in configured):
                    raise PersonError('config/person.json workspaces must be a list of workspace ids')
                result['allowed_values'] = (['base'] if result.get('workspace_value_set') else []) + configured + (['foxrun'] if result.get('workspace_scope') == 'portfolio' and 'foxrun' not in configured else [])
        return result
    if isinstance(value, list):
        return [configure_values(v) for v in value]
    if isinstance(value, str):
        if value == '@person@':
            return name()
        if value == '@Person@':
            return display_name()
        return render_sql(value)
    return value


def configured_workspaces():
    configured = configuration().get('workspaces')
    if configured is not None and (not isinstance(configured, list) or any(
            not isinstance(w, str) or not re.fullmatch(r'[a-z0-9-]+', w) for w in configured)):
        raise PersonError('config/person.json workspaces must be a list of workspace ids')
    return configured


def record_workspaces(db, workspaces):
    """Persist validated install input in the database-owned roster."""
    if not workspaces or any(not isinstance(w, str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,80}', w)
                             for w in workspaces) or len(workspaces) != len(set(workspaces)):
        raise PersonError('The install must supply unique workspace ids')
    db.execute('CREATE TABLE IF NOT EXISTS base_workspaces(id TEXT PRIMARY KEY)')
    db.executemany('INSERT OR IGNORE INTO base_workspaces(id) VALUES(?)', [(w,) for w in workspaces])


class Connection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configured = configured_workspaces()
        def workspace_allowed(value):
            if value is None:
                return 1  # NOT NULL is enforced separately where required.
            if configured is not None:
                return int(value in configured)
            # A database-owned roster is the alternate installation authority.
            for table in ('workspaces', 'base_workspaces'):
                if super(Connection, self).execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    return int(super(Connection, self).execute(
                        'SELECT 1 FROM "' + table + '" WHERE id=?', (value,)).fetchone() is not None)
            return 0
        self.create_function('foxrun_workspace_allowed', 1, workspace_allowed)
        self.create_function('foxrun_workspace_allowed', 2,
                             lambda value, portfolio: int(bool(portfolio) and value == 'foxrun') or workspace_allowed(value))

    def execute(self, sql, parameters=()):
        return super().execute(render_sql(sql), parameters)

    def executemany(self, sql, parameters):
        return super().executemany(render_sql(sql), parameters)

    def executescript(self, sql):
        return super().executescript(render_sql(sql))


def connect(*args, **kwargs):
    kwargs.setdefault('factory', Connection)
    return _RAW_CONNECT(*args, **kwargs)


def install_configuration(system_home, person_name=None, lead_seats=None):
    """Create only; an existing owner's configuration always wins."""
    value = person_name or name()
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', value):
        raise PersonError('person name must be one name token')
    target = Path(system_home) / 'config/person.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        return False
    with target.open('x', encoding='utf-8') as stream:
        json.dump({'name': value, 'leads': list(lead_seats or DEFAULT_LEADS)}, stream, indent=2)
        stream.write('\n')
    return True


def private_terms():
    terms = configuration().get('private_terms', [])
    if not isinstance(terms, list) or any(not isinstance(t, str) or not t for t in terms):
        raise PersonError('config/person.json private_terms must be a list of names')
    return tuple(dict.fromkeys([name(), *terms]))
