#!/usr/bin/env python3
"""T692: a write check reads one page and the few pages its links need.

The scoped check must give the same findings as the old full scan of both
homes, on labeled fixture pages, and it must never walk the bulk folders.
"""
import ast
import csv
import json
from pathlib import Path
import os
import random
import subprocess
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import lint as engine
import lint_gate as gate


def table(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter='\t', lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def page(kind='doc', workspace='shop', body='# Example\n\nA labeled fixture page.\n'):
    return ('---\ntype: ' + kind + '\nworkspace: ' + workspace +
            '\ntimestamp: 2026-10-18T12:00:00-04:00\n---\n' + body)


class ScopedWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd()); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name); self.home = root / '.foxrun'; self.ws = root / 'foxrun'
        self.policy = self.home / 'config/lint'
        shutil.copytree(BASE.parent / 'config/lint', self.policy)
        table(self.policy / 'workspaces.tsv', ['id', 'kind', 'source'],
              [dict(id='shop', kind='workspace', source='Labeled fixture'),
               dict(id='alias', kind='workspace', source='Labeled fixture')])
        table(self.policy / 'db.tsv', ['home', 'path', 'table', 'column', 'format'], [])
        table(self.policy / 'tools.tsv', ['home', 'page', 'runtime', 'source'], [])
        shop = self.ws / 'shop'
        (shop / 'notes').mkdir(parents=True); (shop / 'specs').mkdir()
        (shop / 'AGENTS.md').write_text(page(body='# Labeled workspace contract\n'))
        os.symlink('shop', self.ws / 'alias')  # A renamed workspace keeps its old name as a link.
        (self.home / 'AGENTS.md').write_text(page(workspace='system', body='# Agents\n\nSee [Guide](~/foxrun/shop/notes/guide.md#steps).\n'))
        self.guide = shop / 'notes/guide.md'
        self.guide.write_text(page(body='# Guide\n\n## Steps\n\nLabeled steps.\n\n## Checks\n\nLabeled checks.\n'))
        (shop / 'notes/other.md').write_text(page(body='# Other\n\n[Steps](guide.md#steps) and [[guide#checks]] and [[unique-name]].\n'))
        (shop / 'specs/unique-name.md').write_text(page(body='# Unique\n\nLabeled unique page.\n'))
        (shop / 'specs/twin.md').write_text(page(body='# Twin\n\nLabeled twin one.\n'))
        (shop / 'notes/twin.md').write_text(page(body='# Twin\n\nLabeled twin two.\n'))
        (shop / 'specs/far.md').write_text(page(body='# Far\n\n[Alias link](~/foxrun/alias/notes/guide.md#checks) and [[soon]].\n'))
        # A bulk folder that the write check must never enter.
        bulk = shop / 'archive/old'; bulk.mkdir(parents=True)
        for i in range(50):
            (bulk / ('page-%d.md' % i)).write_text(page(body='# Old\n\n[Steps](../../notes/guide.md#steps)\n'))
        with (BASE.parent / 'config/lint/rules.tsv').open() as stream:
            rows = list(csv.DictReader(stream, delimiter='\t'))
        table(self.policy / 'rules.tsv', ['id', 'words', 'kind', 'scope', 'level'],
              [{k: r[k] for k in ('id', 'words', 'kind', 'scope', 'level')} for r in rows])

    def test_native_listing_and_fallback_select_the_same_link_pool(self):
        (self.ws/'shop/notes/UPPER.MD').write_text(page())
        hidden=self.ws/'shop/private-listing';hidden.mkdir();(hidden/'hidden.md').write_text(page())
        with (self.policy/'scan.tsv').open('a') as stream:
            stream.write('exclude_path\tportfolio/shop/private-listing\tLabeled scan boundary.\n')
        checker=engine.Lint(self.home,self.ws,self.policy)
        accelerated=gate.link_pool(checker)
        with patch.object(gate.shutil,'which',return_value=None):
            fallback=gate.link_pool(engine.Lint(self.home,self.ws,self.policy))
        self.assertEqual(set(accelerated),set(fallback))
        for path in accelerated:
            self.assertEqual(checker.context(path),engine.Lint(self.home,self.ws,self.policy).context(path))

    def both(self, target, body):
        """The scoped check and the old full scan of both homes, on the same request."""
        scoped = gate.evaluate(self.home, self.ws, target, body, self.policy)
        with patch.object(gate, 'needs_home_scan', return_value=True):
            full = gate.evaluate(self.home, self.ws, target, body, self.policy)
        return scoped, full

    def key(self, rows):
        return sorted((r['rule_id'], r['path'], r['what']) for r in rows)

    def test_scoped_findings_equal_full_scan_on_fixture_pages(self):
        guide = self.guide.read_text()
        cases = {
            'unchanged page with links': (self.ws / 'shop/notes/other.md', (self.ws / 'shop/notes/other.md').read_text()),
            'new broken link and section': (self.guide, guide + '\n[Gone](missing.md) and [Self](#nowhere) and [Other](other.md#none)\n'),
            'wiki names: unique, twin, absent': (self.guide, guide + '\n[[unique-name]] [[twin]] [[absent-name]] [[unique-name#nope]]\n'),
            'heading change breaks incoming sections': (self.guide, guide.replace('## Steps', '## Stages').replace('## Checks', '## Proofs')),
            'new page makes a wiki name ambiguous': (self.ws / 'shop/specs/deep/unique-name.md', page(body='# Unique again\n\nLabeled.\n')),
            'new page fixes a wiki name': (self.ws / 'shop/notes/soon.md', page(body='# Soon\n\nLabeled.\n')),
            'link through a linked workspace': (self.ws / 'shop/specs/far.md', (self.ws / 'shop/specs/far.md').read_text() + '\n[[alias/notes/guide#nope]]\n'),
            'system page': (self.home / 'AGENTS.md', page(workspace='system', body='# Agents\n\nSee [Guide](~/foxrun/shop/notes/guide.md#nope).\n')),
        }
        for name, (target, body) in cases.items():
            with self.subTest(case=name):
                scoped, full = self.both(target, body)
                self.assertEqual(self.key(scoped), self.key(full))
        # The fixtures exercise real findings, not only empty deltas.
        scoped, _ = self.both(self.guide, cases['heading change breaks incoming sections'][1])
        self.assertTrue(any(r['what'] == 'Link section is absent: steps' for r in scoped))
        scoped, _ = self.both(*cases['new page makes a wiki name ambiguous'])
        self.assertTrue(any(r['what'].startswith('Wiki link target is ambiguous') for r in scoped))

    def test_write_check_never_walks_bulk_folders_or_the_full_inventory(self):
        bulk = self.ws / 'shop/archive/old'
        walked = []
        real_walk = os.walk
        def walk(top, *args, **kwargs):
            for current, dirs, files in real_walk(top, *args, **kwargs):
                walked.append(Path(current)); yield current, dirs, files
        body = self.guide.read_text().replace('## Steps', '## Stages')
        with patch.object(gate.os, 'walk', walk), \
             patch.object(engine.Lint, 'inventory', side_effect=AssertionError('Full inventory forbidden')):
            gate.evaluate(self.home, self.ws, self.guide, body, self.policy)
        self.assertTrue(walked)
        self.assertFalse(any(bulk == p or bulk in p.parents for p in walked))

    def test_heading_change_with_many_pages_stays_fast(self):
        notes = self.ws / 'shop/notes/many'; notes.mkdir()
        for i in range(1500):
            (notes / ('n-%d.md' % i)).write_text(page(body='# N\n\n[Plain](../guide.md) text %d.\n' % i))
        body = self.guide.read_text().replace('## Checks', '## Proofs')
        start = time.perf_counter()
        rows = gate.evaluate(self.home, self.ws, self.guide, body, self.policy)
        self.assertLess(time.perf_counter() - start, 10.0)
        self.assertTrue(any(r['what'] == 'Link section is absent: checks' for r in rows))

    def test_existing_contract_stays_under_two_seconds_and_100_mb_without_copies(self):
        contract=self.ws/'shop/AGENTS.md'
        large=self.ws/'shop/raw/unrelated.bin';large.parent.mkdir()
        with large.open('wb') as stream:stream.truncate(256*1024*1024)
        scratch=Path(self.tmp.name)/'scratch';scratch.mkdir()
        code='''import json,resource,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
import lint_gate as gate
target=Path(sys.argv[2]);home=Path(sys.argv[3]);portfolio=Path(sys.argv[4]);policy=Path(sys.argv[5])
start=time.perf_counter()
with patch.object(gate.shutil,'copyfile',side_effect=AssertionError('write check copied a file')), \
     patch.object(tempfile,'TemporaryDirectory',side_effect=AssertionError('write check made a temporary tree')):
    findings=gate.evaluate(home,portfolio,target,target.read_text(),policy)
rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({'seconds':time.perf_counter()-start,'rss':rss,'findings':findings}))'''
        env=os.environ.copy();env['TMPDIR']=str(scratch)
        completed=subprocess.run([sys.executable,'-B','-c',code,str(BASE),str(contract),str(self.home),str(self.ws),str(self.policy)],
                                 env=env,capture_output=True,text=True,check=True)
        measured=json.loads(completed.stdout)
        rss_bytes=measured['rss']*(1 if sys.platform=='darwin' else 1024)
        self.assertEqual(measured['findings'],[])
        self.assertLess(measured['seconds'],2)
        self.assertLess(rss_bytes,100_000_000)
        self.assertEqual(list(scratch.iterdir()),[])

    def test_new_contract_stays_under_two_seconds_and_100_mb_without_copies(self):
        contract=self.ws/'new-contract/AGENTS.md'
        scratch=Path(self.tmp.name)/'new-scratch';scratch.mkdir()
        code="import json,resource,sys,tempfile,time\nfrom pathlib import Path\nfrom unittest.mock import patch\nsys.path.insert(0,sys.argv[1])\nimport lint_gate as gate\nstart=time.perf_counter()\nwith patch.object(gate.shutil,'copyfile',side_effect=AssertionError('write check copied a file')), patch.object(tempfile,'TemporaryDirectory',side_effect=AssertionError('write check made a temporary tree')):\n    rows=gate.evaluate(Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4]),Path(sys.argv[5]).read_text(),Path(sys.argv[2])/'config/lint')\nprint(json.dumps({'seconds':time.perf_counter()-start,'rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'findings':rows}))"
        env=os.environ.copy();env['TMPDIR']=str(scratch)
        completed=subprocess.run([sys.executable,'-B','-c',code,str(BASE),str(self.home),str(self.ws),
                                  str(contract),str(self.ws/'shop/AGENTS.md')],
                                 env=env,capture_output=True,text=True,check=True)
        measured=json.loads(completed.stdout)
        rss_bytes=measured['rss']*(1 if sys.platform=='darwin' else 1024)
        self.assertLess(measured['seconds'],2)
        self.assertLess(rss_bytes,100_000_000)
        self.assertTrue(any(r['path']==str(contract) for r in measured['findings']))
        self.assertFalse(contract.exists())
        self.assertEqual(list(scratch.iterdir()),[])

    def test_apps_contract_cli_stays_under_two_seconds_and_100_mb(self):
        apps=self.ws/'apps';apps.mkdir()
        (apps/'huge.md').write_text('broken app content\n'*100_000)
        target=apps/'AGENTS.md'
        body=Path(self.tmp.name)/'apps-body.md'
        body.write_text(page('agents','apps',body='# Apps\n'))
        code="""import json,resource,subprocess,sys,time
start=time.perf_counter()
result=subprocess.run(sys.argv[1:],capture_output=True,text=True,check=True)
rss=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
print(json.dumps(dict(seconds=time.perf_counter()-start,
    peak_rss_bytes=rss*(1 if sys.platform=='darwin' else 1024),findings=json.loads(result.stdout))))"""
        completed=subprocess.run([sys.executable,'-B','-c',code,sys.executable,'-B',str(BASE/'lint_gate.py'),
            '--mode','write','--home',str(self.home),'--workspaces',str(self.ws),
            '--target',str(target),'--body',str(body)],capture_output=True,text=True,check=True,timeout=5)
        measured=json.loads(completed.stdout)
        self.assertLess(measured['seconds'],2)
        self.assertLess(measured['peak_rss_bytes'],100_000_000)
        self.assertEqual(measured['findings'],[])
        self.assertFalse(target.exists())

    def test_skipped_contract_never_scans_neighbors_or_registers_a_workspace(self):
        from base.paths import APP_FOLDERS
        for name in APP_FOLDERS:
            target=self.ws/name/'AGENTS.md'
            target.parent.mkdir()
            with patch.object(gate,'link_pool',side_effect=AssertionError('searched link pool')), \
                 patch.object(gate,'link_referrers',side_effect=AssertionError('searched referrers')), \
                 patch.object(engine.Lint,'inventory',side_effect=AssertionError('walked inventory')):
                self.assertEqual(gate.evaluate(self.home,self.ws,target,page('agents',name),self.policy),[])
            with gate.draft_overlay(target,page('agents',name)):
                checker=engine.Lint(self.home,self.ws,self.policy)
                self.assertNotIn(name,checker.names)
                self.assertFalse(any(checker.matches(target,r['scope']) for r in checker.rules))
            self.assertFalse(target.exists())

    def test_a_configured_shape_exception_is_skipped_by_shape_only_and_lint_still_runs_there(self):
        import base.paths as paths
        from base.paths import APP_FOLDERS, shape_exceptions, skip_workspaces
        name='sample-own-layout'  # A synthetic workspace that the person lists as a shape exception.
        settings=self.home/paths.SHAPE_EXCEPTIONS
        # With no local settings file, the shape check skips only the app folders.
        self.assertFalse(settings.exists())
        self.assertEqual(shape_exceptions(self.home),frozenset())
        self.assertEqual(skip_workspaces(self.home),APP_FOLDERS)
        with patch.dict(os.environ,{'FOXRUN_HOME':str(self.home)}):
            self.assertEqual(paths.SKIP_WORKSPACES,APP_FOLDERS)
        settings.write_text(json.dumps({'shape_exceptions':[name]}))
        self.assertEqual(skip_workspaces(self.home),APP_FOLDERS|{name})
        self.assertNotIn(name,APP_FOLDERS)
        with patch.dict(os.environ,{'FOXRUN_HOME':str(self.home)}):
            from base.paths import SKIP_WORKSPACES
            self.assertIn(name,SKIP_WORKSPACES)
        # A bad settings file fails closed instead of skipping an unknown folder.
        for bad in ({'shape_exceptions':['../'+name]},{'shape_exceptions':['a/b']},{'shape_exceptions':['']},
                    {'shape_exceptions':[5]},{'shape_exceptions':name},[name]):
            settings.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):shape_exceptions(self.home)
        settings.unlink();real=self.home/'other.json';real.write_text(json.dumps({'shape_exceptions':[name]}))
        os.symlink(real,settings)
        with self.assertRaises(ValueError):shape_exceptions(self.home)
        settings.unlink();settings.write_text(json.dumps({'shape_exceptions':[name]}))
        target=self.ws/name/'AGENTS.md'
        target.parent.mkdir()
        with gate.draft_overlay(target,page('agents',name)):
            checker=engine.Lint(self.home,self.ws,self.policy)
            self.assertTrue(any(checker.matches(target,r['scope']) for r in checker.rules))
        self.assertFalse(target.exists())

    def test_full_lint_and_both_link_pools_prune_only_top_level_exceptions(self):
        from base.paths import APP_FOLDERS
        skipped=[]
        for name in APP_FOLDERS:
            folder=self.ws/name;folder.mkdir()
            (folder/'AGENTS.md').write_text('invalid app contract')
            (folder/'invalid.md').write_text('invalid app page [missing](absent.md)\n')
            skipped.append(folder)
        # Identical names under a workspace or system home still get checked.
        nested=self.ws/'shop/notes/apps/invalid.md';nested.parent.mkdir();nested.write_text('bad')
        system=self.home/'apps/invalid.md';system.parent.mkdir();system.write_text('bad')
        near=self.ws/'apps-other/invalid.md';near.parent.mkdir();near.write_text('bad')
        walked=[];real_walk=os.walk
        def walk(*args,**kwargs):
            for current,dirs,files in real_walk(*args,**kwargs):
                walked.append(Path(current));yield current,dirs,files
        with patch.object(engine.os,'walk',walk):
            checker=engine.Lint(self.home,self.ws,self.policy)
            rows=checker.run()
            native=gate.link_pool(checker)
            with patch.object(gate.shutil,'which',return_value=None):
                fallback=gate.link_pool(engine.Lint(self.home,self.ws,self.policy))
            # Direct inventory roots and the full draft overlay obey the same boundary.
            checker.inventory_roots=skipped;checker.files=[];checker.dirs=[]
            checker.inventory()
            self.assertEqual(checker.files,[])
            with gate.draft_overlay(self.ws/'apps/new.md','bad'):
                draft=gate.DraftLint(self.home,self.ws,self.policy,self.ws/'apps/new.md',True)
                draft.inventory()
                self.assertNotIn(self.ws/'apps/new.md',draft.files)
        self.assertFalse(any(any(engine.inside(p,root) for root in skipped) for p in walked))
        self.assertFalse(any(any(engine.inside(Path(r['path']),root) for root in skipped) for r in rows))
        for path in (nested,system,near):
            self.assertTrue(any(r['path']==str(path) and r['rule_id']=='L05' for r in rows))
            self.assertIn(path,native)
        self.assertEqual(set(native),set(fallback))
        self.assertFalse(any(any(engine.inside(p,root) for root in skipped) for p in native))

    def test_links_into_apps_check_existence_without_reading_headings(self):
        apps=self.ws/'apps';apps.mkdir()
        existing=apps/'existing.md';existing.write_text('invalid app content')
        # A linked directory must preserve the same rule for links into apps.
        (self.ws/'shop/notes/app-link').symlink_to(apps,target_is_directory=True)
        body=page(body='# Links\n\n[File](../../apps/existing.md#absent-heading) '
            '[[apps/existing#absent-heading]] [Alias](app-link/existing.md#absent-heading) '
            '[Missing](../../apps/missing.md#heading) [[apps/wiki-missing]]\n')
        target=self.ws/'shop/notes/apps-ref.md'
        original=Path.open
        def opened(path,*args,**kwargs):
            if engine.inside(path.resolve(),apps):raise AssertionError('Read app bytes: '+str(path))
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',opened):
            with gate.draft_overlay(target,body):
                rows=gate.DraftLint(self.home,self.ws,self.policy,target,True).run()
            checked=gate.evaluate(self.home,self.ws,target,body,self.policy)
        full=[r for r in rows if r['path']==str(target) and r['rule_id']=='LINK01']
        scoped=[r for r in checked if r['path']==str(target) and r['rule_id']=='LINK01']
        self.assertEqual(self.key(full),self.key(scoped))
        self.assertEqual(len(full),2)
        self.assertTrue(all(r['what'].startswith('Local link target is absent:') for r in full))
        self.assertTrue(any('missing.md' in r['what'] for r in full))
        self.assertTrue(any('wiki-missing.md' in r['what'] for r in full))

    def populated_contract_folder(self):
        folder=self.ws/'populated';folder.mkdir()
        notes=folder/'notes';notes.mkdir()
        for i in range(500):
            (notes/('page-%d.md' % i)).write_text(page(workspace='populated',body='# Page %d\n' % i))
        (self.ws/'shop/notes/populated-ref.md').write_text(page(body=
            '# Referrer\n\n[[populated/notes/page-499#missing-page]] '
            '[New contract](../../populated/AGENTS.md#missing-contract)\n'))
        return folder/'AGENTS.md',page('agents','populated',body='# Populated\n')

    def test_populated_new_contract_stays_under_two_seconds_and_100_mb_without_copies(self):
        contract,body=self.populated_contract_folder()
        scratch=Path(self.tmp.name)/'populated-scratch';scratch.mkdir()
        code="""import json,resource,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
import lint_gate as gate
start=time.perf_counter()
with patch.object(gate.shutil,'copyfile',side_effect=AssertionError('write check copied a file')), \
     patch.object(tempfile,'TemporaryDirectory',side_effect=AssertionError('write check made a temporary tree')):
    rows=gate.evaluate(Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4]),sys.argv[5],Path(sys.argv[2])/'config/lint')
print(json.dumps({'seconds':time.perf_counter()-start,'rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'findings':rows}))"""
        env=os.environ.copy();env['TMPDIR']=str(scratch)
        completed=subprocess.run([sys.executable,'-B','-c',code,str(BASE),str(self.home),str(self.ws),
                                  str(contract),body],env=env,capture_output=True,text=True,check=True)
        measured=json.loads(completed.stdout)
        rss_bytes=measured['rss']*(1 if sys.platform=='darwin' else 1024)
        print('500-page measurement: '+json.dumps(dict(seconds=measured['seconds'],peak_rss_bytes=rss_bytes)))
        self.assertLess(measured['seconds'],2)
        self.assertLess(rss_bytes,100_000_000)
        self.assertTrue(any(r['what']=='Link section is absent: missing-contract' and
                            r['path'].endswith('populated-ref.md') for r in measured['findings']))
        self.assertFalse(contract.exists())
        self.assertEqual(list(scratch.iterdir()),[])

    def test_populated_contract_uses_one_referrer_pass_and_reads_fallback_pool_once(self):
        target,body=self.populated_contract_folder()
        with patch.object(gate,'link_referrers',wraps=gate.link_referrers) as referred, \
             patch.object(gate.subprocess,'run',wraps=subprocess.run) as searched:
            native=gate.evaluate(self.home,self.ws,target,body,self.policy)
        self.assertEqual(referred.call_count,1)
        queries=[c for c in searched.call_args_list if '--files-with-matches' in c.args[0]]
        if shutil.which('rg'):self.assertEqual(len(queries),2)
        import builtins
        with patch.object(gate.shutil,'which',return_value=None), \
             patch.object(builtins,'open',wraps=builtins.open) as opened, \
             patch.object(gate,'link_referrers',wraps=gate.link_referrers) as referred:
            fallback=gate.evaluate(self.home,self.ws,target,body,self.policy)
        self.assertEqual(referred.call_count,1)
        pool=referred.call_args.args[2]
        reads=[Path(c.args[0]) for c in opened.call_args_list if c.args[1:] == ('rb',)]
        self.assertEqual(len(reads),len(set(reads)))
        self.assertTrue(set(reads).issubset(set(pool)))
        self.assertIn(self.ws/'shop/notes/populated-ref.md',reads)
        self.assertEqual(self.key(fallback),self.key(native))

    def test_non_markdown_forbidden_files_and_linked_files_still_report_findings(self):
        forbidden=self.ws/'shop/notes/blocked.bin';forbidden.write_bytes(b'fixture')
        linked=self.ws/'shop/notes/broken.bin';linked.symlink_to('absent.bin')
        with (self.policy/'rules.tsv').open('a') as stream:
            stream.write('FIXTURE01\tForbidden fixture file.\tforbidden_path\tworkspace:notes/*.bin\terror\n')
        rows=engine.Lint(self.home,self.ws,self.policy).run()
        self.assertTrue(any(r['rule_id']=='FIXTURE01' and r['path']==str(forbidden) for r in rows))
        self.assertTrue(any(r['rule_id']=='LINK01' and r['path']==str(linked) and
                            r['what']=='Symbolic link target is absent or protected.' for r in rows))

    def test_native_referrer_search_uses_the_home_when_stdin_is_a_pipe(self):
        checker=engine.Lint(self.home,self.ws,self.policy)
        pool=gate.link_pool(checker)
        run=subprocess.run
        def piped(command,**kwargs):
            return run(command,input='',**kwargs)
        with patch.object(gate.subprocess,'run',piped):
            found=gate.link_referrers(checker,self.guide,pool,False)
        self.assertIn(self.ws/'shop/notes/other.md',found)

    def test_full_overlay_matches_saved_files_without_copying(self):
        fresh=self.ws/'fresh'
        fresh.mkdir();(fresh/'blank.md').write_text('')
        cases=[
            (self.ws/'shop/notes/new/deep.md',page(body='# New\n\n[Missing](gone.md)\n')),
            (fresh/'AGENTS.md',page(workspace='fresh',body='# Fresh\n')),
            (self.ws/'absent/AGENTS.md',page(workspace='absent',body='# Absent\n')),
            (self.policy/'allowed-top.tsv','scope\tname\tkind\tsource\n'),
        ]
        for target,body in cases:
            with self.subTest(target=target):
                before=target.read_bytes() if target.is_file() else None
                with patch.object(gate.shutil,'copyfile',side_effect=AssertionError('copied a file')), \
                     patch.object(tempfile,'TemporaryDirectory',side_effect=AssertionError('made a temporary tree')), \
                     patch.object(gate,'needs_home_scan',return_value=True):
                    checked=gate.evaluate(self.home,self.ws,target,body,self.policy)
                baseline=engine.Lint(self.home,self.ws,self.policy).run()
                missing=[];parent=target.parent
                while not parent.exists():
                    missing.append(parent);parent=parent.parent
                try:
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(body)
                    candidate=engine.Lint(self.home,self.ws,self.policy).run()
                finally:
                    if before is None:target.unlink()
                    else:target.write_bytes(before)
                    for parent in missing:parent.rmdir()
                self.assertEqual(self.key(checked),self.key(gate.finding_delta(candidate,baseline)))
                self.assertTrue(checked)
                self.assertEqual(target.read_bytes() if target.exists() else None,before)

    def test_full_overlay_inventory_obeys_global_and_rule_exclusions(self):
        cases=[('exclude-dir','shop/hidden/AGENTS.md'),
               ('exclude-path','shop/private/AGENTS.md'),
               ('scope','shop/ignored/AGENTS.md'),
               ('aggregate','shop/aggregate/AGENTS.md'),
               ('included','shop/visible/AGENTS.md')]
        with (self.policy/'scan.tsv').open('a') as stream:
            stream.write('exclude_dir\thidden\tFixture boundary.\n')
            stream.write('exclude_path\tportfolio/shop/private\tFixture boundary.\n')
        for kind,relative in cases:
            with self.subTest(kind=kind):
                target=self.ws/relative
                rules=[dict(id='fixture',kind='required_pages' if kind=='aggregate' else 'frontmatter',
                            scope='pages;!workspace:ignored/')]
                with gate.draft_overlay(target,page()):
                    checker=gate.DraftLint(self.home,self.ws,self.policy,target,True)
                    checker.rules=rules
                    checker.inventory()
                    actual=(set(checker.files),set(checker.dirs))
                target.parent.mkdir(parents=True);target.write_text(page())
                try:
                    checker=engine.Lint(self.home,self.ws,self.policy);checker.rules=rules;checker.inventory()
                    self.assertEqual(actual,(set(checker.files),set(checker.dirs)))
                    self.assertEqual(target in actual[0],kind=='included')
                finally:target.unlink();target.parent.rmdir()

    def forbidden_reads(self, source):
        tree=ast.parse(source)
        inventory=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='inventory')
        aliases={}
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                for name in node.names:aliases[name.asname or name.name]=name.name
            elif isinstance(node,ast.ImportFrom):
                for name in node.names:aliases[name.asname or name.name]=(node.module or '')+'.'+name.name
        forbidden=[]
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call):continue
            fn=node.func;name=None
            if isinstance(fn,ast.Name):name=aliases.get(fn.id,fn.id)
            elif isinstance(fn,ast.Attribute) and isinstance(fn.value,ast.Name):
                name=aliases.get(fn.value.id,fn.value.id)+'.'+fn.attr
            if name in ('open','builtins.open','io.open','codecs.open','os.scandir','os.listdir','os.walk'):
                # Only inventory may walk; draft inventory adds virtual entries.
                if name!='os.walk' or not inventory.lineno<=node.lineno<=inventory.end_lineno:
                    forbidden.append(node.lineno)
        return forbidden

    def test_lint_page_reads_remain_visible_to_the_pathlib_overlay(self):
        self.assertEqual(self.forbidden_reads((BASE/'lint.py').read_text()),[],
                         'Page reads must use pathlib so the draft overlay sees them.')

    def test_read_guard_rejects_each_bypass_including_import_aliases(self):
        source=(BASE/'lint.py').read_text()
        for call in ("open('x')", "io.open('x')", "os.scandir('.')", "os.walk('.')",
                     "os.listdir('.')", "codecs.open('x')", "walk('.')", "scan('.')", "c.open('x')"):
            with self.subTest(call=call):
                mutant=source+"\nfrom os import walk, listdir as scan\nimport codecs as c\ndef bypass():\n    "+call+"\n"
                self.assertTrue(self.forbidden_reads(mutant))

    def test_three_new_contract_cases_match_the_saved_full_engine(self):
        fresh=self.ws/'fresh';fresh.mkdir()
        (fresh/'blank.md').write_text('')
        (fresh/'notes').mkdir();(fresh/'notes/a.md').write_text(page(workspace='wrong'))
        (fresh/'src').mkdir();(fresh/'src/hidden.md').write_text('')
        (self.ws/'shop/notes/ref.md').write_text(page(body='# Ref\n\n[[fresh/src/hidden]] [New](../../absent/AGENTS.md#none)\n'))
        populated=self.populated_contract_folder()
        cases=[populated,(fresh/'AGENTS.md',page(workspace='fresh',body='# Fresh\n\n[Gone](gone.md)\n')),
               (self.ws/'absent/AGENTS.md',page(workspace='absent',body='# Absent\n')),
               (self.ws/'shop/notes/AGENTS.md',page(body='# Nested\n\n[[absent-name]]\n'))]
        for target,body in cases:
            with self.subTest(target=target):
                baseline=engine.Lint(self.home,self.ws,self.policy).run()
                with patch.object(engine.os,'walk',wraps=os.walk) as walked:
                    scoped=gate.evaluate(self.home,self.ws,target,body,self.policy)
                self.assertNotIn(self.home,[Path(c.args[0]) for c in walked.call_args_list])
                self.assertNotIn(self.ws,[Path(c.args[0]) for c in walked.call_args_list])
                missing=[];parent=target.parent
                while not parent.exists():missing.append(parent);parent=parent.parent
                try:
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(body)
                    full=engine.Lint(self.home,self.ws,self.policy).run()
                finally:
                    target.unlink()
                    for parent in missing:parent.rmdir()
                self.assertEqual(self.key(scoped),self.key(gate.finding_delta(full,baseline)))
                if target==populated[0]:
                    with patch.object(gate.shutil,'which',return_value=None):
                        fallback=gate.evaluate(self.home,self.ws,target,body,self.policy)
                    self.assertEqual(self.key(fallback),self.key(scoped))
                    self.assertTrue(any(r['path'].endswith('populated-ref.md') for r in scoped))
                self.assertTrue(any(r['path']==str(target) for r in scoped))

    def test_existing_contract_heading_change_keeps_full_scan_findings(self):
        contract=self.ws/'shop/AGENTS.md'
        source=contract.read_text()
        referrer=self.ws/'shop/notes/contract-link.md'
        referrer.write_text(page(body='# Reference\n\n[Contract](../AGENTS.md#labeled-workspace-contract)\n'))
        draft=source.replace('Labeled workspace contract','Changed workspace contract')
        scoped,full=self.both(contract,draft)
        self.assertEqual(self.key(scoped),self.key(full))
        self.assertTrue(any(row['what']=='Link section is absent: labeled-workspace-contract' for row in scoped))


class EngineCacheTests(unittest.TestCase):
    def test_fast_pattern_forms_match_the_glob_matcher(self):
        patterns = ['**/*.md', '**/node_modules', '**/tools/*/*', 'src', 'releases', 'config/lint/specs',
                    '**/a/b', '**', '**/*', '*.md', 'STATE.md', 'workspaces/*/*.md', 'tools/**/*.md',
                    'x/**', 'wiki/raw/*/*', '**/*.tsv', '**/.md']
        parts = ['a', 'b', 'x', 'raw', 'tools', 'node_modules', 'STATE.md', 'y.md', '.md', 'src',
                 'releases', 'config', 'lint', 'specs', 'workspaces', 'wiki', 'q.tsv', '.']
        rng = random.Random(692)
        for _ in range(3000):
            path = '/'.join(rng.choice(parts) for _ in range(rng.randint(1, 5)))
            for pattern in patterns:
                self.assertEqual(engine.path_match(path, pattern), engine.glob_match(path, pattern), (path, pattern))

    def test_cached_context_equals_a_fresh_answer(self):
        tmp = tempfile.TemporaryDirectory(dir=Path.cwd()); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name); home = root / '.foxrun'; ws = root / 'foxrun'
        shutil.copytree(BASE.parent / 'config/lint', home / 'config/lint')
        table(home / 'config/lint/workspaces.tsv', ['id', 'kind', 'source'],
              [dict(id='shop', kind='workspace', source='Labeled fixture'),
               dict(id='alias', kind='workspace', source='Labeled fixture')])
        table(home / 'config/lint/db.tsv', ['home', 'path', 'table', 'column', 'format'], [])
        (ws / 'shop/notes').mkdir(parents=True); (ws / 'atlas').mkdir()
        (ws / 'shop/AGENTS.md').write_text(page(body='# Labeled workspace contract\n'))
        os.symlink('shop', ws / 'alias')
        paths = [home, home / 'AGENTS.md', home / 'workspaces/shop/x.md', ws, ws / 'shop', ws / 'shop/notes/a.md',
                 ws / 'alias/notes/a.md', ws / 'alias', ws / 'atlas/t.md', ws / 'loose.md', ws / 'other/deep/x.md']
        cached = engine.Lint(home, ws, home / 'config/lint')
        for path in paths + paths:
            self.assertEqual(cached.context(path), old_context(cached, path), path)


def old_context(lint, path):
    """The context algorithm before T692, kept here as the reference."""
    from base.paths import resolve_portfolio_path
    if engine.inside(path, lint.home):
        rel = path.relative_to(lint.home)
        name = rel.parts[1] if len(rel.parts) >= 3 and rel.parts[0] == 'workspaces' else 'system'
        return 'system', rel.as_posix(), name
    try:
        resolved = resolve_portfolio_path(path, lint.workspaces)
    except ValueError:
        resolved = path
    for name in sorted(lint.names):
        try:
            folder = resolve_portfolio_path(lint.workspaces / name, lint.workspaces)
        except ValueError:
            continue
        if engine.inside(resolved, folder) and resolved != folder:
            return 'workspace', resolved.relative_to(folder).as_posix(), name
    rel = path.relative_to(lint.workspaces)
    if len(rel.parts) > 1 and rel.parts[0] in lint.names:
        return 'workspace', Path(*rel.parts[1:]).as_posix(), rel.parts[0]
    if len(rel.parts) > 1 and rel.parts[0] == 'atlas':
        return 'atlas', Path(*rel.parts[1:]).as_posix(), 'atlas'
    return 'portfolio', rel.as_posix(), 'portfolio'


if __name__ == '__main__':
    unittest.main()
