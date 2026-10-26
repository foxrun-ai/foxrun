#!/usr/bin/env python3
"""Install Foxrun into two empty folders. Standard library only."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time

# The hook merge ships in the home, so `foxrun.py hookup` can rerun it on an existing install.
from base.hookup import (codex_event_key, codex_hook_hash, codex_trust, connect,  # noqa: F401
                         hermes_entries, hermes_hookup, hook_entries)

# Frozen made-at-install rows from the product target; table rows describe SQLite objects.
MADE_TSV = """home\tpath\tkind
portfolio	.	folder
portfolio	<workspace>/	folder
portfolio	<workspace>/AGENTS.md	file
portfolio	<workspace>/CLAUDE.md	file
portfolio	<workspace>/GLOSSARY.md	file
portfolio	<workspace>/RESOLVER.md	file
portfolio	<workspace>/STATE.md	file
portfolio	<workspace>/config/	folder
portfolio	<workspace>/history/	folder
portfolio	<workspace>/history/LOG.md	file
portfolio	<workspace>/history/daily/	folder
portfolio	<workspace>/history/handoffs/	folder
portfolio	<workspace>/history/outputs/	folder
portfolio	<workspace>/history/runs/	folder
portfolio	<workspace>/history/snapshots/	folder
portfolio	<workspace>/index.md	file
portfolio	<workspace>/notes/	folder
portfolio	<workspace>/ops/	folder
portfolio	<workspace>/ops/DASHBOARD.md	file
portfolio	<workspace>/ops/decisions.md	file
portfolio	<workspace>/ops/functions/	folder
portfolio	<workspace>/ops/goals.md	file
portfolio	<workspace>/ops/issues.md	file
portfolio	<workspace>/ops/measures.md	file
portfolio	<workspace>/ops/programs.md	file
portfolio	<workspace>/ops/streams.md	file
portfolio	<workspace>/ops/tasks.md	file
portfolio	<workspace>/raw/	folder
portfolio	<workspace>/raw/articles/	folder
portfolio	<workspace>/raw/decks/	folder
portfolio	<workspace>/raw/documents/	folder
portfolio	<workspace>/raw/exports/	folder
portfolio	<workspace>/raw/github/	folder
portfolio	<workspace>/raw/images/	folder
portfolio	<workspace>/raw/instagram/	folder
portfolio	<workspace>/raw/reddit/	folder
portfolio	<workspace>/raw/spreadsheets/	folder
portfolio	<workspace>/raw/transcripts/	folder
portfolio	<workspace>/raw/video/	folder
portfolio	<workspace>/raw/x/	folder
portfolio	<workspace>/raw/youtube/	folder
portfolio	<workspace>/skills/	folder
portfolio	<workspace>/specs/	folder
portfolio	<workspace>/src/	folder
portfolio	<workspace>/team/	folder
portfolio	<workspace>/team/TEAM.md	file
portfolio	<workspace>/tools/	folder
portfolio	<workspace>/tools/CAPABILITIES.md	file
portfolio	<workspace>/tools/cli/	folder
portfolio	<workspace>/tools/external-app/	folder
portfolio	<workspace>/tools/mcp/	folder
portfolio	<workspace>/tools/plugin/	folder
portfolio	<workspace>/tools/schedule/	folder
portfolio	<workspace>/tools/service/	folder
portfolio	<workspace>/wiki/	folder
portfolio	<workspace>/wiki/SCHEMA.md	file
portfolio	<workspace>/wiki/TOPICS.md	file
portfolio	<workspace>/wiki/comparisons/	folder
portfolio	<workspace>/wiki/concepts/	folder
portfolio	<workspace>/wiki/entities/	folder
portfolio	<workspace>/wiki/queries/	folder
portfolio	AGENTS.md	file
portfolio	CLAUDE.md	file
portfolio	atlas/	folder
portfolio	atlas/AGENTS.md	file
portfolio	atlas/CLAUDE.md	file
portfolio	atlas/GLOSSARY.md	file
portfolio	atlas/LIBRARY.md	file
portfolio	atlas/SCHEMA.md	file
portfolio	atlas/TOPICS.md	file
portfolio	atlas/RESOLVER.md	file
portfolio	atlas/STATE.md	file
portfolio	atlas/index.md	file
portfolio	atlas/comparisons/	folder
portfolio	atlas/concepts/	folder
portfolio	atlas/config/	folder
portfolio	atlas/config/glossary-tags.json	file
portfolio	atlas/entities/	folder
portfolio	atlas/history/	folder
portfolio	atlas/history/LOG.md	file
portfolio	atlas/history/daily/	folder
portfolio	atlas/history/daily/.gitkeep	file
portfolio	atlas/history/handoffs/	folder
portfolio	atlas/history/handoffs/.gitkeep	file
portfolio	atlas/history/outputs/	folder
portfolio	atlas/history/outputs/.gitkeep	file
portfolio	atlas/history/runs/	folder
portfolio	atlas/history/runs/.gitkeep	file
portfolio	atlas/queries/	folder
portfolio	atlas/raw/	folder
portfolio	atlas/raw/articles/	folder
portfolio	atlas/raw/decks/	folder
portfolio	atlas/raw/documents/	folder
portfolio	atlas/raw/exports/	folder
portfolio	atlas/raw/github/	folder
portfolio	atlas/raw/images/	folder
portfolio	atlas/raw/instagram/	folder
portfolio	atlas/raw/reddit/	folder
portfolio	atlas/raw/spreadsheets/	folder
portfolio	atlas/raw/transcripts/	folder
portfolio	atlas/raw/video/	folder
portfolio	atlas/raw/x/	folder
portfolio	atlas/raw/youtube/	folder
portfolio	index.md	file
system	.	folder
system	STATE.md	file
system	agents/generated/	folder
system	agents/tools/	folder
system	archive/	folder
system	backups/	folder
system	backups/jsonl/	folder
system	config/	folder
system	config/catalog.yaml	file
system	config/models.yaml	file
system	config/modules.yaml	file
system	config/squads/	folder
system	config/tools.yaml	file
system	cron/	folder
system	cron/launchd/	folder
system	data.db/	database
system	data.db/base/	table-group
system	data.db/base/base_capabilities	table
system	data.db/base/base_fields	table
system	data.db/base/installed_modules	table
system	data.db/base/base_installs	table
system	data.db/base/module_install_activity	table
system	data.db/base/base_modules	table
system	data.db/base/base_object_types	table
system	data.db/base/base_pages	table
system	data.db/base/base_values	table
system	data.db/decisions/	table-group
system	data.db/decisions/decisions	table
system	data.db/decisions/approvals	table
system	data.db/events/	table-group
system	data.db/events/attachments	table
system	data.db/events/activity	table
system	data.db/events/comments	table
system	data.db/events/runs	table
system	data.db/memory/	table-group
system	data.db/memory/lessons	table
system	data.db/work/	table-group
system	data.db/work/work_bugs	table
system	data.db/work/work_functions	table
system	data.db/work/work_goals	table
system	data.db/work/work_incidents	table
system	data.db/work/work_links	table
system	data.db/work/work_measure_history	table
system	data.db/work/work_measures	table
system	data.db/work/work_programs	table
system	data.db/work/work_projects	table
system	data.db/work/task_links	table
system	data.db/work/work_tasks	table
system	data.db/work/work_themes	table
system	evals/	folder
system	evals/agents/	folder
system	evals/memory/	folder
system	health.json	file
system	modules/	folder
system	profile/	folder
system	raw/	folder
system	runs/	folder
system	skills/	folder
system	state/	folder
system	skillwright/manifests/	folder
system	skillwright/retired/	folder
system	skillwright/skill-releases/	folder
system	skillwright/skill-state/	folder
system	skillwright/skills/	folder
system	skillwright/workflows/	folder
system	tools/	folder
system	tools/CAPABILITIES.md	file
system	tools/cli/	folder
system	tools/external-app/	folder
system	tools/mcp/	folder
system	tools/plugin/	folder
system	tools/schedule/	folder
system	tools/service/	folder
system	wiki/	folder
system	wiki/concepts/	folder
system	wiki/entities/	folder
"""
PERSON = re.compile(r'[A-Za-z][A-Za-z0-9_-]*\Z')
WORKSPACE = re.compile(r'[a-z0-9-]+\Z')


def made_rows():
    return list(csv.DictReader(io.StringIO(MADE_TSV), delimiter='\t'))


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def destination(raw, label, tree, empty=True):
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(label + ' must be an absolute path')
    # Reject user-selected links, including parent links. Resolve platform root aliases only.
    for part in [path, *path.parents]:
        if part.is_symlink() and str(part) not in ('/tmp', '/var', '/etc'):
            raise ValueError(label + ' must not cross a symlink: ' + str(part))
    path = path.resolve()
    if within(path, tree) or within(tree, path):
        raise ValueError(label + ' must not overlap the product tree')
    if path.exists() and not path.is_dir():
        raise ValueError(label + ' must be a folder')
    if empty and path.exists() and any(path.iterdir()):
        raise ValueError(label + ' exists and is not empty')
    return path


def ask(label, default, explanation, valid):
    print(explanation)
    value = input(label + ' [' + default + ']: ').strip() or default
    if not valid(value):
        raise ValueError('Invalid ' + label.lower())
    return value


def environment(home, portfolio, name):
    env = dict(os.environ)
    # An existing installation must not supply a different owner or state root.
    for key in list(env):
        if key.startswith('FOXRUN_'):
            del env[key]
    env.update(FOXRUN_HOME=str(home), FOXRUN_PORTFOLIO=str(portfolio),
               FOXRUN_STATE=str(home / 'runs'), FOXRUN_PERSON=name,
               FOXRUN_SEAT='chief-of-staff',
               PYTHONDONTWRITEBYTECODE='1')
    return env


def write_text(path, text):
    """Write generated UTF-8 text with LF newlines, including on Python 3.9."""
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


def run(code, home, env, arguments=()):
    result = subprocess.run([sys.executable, '-B', '-c', code, *map(str, arguments)],
                            cwd=str(home), env=env, text=True, capture_output=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or 'Product tool failed')
    return result.stdout


def shipped_packs(home):
    packs = []
    for path in sorted(home.glob('*/install.json')) + sorted(home.glob('modules/*/install.json')):
        if json.loads(path.read_text(encoding="utf-8")).get('ships') is not False:
            packs.append(path.parent.name)
    return sorted(set(packs))


# Person files: the product ships a blank copy once; they are in made-at-install.tsv, not product-manifest.tsv.
# config/git.md and config/gates.md ship (an update refreshes them); only their .local files are starters (approvals 422, 432).
# Approval 449 (T754): runner fixtures and their tests stay in source for build checks.
BUILD_ONLY = frozenset({
    'install.py', 'made-at-install.tsv', 'tests/test_fresh_install.py',
    # Optional scripts stay in the source package for manual setup, never in a fresh home.
    'tools/bin/ig-read', 'tools/bin/tweet-read', 'tools/bin/browser-humanize.js',
    'work/tests/fixtures/workflows/operate-amazon.yaml',
    'work/tests/fixtures/workflows/produce-ugc-ads.yaml',
    'work/tests/test_flow.py',
    'work/tests/fixtures/personal-workflows/vote.yaml',
    'work/tests/fixtures/personal-workflows/README.md',
    # T873: the uv package and the Claude and Codex plugin files serve the repository, never a fresh home.
    'pyproject.toml', 'packaging/hatch_build.py', 'packaging/foxrun_cli.py',
    '.claude-plugin/marketplace.json', '.agents/plugins/marketplace.json',
    'plugins/foxrun/.claude-plugin/plugin.json', 'plugins/foxrun/.codex-plugin/plugin.json',
    # T878: the GitHub issue templates serve the public repository, never a fresh home.
    '.github/ISSUE_TEMPLATE/bug_report.md', '.github/ISSUE_TEMPLATE/feature_request.md', '.github/ISSUE_TEMPLATE/config.yml',
    *('plugins/foxrun/skills/' + skill + '/' + name for skill, names in (
        ('foxrun-setup', ('SKILL.md', 'README.md', 'bin/setup')),
        ('thread', ('SKILL.md', 'README.md', 'bin/thread')),
        ('foxrun-help', ('SKILL.md', 'README.md', 'bin/ask-sources'))) for name in names),
})

STARTERS = ('agents/soul.md', 'config/gates.local.md', 'config/lint/business-names.tsv',
            'config/git.local.md', 'config/lint/workspaces.tsv', 'config/words.tsv',
            # The release record: the product's skill list starts it; then skill-ship writes it (T675).
            'skillwright/manifests/shipped.yaml',
            # Each Mac writes or keeps its own copy: its paths, names, and lint policy (T742; T630).
            'agents/execution/skills.yaml', 'capture/capture.config.json', 'config/lint/routes.tsv', 'config/lint/tools.tsv',
            'base/published/words.tsv', 'config/module-commands.json', 'config/lint/allowed-top.tsv',
            'config/lint/brand.tsv', 'config/lint/db.tsv', 'config/lint/db-reasons.tsv', 'config/lint/required-pages.tsv',
            'config/lint/spec-changes.tsv', 'config/lint/stale-names.tsv', 'config/lint/tool-exceptions.tsv',
            'config/lint/specs/v2/capabilities/purpose.md', 'config/lint/specs/v2/capabilities/spec.tsv',
            'config/lint/specs/v2/team/purpose.md', 'config/lint/specs/v2/workspace-view/purpose.md',
            'config/lint/specs/v3/tool-page/purpose.md', 'config/lint/specs/v3/top-pages/purpose.md',
            'config/lint/specs/v3/top-pages/spec-RESOLVER.tsv', 'config/lint/specs/v3/top-pages/spec-STATE.tsv',
            'work/README-standing.md', 'skills/log/SKILL.md', 'skills/orchestrate/SKILL.md',
            'skills/orchestrate/bin/orchestrate')


def copy_tree(tree, home):
    # Installing from an installed checkout must not copy its person's database,
    # configuration, or generated files into another person's fresh home.
    with (tree / 'product-manifest.tsv').open(encoding='utf-8', newline='') as handle:
        shipped = {row['path'] for row in csv.DictReader(handle, delimiter='\t')}
    shipped -= BUILD_ONLY | set(STARTERS)
    shipped.add('product-manifest.tsv')
    workflow_shelf = home / 'skillwright/workflows'
    workflow_record = workflow_shelf / '.release-manifest.json'
    if workflow_shelf.is_symlink() or workflow_record.is_symlink():
        raise ValueError('Workflow shelf and release record must be regular paths.')
    workflow_manifest = json.loads(workflow_record.read_text(encoding="utf-8")) if workflow_record.exists() else {'version': 1, 'workflows': {}}
    if workflow_manifest.get('version') != 1 or not isinstance(workflow_manifest.get('workflows'), dict):
        raise ValueError('Invalid workflow release record.')
    personal_workflows = {name for name, row in workflow_manifest['workflows'].items() if row.get('owner') == 'person'}
    def ignore(directory, names):
        rejected = set(names) & {'.git', '.agents', '.codex', '.claude', '.aws', '.hermes',
                                 'not-shipped', '__pycache__', '.DS_Store'}
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(tree).as_posix()
            # Personal seat files never ship, even if a source manifest lists one.
            if relative == 'profile/agents' or relative.startswith('profile/agents/'):
                rejected.add(name)
                continue
            if path.parent == tree / 'skillwright/workflows' and path.stem in personal_workflows:
                rejected.add(name)
            if relative not in shipped and not any(value.startswith(relative + '/') for value in shipped):
                rejected.add(name)
            if name.endswith(('.pyc', '.pyo')):
                rejected.add(name)
            if path.is_symlink():
                raise ValueError('Product tree contains a symlink: ' + str(path.relative_to(tree)))
            if path.is_dir() and (path / 'install.json').is_file():
                if json.loads((path / 'install.json').read_text(encoding="utf-8")).get('ships') is False:
                    rejected.add(name)
        return rejected
    shutil.copytree(tree, home, dirs_exist_ok=True, ignore=ignore)
    # Keep product fallbacks separate from released personal overrides at the shelf.
    for workflow in sorted((tree / 'skillwright/workflows').glob('*.yaml')):
        if workflow.relative_to(tree).as_posix() not in shipped:
            continue
        files = {workflow.name: workflow.read_bytes()}
        page = workflow.with_suffix('.md')
        if page.relative_to(tree).as_posix() in shipped:
            files[page.name] = page.read_bytes()
        rows = {}
        for name, raw in files.items():
            target = workflow_shelf / '.product' / name
            if target.is_symlink() or target.parent.is_symlink():
                raise ValueError('Product workflow snapshot cannot be linked.')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            rows[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        if workflow.stem not in personal_workflows:
            digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
            workflow_manifest['workflows'][workflow.stem] = dict(owner='product', source='product:' + workflow.name,
                release_id='installed-' + digest[:12], digest=digest, files=rows)
    write_text(workflow_record, json.dumps(workflow_manifest, indent=2, sort_keys=True) + '\n')
    # Starters are made once: after install they are the person's, and a product copy never overwrites them.
    for name in STARTERS:
        target = home / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((tree / name).read_bytes())
            shutil.copymode(str(tree / name), str(target))  # bin/orchestrate stays a command

    from base.install_lint_defaults import retarget_contract_sources
    retarget_contract_sources(home)


def install_profile(tree, home, portfolio, name):
    template = tree / 'config/templates/profile/AGENTS.md'
    starter = home / 'config/templates/profile/AGENTS.md'
    if template.is_file() and not starter.exists():
        starter.parent.mkdir(parents=True, exist_ok=True)
        with starter.open('xb') as stream:
            stream.write(template.read_bytes())
    target = home / 'profile/AGENTS.md'
    if target.exists():
        return
    if not template.is_file():
        raise FileNotFoundError(f'starter global contract template is missing: {template}')
    text = template.read_text(encoding="utf-8")
    text = text.replace('@Person@', name.capitalize())
    text = text.replace('<home>', str(home)).replace('<portfolio>', str(portfolio))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


def configure(home, portfolio, name, workspace, runtime, env):
    run('from base.install_system import install_configuration; '
        'import sys; install_configuration(sys.argv[1],sys.argv[2])', home, env, [home, name])
    person_file = home / 'config/person.json'
    data = json.loads(person_file.read_text(encoding="utf-8"))
    data.update(workspaces=[workspace, 'atlas'], default_workspace=workspace,
                system_workspace=workspace, portfolio=os.path.relpath(portfolio, home), runtime=runtime,
                leads=[('lead-' + workspace)[:40]])
    write_text(person_file, json.dumps(data, indent=2) + '\n')
    for item in ('standing-seats.json', 'dream.json'):
        target = home / 'config' / item
        if not target.exists():
            target.write_bytes((home / 'config/templates' / item).read_bytes())
    squad = home / 'config/squads/example.yaml'
    squad.parent.mkdir(parents=True, exist_ok=True)
    write_text(squad, (home / 'config/templates/squads/example.yaml').read_text(encoding="utf-8")
                     .replace('<workspace>', workspace).replace('<agent>', ('lead-' + workspace)[:40]))
    for item in ('business-names.tsv',):
        target = home / 'config/lint' / item
        write_text(target, target.read_text(encoding="utf-8").replace('<workspace>', workspace))
    tools = home / 'config/templates/tools.yaml'
    write_text(home / 'config/tools.yaml', tools.read_text(encoding="utf-8") if tools.is_file() else 'format: 1\ntools: []\n')


def workspace_install(home, portfolio, workspace, name, packs, env):
    target = portfolio / workspace
    target.mkdir()
    values = dict(definition_root=os.path.relpath(home / 'base', target),
                  portfolio_agents='../AGENTS.md')
    code = '''import json,sys
from pathlib import Path
from base import install_workspace as tool
# Product workspace names permit all lowercase letters, digits, and dashes.
import re
tool.WORKSPACE_ID=re.compile(r'^[a-z0-9-]+$')
tool.KNOWN_MODULES |= set(sys.argv[3].split(','))
values=json.loads(sys.argv[4])
plan=tool.plan_install(modules_root=Path(sys.argv[1]),target=Path(sys.argv[2]),
 live_vault=Path(sys.argv[1]),workspace_type='personal',raw_modules=sys.argv[3],
 values=values,target_workspace=sys.argv[5],install_timestamp=sys.argv[6],
 approved_tags=[],database=None,actor=None)
tool.apply_plan(plan)
'''
    run(code, home, env, [home, target, ','.join(packs), json.dumps(values), workspace,
                        datetime.now(timezone.utc).isoformat()])


def build_database(home, packs, env):
    # The builder owns the existing work.py tables and dictionary.
    legacy = [name for name in packs if name in ('base','work','capture') and (home/name/'blueprint.sql').is_file()]
    run('import sys; from pathlib import Path; from base import build_database as tool; '
        'tool.MODULE_ORDER += ("capture",); '
        'tool.BLUEPRINTS["capture"]=(Path("capture/blueprint.sql").resolve(),); '
        'tool.OBJECTS["capture"]={"tables": ("captures",),"mirrors": (),"trends": (),"views": ()}; '
        'tool.build_database(Path(sys.argv[1]),sys.argv[2],actor="installer")',
        home, env, [home / 'data.db', ','.join(legacy)])
    # The shipped base blueprint owns the prefixed model tables. Compile only shipped packs.
    code = '''import sys
from pathlib import Path
from base import core, build_database
import re
packs=set(sys.argv[2].split(','))
# Add-on tables come from the add-on's own blueprint folder, never from the core blueprint.
targets,columns=core.load(Path('base/blueprint'),addons=core.addon_blueprints(Path('.'),packs))
targets=[row for row in targets if row['module'] in packs]
names={row['name'] for row in targets if row['kind']=='table'}
columns=[row for row in columns if row['table'] in names]
db=core.connect(sys.argv[1],{'writer':'schema','actor':'installer','reason':'Fresh install.'})
try:
 db.executescript(core.sql_schema(targets,columns))
 core.seed_rows(db,targets,columns)
 db.commit()
 for statement in build_database._statements(core.guard_sql(targets,columns)):
  trigger=re.search(r'\\bON\\s+"?([a-z_]+)"?\\s+(?:WHEN|BEGIN)',statement,re.I)
  if trigger and trigger.group(1) not in names|{'_foxrun_sequence'}:
   continue
  db.executescript(statement)
finally: db.close()
'''
    run(code, home, env, [home / 'data.db', ','.join(packs)])
    # The lessons table and active_lessons view, with their dictionary rows (T260); the start page reads them.
    run('import sys; from pathlib import Path; from memory.lessons import apply; apply(Path(sys.argv[1]))',
        home, env, [home / 'data.db'])
    # SCHEMA.md comes from its one builder, base/generate_pages.py, as on every rebuild.
    run('import sys; from pathlib import Path; from base.generate_pages import schema; '
        'home=Path(sys.argv[1]); '
        '\nwith (home/"SCHEMA.md").open("w",encoding="utf-8",newline="\\n") as stream: stream.write(schema(home))', home, env, [home])


GLOSSARY_TAGS = ('## Approved tags\n\n[]\n\nAgents use this list. They never invent tags.\n'
                 'If no tag fits, use the nearest approved parent and record a proposal for the keeper.\n'
                 "The keeper batches proposals for Person's approval; a proposal does not add a tag.\n")


def session_holder(home, env):
    """Sessions log as runs on the task with the reserved key (T744); a fresh tracker gets that task now (T595)."""
    result = subprocess.run([sys.executable, '-B', 'events/session_run.py', 'setup', '--db', str(home / 'data.db'), '--create'],
                            cwd=str(home), env=env, text=True, capture_output=True)
    if result.returncode:
        raise ValueError('session holding task failed: ' + (result.stderr.strip() or result.stdout.strip()))


def build_pages(home, portfolio, env):
    """The Keeper's builders make the pages an agent loads: STATE.md from the rows, the wiki topic pages and atlas/LIBRARY.md, then index.md."""
    day = datetime.now().astimezone().strftime('%Y-%m-%d')
    pages = ['base/page_indexes.py', '--portfolio', str(portfolio), '--system-home', str(home), '--as-of', day, '--kind']
    # Topic pages and atlas/LIBRARY.md first, so each index.md lists them.
    for arguments in (['memory/state.py', 'build', '--all'], pages + ['topics'], pages + ['index'],
                      ['base/make_workspaces_view.py', '--system-home', str(home), '--workspace-root', str(portfolio)]):
        result = subprocess.run([sys.executable, '-B', *arguments], cwd=str(home), env=env, text=True, capture_output=True)
        if result.returncode and not topics_only_issues(arguments, result.stdout):
            raise ValueError(arguments[0] + ' failed: ' + (result.stderr.strip() or result.stdout.strip()))


def topics_only_issues(arguments, stdout):
    """A new wiki has no config/topics.yaml yet. page_indexes.py still writes every page and names the missing catalog as an issue."""
    if arguments[0] != 'base/page_indexes.py':
        return False
    try:
        report = json.loads(stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return False
    return not report.get('stale') and not report.get('shape') and all(
        issue.get('page') == 'config/topics.yaml' for issue in report.get('issues', []))


def populate(home, portfolio, workspace):
    for row in made_rows():
        if row['kind'] in ('table', 'table-group', 'database'):
            continue
        root = home if row['home'] == 'system' else portfolio
        path = root / row['path'].replace('<workspace>', workspace).rstrip('/')
        if row['kind'] == 'folder':
            path.mkdir(parents=True, exist_ok=True)
        elif not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            title = path.stem.replace('_', ' ').replace('-', ' ')
            write_text(path, '# ' + title + '\n\nNo records yet.\n')
    write_text(home / 'STATE.md', '# State\n\nInstall complete. Open your first workspace to begin.\n')
    write_text(home / 'health.json', '{"installed": true, "schedules_enabled": false}\n')
    write_text(portfolio / 'AGENTS.md', '# Foxrun workspaces\n\nRead the selected workspace’s AGENTS.md, STATE.md, and index.md.\n')
    write_text(portfolio / 'CLAUDE.md', '@AGENTS.md\n')
    # index.md at the top of the portfolio is built by base/page_indexes.py (build_pages), from base/templates/index.md.
    write_text(portfolio / 'atlas/AGENTS.md', '# Atlas\n\nKeep knowledge in concepts, entities, comparisons, and queries.\nKeep source files in raw. Read TOPICS.md first.\n')
    # Atlas is a standard workspace: the standard CLAUDE shim and an approved tag source for GLOSSARY.md.
    stamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    write_text(portfolio / 'atlas/CLAUDE.md', '---\ntype: agents\nworkspace: atlas\ntimestamp: ' + stamp + '\n---\n'
        '@AGENTS.md\n')
    tags = portfolio / 'atlas/config/glossary-tags.json'
    tags.parent.mkdir(parents=True, exist_ok=True)
    write_text(tags, json.dumps({'owner': 'Person approves; keeper maintains', 'section': GLOSSARY_TAGS}, indent=2) + '\n')
    # Portfolio pages ship as installer templates.
    for source in (home / 'config/templates/portfolio').glob('*.md'):
        text = source.read_text(encoding="utf-8").replace('<workspace>', workspace)
        text = text.replace('<home>', os.path.relpath(home, portfolio)).replace('<timestamp>', stamp)
        write_text(portfolio / source.name, text)
    gates = portfolio / workspace / 'notes/gates.md'
    gates.parent.mkdir(parents=True, exist_ok=True)
    write_text(gates, '# Approval gates\n\nRead the workspace AGENTS.md and the global contract at ' + str(home / 'profile/AGENTS.md') + '.\n'
        'Get explicit approval before money, sends, deletes, production changes, or actions that cannot be undone.\n'
        'Show the exact action and version for approval.\n')
    # The installed tool leaves a generic stub; make its database location exact.
    for folder in (portfolio / workspace, portfolio / 'atlas'):
        for file in folder.rglob('*.md'):
            text = file.read_text(encoding="utf-8")
            text = text.replace(workspace + '.sqlite', os.path.relpath(home / 'data.db', folder))
            write_text(file, text)


def install_workspace_lead(home, portfolio, workspace, runtime_roots=()):
    """Fill one lead boot; an existing skill name always wins without any writes."""
    if not WORKSPACE.fullmatch(workspace):
        raise ValueError('invalid lead workspace')
    folder = portfolio / workspace
    roots = [folder / 'skills', folder / '.agents/skills', folder / '.claude/skills']
    candidates = roots + [folder / '.codex/skills', home / 'skills',
                          home / 'skillwright/skills', *runtime_roots]
    if any((root / workspace).exists() or (root / workspace).is_symlink()
           for root in candidates):
        return False
    # Native runtime copies use the same local paths as workspace-owned skills.
    # Keep regular files: install manifests and doctor deliberately refuse links.
    for root in roots:
        for path in (root, *root.parents):
            if path.is_symlink():
                raise ValueError('lead skill path must not cross a symlink: ' + str(path))
    text = (home / 'config/templates/workspace-lead/SKILL.md').read_text(encoding="utf-8")
    text = text.replace('<home>', str(home)).replace('<portfolio>', str(portfolio))
    text = text.replace('<workspace>', workspace)
    for root in roots:
        target = root / workspace / 'SKILL.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
    return True


SEAT_BOOT_SKILLS = ('chief', 'architect', 'keeper', 'toolsmith', 'skillwright', 'scout', 'adviser')


def install_seat_boots(home, name, runtime_roots=()):
    """Fill default seat boots; a name taken on any shelf always wins."""
    roots = list(dict.fromkeys([home / 'skills', *runtime_roots]))
    candidates = [*roots, home / 'skillwright/skills']
    # Validate every destination before writing the first skill.
    for root in roots:
        for path in (root, *root.parents):
            if path.is_symlink():
                raise ValueError('seat skill path must not cross a symlink: ' + str(path))
    installed = []
    for skill in SEAT_BOOT_SKILLS:
        if any((root / skill).exists() or (root / skill).is_symlink() for root in candidates):
            print('Skipped seat boot /' + skill + ': skill name already exists on the shelf.')
            continue
        source = home / 'config/templates' / skill
        for root in roots:
            for file in sorted(source.rglob('*')):
                if not file.is_file():
                    continue
                target = root / skill / file.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('x', encoding='utf-8', newline='\n') as stream:
                    stream.write(file.read_text(encoding="utf-8").replace('@Person@', name.capitalize()))
        installed.append(skill)
    return installed


# T862: the setup skills ship beside handoff; a name already on a shelf is skipped, never replaced.
PRODUCT_SKILLS = ('handoff', 'thread', 'foxrun-setup', 'foxrun-help')
# T245: every product skill folder ships to a fresh shelf, except a skill the shelf retired.
RETIRED_SKILLS = frozenset({'to-tickets'})


def product_skills(home):
    """The product skills a fresh install releases: the named four first, then every other folder."""
    root = home / 'skillwright/skills'
    found = sorted(p.name for p in root.iterdir() if (p / 'SKILL.md').is_file()) if root.is_dir() else []
    return tuple(dict.fromkeys([*PRODUCT_SKILLS, *(s for s in found if s not in RETIRED_SKILLS)]))


def install_handoff(home, name, runtime_roots=()):
    """Release the product handoff skill, keeping any existing skill name."""
    return install_product_skill(home, 'handoff', name, runtime_roots)


def install_product_skill(home, skill, name, runtime_roots=()):
    """Release one product skill, keeping any existing skill name."""
    roots = list(dict.fromkeys([home / 'skills', *runtime_roots]))
    for root in roots:
        for path in (root, *root.parents):
            if path.is_symlink():
                raise ValueError(skill + ' skill path must not cross a symlink: ' + str(path))
    # A name already on one shelf is kept there; the other shelves still get the skill (T862).
    open_roots = [root for root in roots if not ((root / skill).exists() or (root / skill).is_symlink())]
    if not open_roots:
        print('Skipped product skill /' + skill + ': skill name already exists on the shelf.')
        return False
    source = home / 'skillwright/skills' / skill
    for root in open_roots:
        for file in sorted(source.rglob('*')):
            if not file.is_file():
                continue
            target = root / skill / file.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(file.read_text(encoding="utf-8").replace('@Person@', name.capitalize()))
            shutil.copymode(file, target)
    return True


def first_agent(home, portfolio, workspace, env):
    ident = ('lead-' + workspace)[:40]
    code = '''import argparse,json,os,re,sys
from pathlib import Path
sys.path.insert(0,str(Path('agents/tools').resolve()))
import agent_new as tool
repo=Path('agents').resolve()
workspace=Path(sys.argv[1]); ident=sys.argv[2]
args=argparse.Namespace(id=ident,role='workspace lead',summary='Lead '+workspace.name+' and keep work clear.',
 tier='work',shared=False,client=workspace.name,runtimes='claude,codex',hermes_mode='none',skills='log,to-tickets',
 tools='',sets='base',return_to='session:caller',dry_run=False)
tool.create_command(args)
identity=tool.load_identity(ident,repo)
# Use the tool's fresh template, without importing a seat's roster or runtime bindings.
for runtime,extension,render in [('claude','md',tool.claude_cape),('codex','toml',tool.codex_cape)]:
 text=render(identity,repo)
 # Paths in Markdown are relative to the workspace. The runtime chooses its model.
 text=text.replace(str(repo),os.path.relpath(repo,workspace))
 text=re.sub(r'^model *[:=].*\\n','',text,flags=re.M)
 for folder in [repo/'generated'/runtime,workspace/'team'/runtime]:
  folder.mkdir(parents=True,exist_ok=True)
  with (folder/(ident+'.'+extension)).open('w',encoding='utf-8',newline='\\n') as stream:
   stream.write(text)
source=identity.path
for target in (repo/'generated'/(ident+'.md'),workspace/'team'/(ident+'.md')):
 with target.open('w',encoding='utf-8',newline='\\n') as stream:
  stream.write(source.read_text(encoding="utf-8"))
# System seats use the same resolver as starts and every other seat reader.
names={p.stem for folder in (repo,repo.parent/'profile/agents') for p in folder.glob('*.md')}
for name in sorted(names):
 file=tool.system_paths.resolve_seat(name,home=repo.parent,shipped_dir=repo)
 if file is None or not tool.is_identity_page(file): continue
 seat=tool.load_identity(file.stem,repo)
 for runtime,extension,render in [('claude','md',tool.claude_cape),('codex','toml',tool.codex_cape)]:
  if runtime not in seat.data['runtimes']: continue
  text=render(seat,repo)
  text=re.sub(r'^model *[:=].*\\n','',text,flags=re.M)
  target=repo/'generated'/runtime/(file.stem+'.'+extension)
  target.parent.mkdir(parents=True,exist_ok=True)
  with target.open('w',encoding='utf-8',newline='\\n') as stream:
   stream.write(text)
'''
    run(code, home, env, [portfolio / workspace, ident])
    write_text(portfolio / workspace / 'team/TEAM.md', '# Team\n\nLead: [' + ident + '](' + ident + '.md).\n'
        'Claude and Codex files are in team/claude and team/codex.\n'
        'Source: agent_new.py’s fresh template. It starts without an existing team or external accounts.\n')
    return ident


def missing_tables(home):
    with sqlite3.connect(str(home / 'data.db')) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return [row['path'] for row in made_rows() if row['kind'] == 'table' and Path(row['path']).name not in names]


def write_manifests(home, portfolio, workspace):
    # Rebuild from the copied shipment list only after all install writers finish.
    original = home / 'product-manifest.tsv'
    with original.open(encoding='utf-8', newline='') as stream:
        names = {row['path'] for row in csv.DictReader(stream, delimiter='\t')}
    # GUIDE.md and INSTALL.md are product pages: they stay installed. GLOSSARY.md is built from the person's words.
    generated = BUILD_ONLY | set(STARTERS) | {'GLOSSARY.md', 'base/product-manifest.tsv', 'base/made-at-install.tsv'}
    names -= generated
    names = {name for name in names if name != 'profile/agents' and not name.startswith('profile/agents/')}
    manifest = home / 'base/product-manifest.tsv'
    with manifest.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(('path', 'bytes', 'sha256'))
        for name in sorted(names):
            raw = (home / name).read_bytes()
            writer.writerow((name, len(raw), hashlib.sha256(raw).hexdigest()))
    # List actual installer outputs. Workspace placeholders remain portable.
    shipped = names | {'product-manifest.tsv', 'base/product-manifest.tsv', 'base/made-at-install.tsv'}
    made = []
    for root, prefix in ((home, ''), (portfolio, 'portfolio/')):
        made.append((prefix + '.', 'folder'))
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise ValueError('Install produced a symbolic link: ' + str(path))
            name = path.relative_to(root).as_posix()
            if not prefix and path.is_file() and name in shipped:
                continue
            name = prefix + name
            if prefix:
                name = name.replace('portfolio/' + workspace + '/', 'portfolio/<workspace>/')
                if name == 'portfolio/' + workspace:
                    name = 'portfolio/<workspace>'
            name = name.replace('lead-' + workspace, '<agent>')
            made.append((name, 'folder' if path.is_dir() else 'file'))
    with (home / 'base/made-at-install.tsv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(('path', 'kind'))
        writer.writerows(made)
    # Root copies are only transport inputs. The doctor uses the base/ lists.
    original.write_bytes(manifest.read_bytes())
    (home / 'made-at-install.tsv').write_bytes((home / 'base/made-at-install.tsv').read_bytes())


RUNTIME_CONTRACTS = {
    'claude': '''@<home>/agents/soul.md

@<home>/profile/AGENTS.md

If the soul is missing, say so in your first reply, then keep working.
If you cannot see the global contract's `Start Every Session` section, stop and tell @Person@. Do no work until it is back.
''',
    'codex': '''1. Read [`<home>/agents/soul.md`](<home>/agents/soul.md).
2. Read [`<home>/profile/AGENTS.md`](<home>/profile/AGENTS.md).

If the soul is missing, say so in your first reply, then keep working.
If the global contract is missing, stop and tell @Person@. Do no work until it is back.
''',
}


def runtime_contract(raw, runtime, home, name):
    """Replace only Foxrun's marked bytes; keep all user and plugin bytes."""
    begin, end = b'<!-- foxrun:begin -->', b'<!-- foxrun:end -->'
    body = RUNTIME_CONTRACTS[runtime].replace('<home>', str(home)).replace('@Person@', name.capitalize())
    block = begin + b'\n' + body.encode('utf-8') + end + b'\n'
    if begin not in raw and end not in raw:
        return raw + (b'\n' if raw and not raw.endswith(b'\n') else b'') + block
    pattern = re.compile(rb'(?ms)^<!-- foxrun:begin -->\r?\n.*?^<!-- foxrun:end -->(?:\r?\n|$)')
    match = pattern.search(raw)
    if raw.count(begin) != 1 or raw.count(end) != 1 or match is None:
        raise ValueError('runtime contract has malformed or duplicate Foxrun markers')
    return raw[:match.start()] + block + raw[match.end():]


def install_runtime_contracts(paths, home, name, write=True):
    """Plan every contract before writing any; reinstall preserves user text."""
    planned = {}
    for runtime, settings in paths.items():
        target = settings.parent / ('CLAUDE.md' if runtime == 'claude' else 'AGENTS.md')
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('runtime contract must be a regular file')
        raw = target.read_bytes() if target.exists() else b''
        planned[target] = runtime_contract(raw, runtime, home, name)
    if write:
        for target, raw in planned.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != raw:
                target.write_bytes(raw)
    return planned


def runtime_paths(args, home, portfolio, tree):
    paths = {}
    for runtime in ('claude', 'codex') if args.runtime == 'both' else (args.runtime,):
        if args.runtime_home:
            folder = Path(args.runtime_home).expanduser()
            if args.runtime == 'both':
                folder /= runtime
        else:
            folder = Path.home() / ('.' + runtime)
        folder = destination(str(folder), 'runtime home', tree, empty=False)
        if within(folder,home) or within(home,folder) or within(folder,portfolio) or within(portfolio,folder):
            raise ValueError('runtime home must not overlap either install folder')
        # Reject settings symlinks before any install writes.
        settings = folder / ('settings.json' if runtime == 'claude' else 'hooks.json')
        if settings.is_symlink():
            raise ValueError('runtime settings must not be a symlink')
        if args.hookup and settings.exists():
            data = json.loads(settings.read_text(encoding="utf-8"))
            if not isinstance(data,dict) or not isinstance(data.get('hooks',{}),dict):
                raise ValueError('runtime settings must contain a JSON object with hooks')
            if any(not isinstance(value,list) for value in data.get('hooks',{}).values()):
                raise ValueError('runtime hook events must contain lists')
        paths[runtime] = settings
    return paths


def hookup(paths, home):
    """Merge the Foxrun hooks into the selected runtime settings (base/hookup.py, shared with
    `foxrun.py hookup`). A changed settings file is backed up under <home>/backups/ first."""
    connect(home, paths)
    # Hermes, when installed: the same start check, start page, and compact handoff (T744).
    for config in hermes_hookup(home):
        print('Hermes hook entries written: ' + str(config))


def schedule_nightly(home, portfolio):
    """Turn on the nightly job from the installed template (cron/schedule.py).
    Return its state word and job file, or None where launchd does not run."""
    if sys.platform != 'darwin' and not os.environ.get('FOXRUN_LAUNCHCTL'):
        return None
    spec = importlib.util.spec_from_file_location('foxrun_schedule', str(home / 'cron/schedule.py'))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    try:
        state = tool.turn_on(home, portfolio)
    except (OSError, ValueError) as error:
        raise ValueError('nightly job not turned on: ' + str(error) +
                         '; run python3 ' + str(home / 'cron/schedule.py') + ' --on, or install with --no-schedule')
    health = home / 'health.json'
    data = json.loads(health.read_text(encoding="utf-8"))
    data['schedules_enabled'] = True
    write_text(health, json.dumps(data) + '\n')
    return state, tool.target()


def main(argv=None):
    listing = "--list-addons" in (sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', required=not listing)
    parser.add_argument('--portfolio', required=not listing)
    parser.add_argument('--person', default='person')
    parser.add_argument('--workspace', default='my-workspace')
    parser.add_argument('--runtime', choices=('claude','codex','both'), default='both')
    parser.add_argument('--runtime-home')
    parser.add_argument('--hookup', action='store_true')
    parser.add_argument('--yes', action='store_true')
    parser.add_argument('--list-addons', action='store_true')
    parser.add_argument('--no-schedule', action='store_true', help='Leave the nightly job off.')
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        tree = Path(__file__).resolve().parent
        from base import optional_addons
        optional_addons.show(tree)
        if args.list_addons:
            return 0
        home = destination(args.home, 'home', tree)
        portfolio = destination(args.portfolio, 'portfolio', tree)
        if within(home,portfolio) or within(portfolio,home):
            raise ValueError('home and portfolio must not overlap')
        if not args.yes:
            args.person = ask('Your name', args.person, 'This name identifies your work. Use one name without spaces.', PERSON.fullmatch)
            args.workspace = ask('First workspace', args.workspace, 'This folder holds your first project. Use lowercase letters, digits, and dashes.', WORKSPACE.fullmatch)
            args.runtime = ask('Runtime', args.runtime, 'Choose the app that reads your work: claude, codex, or both.', lambda value: value in ('claude','codex','both'))
        if not PERSON.fullmatch(args.person):
            raise ValueError('person must be one name without spaces')
        if not WORKSPACE.fullmatch(args.workspace) or args.workspace in ('atlas','inbox'):
            raise ValueError('workspace must use lowercase letters, digits, and dashes; atlas and inbox are reserved')
        paths = runtime_paths(args,home,portfolio,tree)
        install_runtime_contracts(paths,home,args.person,write=False)
        # Nothing above this line writes an install or runtime file.
        home.mkdir(parents=True, exist_ok=True)
        portfolio.mkdir(parents=True, exist_ok=True)
        copy_tree(tree,home)
        # A later `foxrun.py update` with no --source reads this product folder from the home.
        from update import SOURCE_RECORD, source_record
        (home / SOURCE_RECORD).write_bytes(source_record(tree))
        env = environment(home,portfolio,args.person)
        packs = shipped_packs(home)
        configure(home,portfolio,args.person,args.workspace,args.runtime,env)
        install_profile(tree,home,portfolio,args.person)
        workspace_install(home,portfolio,args.workspace,args.person,packs,env)
        populate(home,portfolio,args.workspace)
        # This is a person's starter page, built from their installed catalog and pages.
        run('import sys; from pathlib import Path; from base.build_caps import build; '
            'home=Path(sys.argv[1]); '
            '\nwith (home/"tools/CAPABILITIES.md").open("w",encoding="utf-8",newline="\\n") as stream: stream.write(build(home))',
            home,env,[home])
        build_database(home,packs,env)
        session_holder(home,env)
        run("import sys; from base.install_lint_defaults import generate; generate(*sys.argv[1:])", home,env,[home,portfolio,args.workspace])
        ident = first_agent(home,portfolio,args.workspace,env)
        skill_roots = [path.parent / 'skills' for path in paths.values()]
        # A trial install keeps its shared shelf under the trial folder, never the real home.
        shared = Path(args.runtime_home).expanduser() / 'agents' if args.runtime_home else Path.home() / '.agents'
        skill_roots.append(shared / 'skills')
        for workspace in (args.workspace, 'atlas'):
            install_workspace_lead(home,portfolio,workspace,skill_roots)
        write_manifests(home,portfolio,args.workspace)
        # The built pages: glossaries from the person's words. GUIDE.md and INSTALL.md ship as the product made them.
        run("import sys; from pathlib import Path; from base.published_pages import pages; "
            "home=Path(sys.argv[1]); "
            "\nfor p,body in pages(home,Path(sys.argv[2])).items():\n"
            " if p not in (home/'GUIDE.md',home/'INSTALL.md'):\n"
            "  p.parent.mkdir(parents=True,exist_ok=True)\n"
            "  with p.open('w',encoding='utf-8',newline='\\n') as stream:\n"
            "   stream.write(body)",
            home,env,[home,portfolio])
        build_pages(home,portfolio,env)
        write_manifests(home,portfolio,args.workspace)
        check = subprocess.run([sys.executable,'-B',str(home/'foxrun.py'),'doctor'],cwd=str(home),env=env,text=True,capture_output=True)
        print(check.stdout,end='')
        if check.returncode:
            raise ValueError('doctor failed: ' + check.stderr.strip())
        for skill in product_skills(home):
            install_product_skill(home,skill,args.person,skill_roots)
        install_seat_boots(home,args.person,skill_roots)
        write_manifests(home,portfolio,args.workspace)
        install_runtime_contracts(paths,home,args.person)
        if args.hookup:
            hookup(paths,home)
        nightly = None if args.no_schedule else schedule_nightly(home,portfolio)
        print('Made: Foxrun, its database, Atlas, workspace ' + args.workspace + ', and lead ' + ident + '.')
        print('Lead source: the agents tool’s fresh template; it starts without an existing team or accounts.')
        print('System folder: ' + str(home))
        print('Portfolio folder: ' + str(portfolio))
        print('Next command: ' + shlex.join(['python3',str(home/'foxrun.py'),'start']))
        if args.hookup:
            for runtime, path in paths.items():
                print('Hook entries written: ' + str(path))
                if runtime == 'codex':
                    print('Codex trust rows written: ' + str(path.parent / 'config.toml'))
        else:
            for runtime in ('claude','codex') if args.runtime=='both' else (args.runtime,):
                folder = Path(args.runtime_home).expanduser() if args.runtime_home else Path.home()/('.'+runtime)
                if args.runtime_home and args.runtime=='both':
                    folder /= runtime
                path = folder/('settings.json' if runtime=='claude' else 'hooks.json')
                print('Add these exact entries to ' + str(path) + ' (merge with existing hooks):')
                print(json.dumps({'hooks':hook_entries(home,runtime)},indent=2))
        if args.no_schedule:
            print('Nightly job: off (--no-schedule). Turn it on: ' + shlex.join(['python3',str(home/'cron/schedule.py'),'--on']))
        elif nightly is None:
            print('Nightly job: off; launchd runs on macOS only.')
        else:
            print('Nightly job: ' + nightly[0] + ' ' + str(nightly[1]))
        missing = missing_tables(home)
        if missing:
            raise ValueError('Required database tables are missing: ' + ', '.join(missing))
        print('Install time: %.3f seconds' % (time.monotonic()-started))
        return 0
    except (ValueError,OSError,sqlite3.Error,EOFError) as error:
        print('Install refused or failed: ' + str(error),file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
