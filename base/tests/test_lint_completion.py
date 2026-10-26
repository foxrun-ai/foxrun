"""L09-L13 behavior on labeled fake homes; no live receipt or release is claimed."""
import ast
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
import lint as engine
import lint_gate as gate
import lint_rule as growth
import lint_render as renderer

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def table(path,columns,rows):
    if any('write' in row for row in rows) and 'write' not in columns:columns=list(columns)+['write']
    if 'write' in columns:
        rows=[dict(row,write=row.get('write','warning')) for row in rows]
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,delimiter='\t',lineterminator='\n')
        writer.writeheader();writer.writerows(rows)

class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.home=self.root/'.foxrun';self.ws=self.root/'foxrun'
        self.home.mkdir();(self.ws/'shop').mkdir(parents=True)
        (self.ws/'shop/AGENTS.md').write_text(self.body('agents', 'shop', '# Contract\n\nA labeled contract.\n'))
        self.policy=self.home/'config/lint'
        shutil.copytree(BASE.parents[0]/'config/lint',self.policy)
        table(self.policy/'workspaces.tsv',['id','kind','source'],[dict(id='shop',kind='workspace',source='Fake fixture')])
        with (self.policy/'routes.tsv').open() as stream:
            reader=csv.DictReader(stream,delimiter='\t');routes=list(reader);columns=reader.fieldnames
        routes.append(dict(home='workspace',type='agents',pattern='AGENTS.md',source='Labeled fixture contract',quote='Contract registers this fixture workspace.'))
        table(self.policy/'routes.tsv',columns,routes)
        table(self.policy/'db.tsv',['home','path','table','column','format'],[])
        for rel in ['base/lint_render.py','base/lint_rule.py','config/lint/brand.css',
                    'skillwright/skills/lint-rule/SKILL.md','skillwright/tools/skill_ship.py','cron/nightly.py']:
            p=self.home/rel;p.parent.mkdir(parents=True,exist_ok=True)
            fixtures={'skillwright/skills/lint-rule/SKILL.md':'# Labeled fake lint-growth skill\n',
                      'cron/nightly.py':'# Labeled fixture: run_lint(\n'}
            if rel in fixtures:p.write_text(fixtures[rel])
            else:shutil.copyfile(BASE.parent/rel,p)
        table(self.policy/'tools.tsv',['home','page','runtime','source'],[])
        self.page=self.home/'PAGE.md';self.page.write_text(self.body())
    def test_fixture_uses_system_temp_directory(self):
        self.assertEqual(self.root.parent.resolve(),Path(tempfile.gettempdir()).resolve())
    def body(self,kind='doc',workspace='system',body='# Example\n\nA useful example.\n'):
        return '---\ntype: '+kind+'\nworkspace: '+workspace+'\ntimestamp: 2026-10-14T12:00:00-04:00\n---\n'+body
    def rule(self,id_,kind,scope='*:**'):
        table(self.policy/'rules.tsv',['id','words','kind','scope','level'],[dict(id=id_,words='Fake fixture.',kind=kind,scope=scope,level='error')])
    def run_rule(self,id_):return engine.Lint(self.home,self.ws,self.policy).run(id_)
    def shipped_rules(self,*ids):
        with (BASE.parent/'config/lint/rules.tsv').open() as stream:
            rows=[r for r in csv.DictReader(stream,delimiter='\t') if r['id'] in ids]
        self.assertEqual({r['id'] for r in rows},set(ids))
        table(self.policy/'rules.tsv',['id','words','kind','scope','level'],rows)
    def tool(self):
        p=self.home/'tools/cli/thing.py';p.parent.mkdir(parents=True);p.write_text('print("fake")\n')
        page=p.with_suffix('.md');page.write_text(self.body('tool'))
        return p,page
    def test_l09_separates_adjacent_tool_and_page(self):
        self.shipped_rules('L09');self.tool();self.assertEqual(self.run_rule('L09'),[])
    def test_l09_unpaged_payload_is_a_finding(self):
        self.shipped_rules('L09');p,page=self.tool();page.unlink()
        self.assertIn('no page',self.run_rule('L09')[0]['what'])
    def test_l09_unmapped_page_is_a_finding(self):
        self.shipped_rules('L09');p,page=self.tool();p.unlink()
        self.assertIn('no separately identified',self.run_rule('L09')[0]['what'])
    def test_l09_external_runtime_is_never_executed(self):
        self.shipped_rules('L09');p,page=self.tool()
        table(self.policy/'tools.tsv',['home','page','runtime','source'],[dict(home='system',page='tools/cli/thing.md',runtime=str(p),source='Fake source')])
        with patch.object(subprocess,'run',side_effect=AssertionError('Tool execution forbidden')):
            self.assertEqual(self.run_rule('L09'),[])
        p.unlink();self.assertIn('runtime is absent',self.run_rule('L09')[0]['what'])
    def test_l09_every_category_detects_unpaged_tools_and_accepts_paired_pages(self):
        self.shipped_rules('L09')
        for home in [self.home,self.ws/'shop']:
            for kind in ['cli','mcp','service','plugin','external-app','schedule']:
                with self.subTest(home=home.name,kind=kind):
                    tool=home/'tools'/kind/'unpaged.py';tool.parent.mkdir(parents=True,exist_ok=True)
                    tool.write_text('print("labeled inert fixture")\n')
                    findings=[r for r in self.run_rule('L09') if r['path']==str(tool)]
                    self.assertEqual(len(findings),1)
                    tool.with_suffix('.md').write_text(self.body('tool','system' if home==self.home else 'shop'))
                    self.assertFalse([r for r in self.run_rule('L09') if r['path'] in (str(tool),str(tool.with_suffix('.md')))])
    def test_l09_shipped_scope_detects_unpaged_directories_in_every_category(self):
        self.shipped_rules('L09')
        for home in [self.home,self.ws/'shop']:
            for kind in ['cli','mcp','service','plugin','external-app','schedule']:
                with self.subTest(home=home.name,kind=kind):
                    package=home/'tools'/kind/'unpaged-package';package.mkdir(parents=True,exist_ok=True)
                    (package/'run.py').write_text('print("inert nested fixture")\n')
                    control=package.with_suffix('.py');control.write_text('# inert file control\n')
                    findings=self.run_rule('L09')
                    self.assertEqual(len([r for r in findings if r['path']==str(package)]),1)
                    self.assertEqual(len([r for r in findings if r['path']==str(control)]),1)
                    self.assertFalse([r for r in findings if r['path']==str(package/'run.py')])
    def test_prewrite_preserves_paired_directories_with_shipped_l09_scope(self):
        self.shipped_rules('L09')
        for home in [self.home,self.ws/'shop']:
            for kind in ['cli','mcp','service','plugin','external-app','schedule']:
                with self.subTest(home=home.name,kind=kind):
                    package=home/'tools'/kind/'paired-package';package.mkdir(parents=True,exist_ok=True)
                    (package/'unread.md').write_text('Payload content must not be read.\n')
                    (package/'.env').write_text('Labeled fake protected fixture; not a credential.\n')
                    page=package.with_suffix('.md');page.write_text(self.body('tool','system' if home==self.home else 'shop'))
                    self.assertEqual(self.run_rule('L09'),[])
                    before=page.read_bytes()
                    original_copy=shutil.copyfile;original_read=Path.read_text
                    def copy_without_payload(source,*args,**kwargs):
                        self.assertNotIn('/paired-package/',str(source))
                        self.assertFalse(engine.protected(source))
                        return original_copy(source,*args,**kwargs)
                    def read_without_payload(path,*args,**kwargs):
                        self.assertNotIn('/paired-package/',str(path))
                        self.assertFalse(engine.protected(path))
                        return original_read(path,*args,**kwargs)
                    with patch.object(gate.shutil,'copyfile',side_effect=copy_without_payload),patch.object(Path,'read_text',read_without_payload):
                        self.assertEqual(gate.evaluate(self.home,self.ws,page,page.read_text(),self.policy),[])
                    self.assertEqual(page.read_bytes(),before)
                    self.assertTrue((package/'unread.md').is_file())
    def test_prewrite_preserves_declared_local_runtime_files_and_directories(self):
        self.shipped_rules('L09');registry=[]
        for owner,home in [('system',self.home),('shop',self.ws/'shop')]:
            for kind in ['file','directory']:
                with self.subTest(owner=owner,kind=kind):
                    runtime=home/'runtimes'/('inert-runner.py' if kind=='file' else 'inert-package')
                    runtime.parent.mkdir(parents=True,exist_ok=True)
                    if kind=='file':runtime.write_text('Runtime bytes must not be read.\n')
                    else:runtime.mkdir();(runtime/'unread.md').write_text('Nested runtime bytes must not be read.\n')
                    page=home/'tools/service'/('declared-'+kind+'.md');page.parent.mkdir(parents=True,exist_ok=True)
                    page.write_text(self.body('tool','system' if owner=='system' else 'shop'))
                    registry.append(dict(home=owner,page=page.relative_to(home).as_posix(),runtime=runtime.relative_to(home).as_posix(),source='Labeled local fixture'))
                    table(self.policy/'tools.tsv',['home','page','runtime','source'],registry)
                    self.assertEqual(self.run_rule('L09'),[])
                    original_copy=shutil.copyfile;original_read=Path.read_text
                    def no_runtime_copy(source,*args,**kwargs):
                        self.assertNotIn('/runtimes/',str(source))
                        return original_copy(source,*args,**kwargs)
                    def no_runtime_read(path,*args,**kwargs):
                        self.assertNotIn('/runtimes/',str(path))
                        return original_read(path,*args,**kwargs)
                    with patch.object(gate.shutil,'copyfile',side_effect=no_runtime_copy),patch.object(Path,'read_text',no_runtime_read):
                        self.assertEqual(gate.evaluate(self.home,self.ws,page,page.read_text(),self.policy),[])
    def test_l09_metadata_keeps_protected_entries_excluded(self):
        self.shipped_rules('L09')
        hidden=self.home/'tools/service/.env';hidden.mkdir(parents=True)
        (hidden/'unread.md').write_text('Labeled fake protected fixture.\n')
        self.assertEqual(self.run_rule('L09'),[])
        checker=engine.Lint(self.home,self.ws,self.policy)
        metadata=gate.tool_metadata(checker,[self.home,self.ws])
        self.assertNotIn(hidden,metadata)
        self.assertFalse(any(engine.protected(p) for p in metadata))
    def test_l10_correct_type_home_passes(self):
        page=self.home/'README.md';page.write_text(self.body())
        self.rule('L10','object_route','system:README.md');self.assertEqual(self.run_rule('L10'),[])
    def test_l10_unsupported_generic_root_doc_stays_unresolved(self):
        self.rule('L10','object_route','system:PAGE.md')
        self.assertIn('outside the coded home',self.run_rule('L10')[0]['what'])
    def test_l10_preserves_tool_binding_exceptions(self):
        runtime,page=self.tool()
        excluded=page.parent/'README.md';excluded.write_text(self.body('tool'))
        self.rule('L10','object_route','system:tools/**/*.md')
        self.assertEqual([r['path'] for r in self.run_rule('L10')],[str(excluded)])
    def test_l10_wrong_home_and_unknown_type_fail(self):
        self.rule('L10','object_route','system:PAGE.md')
        for kind in ['feature','unknown-type']:
            self.page.write_text(self.body(kind));self.assertIn('outside the coded home',self.run_rule('L10')[0]['what'])
    def test_l10_missing_type_blocks_routing(self):
        self.rule('L10','object_route','system:PAGE.md');self.page.write_text('# Example\n')
        self.assertIn('without a type',self.run_rule('L10')[0]['what'])
    def test_l08_preserves_applied_build_spec_binding_and_checks(self):
        self.rule('L08','page_spec','workspace:specs/**/*.md')
        page=self.ws/'shop/specs/example.md';page.parent.mkdir(parents=True)
        labels=['Problem','Result','Scope','Sources','Changes','Checks','Rollback','Open questions']
        page.write_text(self.body('spec','shop','# Example\n\n'+''.join('## '+h+'\n\nA specific fixture.\n\n' for h in labels)))
        self.assertEqual(self.run_rule('L08'),[])
        page.write_text(page.read_text().replace('## Checks','## Other'))
        self.assertTrue(any('Checks' in r['what'] for r in self.run_rule('L08')))
    def test_l01_rejects_malformed_drawn_spec_and_l10_accepts_its_home(self):
        page=self.ws/'shop/specs/broken.md';page.parent.mkdir(parents=True)
        page.write_text(self.body('spec','shop','# Broken\n\nThis deliberately incomplete spec has no required implementation sections.\n'))
        self.rule('L01','page_spec','workspace:**/*.md')
        self.assertTrue(self.run_rule('L01'))
        self.rule('L10','object_route','workspace:**/*.md')
        self.assertEqual(self.run_rule('L10'),[])
        wrong=self.ws/'shop/docs/specs/broken.md';wrong.parent.mkdir(parents=True);page.rename(wrong)
        self.assertTrue(any(r['path']==str(wrong) for r in self.run_rule('L10')))
    def test_l11_skill_and_helper_are_required(self):
        self.rule('L11','lint_growth');self.assertEqual(self.run_rule('L11'),[])
        (self.home/'base/lint_rule.py').unlink();self.assertIn('absent',self.run_rule('L11')[0]['what'])
    def test_l11_one_row_requires_both_fixture_results_and_keeps_evidence(self):
        self.rule('BASE','blank_page','system:PAGE.md')
        self.page.write_text(self.body(body='# Example\n\nThis labeled fake page has enough content to test the good fixture boundary.\n'))
        badhome=self.root/'bad-home';badws=self.root/'bad-ws';badhome.mkdir();badws.mkdir()
        (badhome/'PAGE.md').write_text(self.body(body=''))
        evidence=self.root/'finding.txt';evidence.write_text('Labeled fake blank-page finding.\n')
        rule=dict(id='NEW',words='No blank page.',kind='blank_page',scope='system:PAGE.md',level='error')
        before=(self.policy/'rules.tsv').read_bytes()
        result=growth.grow(self.policy,rule,'FIXTURE',evidence,(self.home,self.ws),(badhome,badws))
        self.assertEqual(result['good'],0);self.assertGreater(result['bad'],0)
        self.assertEqual((self.policy/'rules.tsv').read_bytes(),before)
        growth.grow(self.policy,rule,'FIXTURE',evidence,(self.home,self.ws),(badhome,badws),True)
        with (self.policy/'rule-evidence.tsv').open() as stream:
            ledger=list(csv.DictReader(stream,delimiter='\t'))
        self.assertEqual(ledger[-1]['sha256'],sha(evidence));self.assertEqual(ledger[-1]['task'],'FIXTURE')
        self.assertEqual((self.policy/ledger[-1]['evidence']).read_bytes(),evidence.read_bytes())
        with self.assertRaises(ValueError):growth.grow(self.policy,dict(rule,id='BAD'),'FIXTURE',evidence,(self.home,self.ws),(self.home,self.ws),True)
    def test_l12_all_gate_entries_are_connected(self):
        self.rule('L12','lint_gates');self.assertEqual(self.run_rule('L12'),[])
        (self.home/'cron/nightly.py').write_text('# Labeled fixture: no lint call\n')
        self.assertIn('disconnected: nightly',self.run_rule('L12')[0]['what'])
    def test_prewrite_checks_prospective_bytes_and_preserves_original(self):
        self.rule('L05','frontmatter','system:PAGE.md');old=self.page.read_bytes()
        self.assertEqual(gate.evaluate(self.home,self.ws,self.page,self.body(),self.policy),[])
        self.assertTrue(gate.evaluate(self.home,self.ws,self.page,self.body(workspace='old-owner'),self.policy))
        self.assertEqual(self.page.read_bytes(),old)
    def test_prewrite_ignores_old_findings_and_line_changes(self):
        self.rule('L05','frontmatter','system:**/*.md')
        self.page.write_text(self.body(workspace='old-owner'))
        (self.home/'OLD.md').write_text('# Existing broken page\n')
        self.assertTrue(engine.Lint(self.home,self.ws,self.policy).run())
        body=self.page.read_text().replace('workspace: old-owner','\nworkspace: old-owner')
        self.assertEqual(gate.evaluate(self.home,self.ws,self.page,body,self.policy),[])
        self.assertEqual(gate.evaluate(self.home,self.ws,self.home/'NEW.md',self.body(),self.policy),[])
        added=gate.evaluate(self.home,self.ws,self.page,body.replace('type: doc','type: Invalid Type'),self.policy)
        self.assertTrue(added)
        self.assertTrue(all(r['what']=='Invalid front matter value: type' for r in added))
    def test_hook_passes_existing_and_added_page_findings(self):
        # g-checks-never-block-work-except-secrets (fe36ef3): only a secret blocks a save; page findings never block.
        self.rule('L05','frontmatter','system:PAGE.md')
        self.page.write_text(self.body(workspace='old-owner'))
        event=dict(tool_name='Write',tool_input=dict(file_path=str(self.page),content=self.page.read_text()+'\n'))
        passed=self.hook_cli(event)
        self.assertEqual((passed.returncode,passed.stdout,passed.stderr),(0,'',''))
        event['tool_input']['content']='# Missing front matter\n'
        passed=self.hook_cli(event)
        self.assertEqual((passed.returncode,passed.stdout,passed.stderr),(0,'',''))
    def test_prewrite_scopes_reads_and_timing_with_many_old_findings(self):
        self.rule('L05','frontmatter','system:**/*.md')
        old=self.home/'old';old.mkdir()
        for i in range(1000):(old/(str(i)+'.md')).write_text('# Old invalid fixture\n')
        original=Path.read_text
        def read_selected(path,*args,**kwargs):
            self.assertNotIn(old,path.parents)
            return original(path,*args,**kwargs)
        start=time.perf_counter()
        with patch.object(Path,'read_text',read_selected),patch.object(engine.Lint,'inventory',side_effect=AssertionError('Full inventory forbidden')):
            self.assertEqual(gate.evaluate(self.home,self.ws,self.page,self.body(),self.policy),[])
        elapsed=time.perf_counter()-start
        self.assertLess(elapsed,2.0,'A local write must not scan unrelated old pages.')
    def test_prewrite_accepts_history_outputs_and_blocks_new_unknown_top(self):
        self.shipped_rules('L02','LINK01','UPKEEP04')
        self.allow_current_top()
        history=self.ws/'shop/history';history.mkdir()
        target=history/'outputs/evidence.md'
        self.assertEqual(gate.evaluate(self.home,self.ws,target,'# Labeled evidence\n',self.policy),[])
        unknown=self.ws/'shop/unknown/evidence.md'
        rows=gate.evaluate(self.home,self.ws,unknown,'# Labeled evidence\n',self.policy)
        self.assertTrue(any(r['rule_id']=='L02' and r['path']==str(unknown.parent) for r in rows))
    def test_delta_uses_rule_path_and_message_only(self):
        row=dict(rule_id='R',path='/fixture',what='Old',line=1,level='error')
        self.assertEqual(gate.finding_delta([dict(row,line=99)],[row]),[])
        for key in ['rule_id','path','what']:
            changed=dict(row);changed[key]+=' new'
            self.assertEqual(gate.finding_delta([changed],[row]),[changed])
    def test_prewrite_checks_incoming_link_anchors(self):
        self.shipped_rules('LINK01')
        other=self.home/'OTHER.md';other.write_text('[Existing link](PAGE.md#example)\n')
        self.assertEqual(gate.evaluate(self.home,self.ws,self.page,self.body(),self.policy),[])
        rows=gate.evaluate(self.home,self.ws,self.page,self.body(body='# Changed\n\nA useful example.\n'),self.policy)
        self.assertTrue(any(r['path']==str(other) and r['what']=='Link section is absent: example' for r in rows))
    def test_full_scan_compares_both_states_on_the_same_safe_copy(self):
        self.shipped_rules('LINK01','L03')
        evidence=self.home/'history/outputs/old.md';evidence.parent.mkdir(parents=True)
        evidence.write_text('Labeled historical evidence.\n')
        body=self.body(body='# Example\n\n[Old evidence](history/outputs/old.md)\n')
        self.page.write_text(body)
        # The safe copy omits history payloads. That omission must cancel in
        # the baseline, rather than become a new finding on an unchanged write.
        self.assertEqual(gate.evaluate(self.home,self.ws,self.page,body,self.policy),[])
        rows=gate.evaluate(self.home,self.ws,self.page,body+'\n[New broken link](missing.md)\n',self.policy)
        self.assertEqual(len(rows),1)
        self.assertIn('missing.md',rows[0]['what'])
        self.assertEqual(gate.evaluate(self.home,self.ws,self.page,self.body()+'\n[New valid link](history/outputs/old.md)\n',self.policy),[])
    def test_prewrite_keeps_heading_preserving_plain_text_edits_local(self):
        self.shipped_rules('LINK01')
        body=self.body(body='# Example\n\nA changed fact with the same heading.\n')
        with patch.object(engine.Lint,'inventory',side_effect=AssertionError('Full inventory forbidden')):
            self.assertEqual(gate.evaluate(self.home,self.ws,self.page,body,self.policy),[])
    def test_prewrite_ignores_git_index_rules_for_body_writes(self):
        self.rule('CACHE','tracked_cache')
        with patch.object(gate.subprocess,'run',side_effect=AssertionError('Git index must not be read')):
            self.assertEqual(gate.evaluate(self.home,self.ws,self.page,self.body(),self.policy),[])
    def allow_current_top(self):
        allowed=[]
        for scope,root in [('system',self.home),('portfolio',self.ws),('workspace',self.ws/'shop')]:
            allowed.extend(dict(scope=scope,name=p.name,kind='dir' if p.is_dir() else 'file',
                                source='Labeled fixture') for p in root.iterdir())
        table(self.policy/'allowed-top.tsv',['scope','name','kind','source'],allowed)
    def candidate_scope_regression(self,full):
        if not full:self.shipped_rules('L02','LINK01')
        page=self.home/'sources/blank.md';page.parent.mkdir();page.write_text('')
        hidden=page.parent/'.env.fixture.md';hidden.write_bytes(b'\xff')
        if not full:self.allow_current_top();self.assertEqual(engine.Lint(self.home,self.ws,self.policy).run(),[])
        rules=self.policy/'rules.tsv';before=rules.read_text()
        body=before+'NEW\tNo blank source pages.\tblank_page\tsystem:sources/*.md\terror'+('\twarning' if 'write' in before.splitlines()[0].split('\t') else '')+'\n'
        copyfile=shutil.copyfile
        def safe_copy(source,dest,*args,**kwargs):
            self.assertFalse(engine.protected(source));return copyfile(source,dest,*args,**kwargs)
        with patch.object(gate.shutil,'copyfile',side_effect=safe_copy):
            checked=gate.evaluate(self.home,self.ws,rules,body,self.policy)
        self.assertEqual(rules.read_text(),before)
        rules.write_text(body)
        direct=engine.Lint(self.home,self.ws,self.policy).run()
        rules.write_text(before)
        got=[r for r in checked if r['rule_id']=='NEW'];expected=[r for r in direct if r['rule_id']=='NEW']
        self.assertEqual(got,expected);self.assertEqual(len(got),1)
        self.assertEqual(got[0]['path'],str(page))
        self.assertFalse(any(r['path']==str(hidden) for r in checked))
        if not full:self.assertEqual(checked,direct)
        return checked,direct
    def test_prewrite_expanded_scope_with_clean_shipped_rules(self):
        self.candidate_scope_regression(False)
    def test_prewrite_expanded_scope_with_all_shipped_rules(self):
        self.candidate_scope_regression(True)
    def required_history_regression(self,full=False,missing=False,broken=False):
        if not full:self.shipped_rules('L02','LINK01','UPKEEP05')
        log=self.ws/'shop/history/LOG.md';log.parent.mkdir()
        text=self.body('log','shop','''# Log: shop

This labeled fixture checks the required history page.

```
ENTRIES  1
WITH NO DATE  0
DAYS WITH AN ENTRY  1
FIRST  2026-10-14
NEWEST  2026-10-14
MADE  2026-10-14
```

## The 5 newest days

### 2026-10-14

| Time | What happened | By | Tag |
|---|---|---|---|
| 12:00 | Labeled fixture | reviewer | test |

## Older

| Month | Entries | Days with an entry |
|---|---|---|
| 2026-09 | 0 | 0 |
''')
        if not missing:log.write_text(text.replace('## Older','## Wrong section') if broken else text)
        for name in ['unrelated.md','.env.fixture.md']:(log.parent/name).write_bytes(b'\xff')
        self.allow_current_top()
        before=self.page.read_bytes();log_before=log.read_bytes() if log.exists() else None
        direct=engine.Lint(self.home,self.ws,self.policy).run()
        copyfile=shutil.copyfile;read_text=Path.read_text;copied=[]
        def selected_copy(source,dest,*args,**kwargs):
            source=Path(source);self.assertFalse(engine.protected(source))
            # T757: only inputs affected by this write may be copied.
            if log.parent in source.parents:
                copied.append(source);self.fail('Unrelated history was copied.')
            return copyfile(source,dest,*args,**kwargs)
        def selected_read(source,*args,**kwargs):
            if log.parent in source.parents:self.fail('Unrelated history was opened.')
            self.assertFalse(engine.protected(source))
            return read_text(source,*args,**kwargs)
        with patch.object(gate.shutil,'copyfile',side_effect=selected_copy),patch.object(Path,'read_text',selected_read):
            checked=gate.evaluate(self.home,self.ws,self.page,self.page.read_text(),self.policy)
        expected=[r for r in direct if r['rule_id']=='UPKEEP05']
        got=[r for r in checked if r['rule_id']=='UPKEEP05']
        self.assertEqual(got,[])  # Existing required-page findings do not block this unrelated write.
        self.assertEqual(self.page.read_bytes(),before)
        self.assertEqual(log.read_bytes() if log.exists() else None,log_before)
        if missing:
            self.assertEqual(len(expected),1);self.assertEqual(expected[0]['what'],'Required top page is absent or linked.')
            self.assertEqual(copied,[])
        elif broken:
            self.assertTrue(expected);self.assertFalse(any(r['what']=='Required top page is absent or linked.' for r in expected))
            self.assertEqual(copied,[])
        else:self.assertEqual(got,[]);self.assertEqual(copied,[])
        self.assertEqual(checked,[])
        return checked,direct
    def test_prewrite_skips_unrelated_history_with_clean_shipped_rules(self):
        self.required_history_regression()
    def test_prewrite_skips_unrelated_history_with_all_shipped_rules(self):
        self.required_history_regression(full=True)
    def test_nightly_still_reports_absent_required_history(self):
        self.required_history_regression(missing=True)
    def test_nightly_still_reports_absent_required_history_with_all_shipped_rules(self):
        self.required_history_regression(full=True,missing=True)
    def test_nightly_still_validates_required_history_form(self):
        self.required_history_regression(broken=True)
    def test_new_tool_payloads_keep_the_affected_inventory_check(self):
        self.shipped_rules('L09')
        folder=self.home/'tools/cli'
        # A first payload can also create the declared tool root itself.
        target=folder/'first.py'
        self.assertFalse(folder.exists())
        findings=gate.evaluate(self.home,self.ws,target,'print("Labeled fake tool")\n',self.policy)
        self.assertTrue(any(r['rule_id']=='L09' and 'payload has no page' in r['what'] for r in findings),findings)
        with patch.object(gate,'needs_home_scan',return_value=True):
            full=gate.evaluate(self.home,self.ws,target,'print("Labeled fake tool")\n',self.policy)
        self.assertEqual(findings,full)
        self.assertFalse(folder.exists())
        folder.mkdir(parents=True)
        for target in [folder/'new.py',folder/'vendor/new.py']:
            with self.subTest(target=target):
                findings=gate.evaluate(self.home,self.ws,target,'print("Labeled fake tool")\n',self.policy)
                self.assertTrue(any(r['rule_id']=='L09' and 'payload has no page' in r['what'] for r in findings),findings)
                with patch.object(gate,'needs_home_scan',return_value=True):
                    full=gate.evaluate(self.home,self.ws,target,'print("Labeled fake tool")\n',self.policy)
                self.assertEqual(findings,full)
                self.assertFalse(target.exists())

    def test_writing_required_history_checks_its_form_without_copying(self):
        # T757 keeps an affected required-page check; only unrelated history is skipped.
        self.required_history_regression(broken=True)
        target=self.ws/'shop/history/LOG.md'
        original=target.read_bytes();copied=[];copyfile=shutil.copyfile
        def copy(source,dest,*args,**kwargs):
            if Path(source)==target:copied.append(target)
            return copyfile(source,dest,*args,**kwargs)
        # This change removes the required heading, rather than repeating an existing defect.
        valid=target.read_text().replace('## Wrong section','## Older')
        target.write_text(valid)
        with patch.object(gate.shutil,'copyfile',side_effect=copy):
            findings=gate.evaluate(self.home,self.ws,target,valid.replace('## Older','## Wrong section'),self.policy)
        self.assertTrue(any(r['rule_id']=='UPKEEP05' and r['write']=='warning' for r in findings),findings)
        self.assertEqual(copied,[])
        self.assertEqual(target.read_text(),valid)

    def test_prewrite_inventory_uses_candidate_workspace_names(self):
        self.shipped_rules('L02')
        with (self.policy/'rules.tsv').open() as stream:rows=list(csv.DictReader(stream,delimiter='\t'))
        rows.append(dict(id='NEW',words='Fixture.',kind='blank_page',scope='workspace:check.md',level='error'))
        table(self.policy/'rules.tsv',list(rows[0]),rows)
        page=self.ws/'fresh/check.md';page.parent.mkdir();page.write_text('');self.allow_current_top()
        # T758 replaces list edits with a new workspace contract.
        target=self.ws/'fresh/AGENTS.md'
        checked=gate.evaluate(self.home,self.ws,target,self.body(workspace='fresh'),self.policy)
        self.assertEqual([r['path'] for r in checked if r['rule_id']=='NEW'],[str(page)])
    def test_prewrite_inventory_uses_candidate_scan_exclusions(self):
        self.shipped_rules('L02')
        with (self.policy/'rules.tsv').open() as stream:rows=list(csv.DictReader(stream,delimiter='\t'))
        rows.append(dict(id='NEW',words='Fixture.',kind='blank_page',scope='system:sources/*.md',level='error'))
        table(self.policy/'rules.tsv',list(rows[0]),rows)
        page=self.home/'sources/blank.md';page.parent.mkdir();page.write_text('');self.allow_current_top()
        table(self.policy/'scan.tsv',['kind','pattern','reason'],[dict(kind='exclude_dir',pattern='sources',reason='Labeled fixture')])
        self.assertFalse([r for r in engine.Lint(self.home,self.ws,self.policy).run() if r['rule_id']=='NEW'])
        checked=gate.evaluate(self.home,self.ws,self.policy/'scan.tsv','kind\tpattern\treason\n',self.policy)
        self.assertEqual([r['path'] for r in checked if r['rule_id']=='NEW'],[str(page)])
    def test_prewrite_inventory_uses_candidate_tool_metadata(self):
        self.shipped_rules('L02','L09')
        runtime=self.home/'runtime/fixture.py';runtime.parent.mkdir();runtime.write_text('Labeled payload; never read.\n')
        page=self.home/'wiki/entities/fixture.md';page.parent.mkdir(parents=True);page.write_text(self.body('tool'))
        self.allow_current_top()
        body='home\tpage\truntime\tsource\nsystem\twiki/entities/fixture.md\truntime/fixture.py\tLabeled source\n'
        copyfile=shutil.copyfile
        def metadata_only(source,dest,*args,**kwargs):
            self.assertNotEqual(Path(source),runtime);return copyfile(source,dest,*args,**kwargs)
        with patch.object(gate.shutil,'copyfile',side_effect=metadata_only):
            self.assertEqual(gate.evaluate(self.home,self.ws,self.policy/'tools.tsv',body,self.policy),[])
    def test_prewrite_preserves_real_cross_home_link_and_supplied_layout(self):
        self.shipped_rules('LINK01')
        link='../../../../'+self.home.name+'/config/gates.md'
        original=self.body('tool','shop','# Fixture\n\n[Gate]('+link+')\n')
        for layout in ['siblings','different_parents','same_names']:
            with self.subTest(layout=layout):
                if layout!='siblings':
                    home=self.root/layout/'system-parent'/('.foxrun' if layout=='different_parents' else 'home')
                    ws=self.root/layout/'workspace-parent'/('foxrun' if layout=='different_parents' else 'home')
                    home.parent.mkdir(parents=True);ws.parent.mkdir(parents=True)
                    shutil.move(str(self.home),str(home));shutil.move(str(self.ws),str(ws))
                    self.home,self.ws=home,ws;self.policy=self.home/'config/lint'
                page=self.ws/'shop/tools/cli/dropbox-ugc.md';page.parent.mkdir(parents=True,exist_ok=True)
                gates=self.home/'config/gates.md';gates.write_text('# Gates\n\nLabeled fixture.\n')
                body=original if layout=='siblings' else original.replace(link,
                    Path(os.path.relpath(gates,page.parent)).as_posix())
                page.write_text(body);before=sha(page)
                self.assertEqual(self.run_rule('LINK01'),[])
                self.assertEqual(gate.evaluate(self.home,self.ws,page,body,self.policy),[])
                self.assertEqual(sha(page),before)
    def test_prewrite_rejects_unknown_kind_in_candidate_rules(self):
        self.shipped_rules('L02');self.allow_current_top()
        self.assertEqual(self.run_rule('L02'),[])
        rules=self.policy/'rules.tsv';before=rules.read_bytes()
        body='id\twords\tkind\tscope\tlevel\nBROKEN\tBroken\tnot_a_kind\t*:**\terror\n'
        with self.assertRaisesRegex(ValueError,'Invalid rule: BROKEN'):
            gate.evaluate(self.home,self.ws,rules,body,self.policy)
        self.assertEqual(rules.read_bytes(),before)
        # g-checks-never-block-work-except-secrets (fe36ef3): the save hook checks only secrets, so a broken rule file is not blocked there.
        result=self.hook_cli(dict(tool_name='Write',tool_input=dict(file_path=str(rules),content=body)))
        self.assertEqual((result.returncode,result.stdout),(0,''))
    def test_prewrite_rejects_malformed_candidate_spec(self):
        self.shipped_rules('L02');self.allow_current_top()
        self.assertEqual(self.run_rule('L02'),[])
        spec=self.policy/'specs/v3/tool-page/spec.tsv';before=spec.read_bytes()
        with self.assertRaisesRegex(ValueError,'Missing policy columns'):
            gate.evaluate(self.home,self.ws,spec,'broken\tvalue\nfixture\tfixture\n',self.policy)
        self.assertEqual(spec.read_bytes(),before)
    def test_prewrite_uses_candidate_top_list(self):
        self.shipped_rules('L02');self.allow_current_top()
        self.assertEqual(self.run_rule('L02'),[])
        target=self.policy/'allowed-top.tsv';before=target.read_bytes()
        findings=gate.evaluate(self.home,self.ws,target,'scope\tname\tkind\tsource\n',self.policy)
        self.assertTrue(findings);self.assertTrue(all(r['rule_id']=='L02' for r in findings))
        self.assertEqual(target.read_bytes(),before)
    def test_prewrite_copies_external_policy_and_excluded_specs_safely(self):
        self.shipped_rules('L02');self.allow_current_top()
        outside=self.root/'fixture-policy';shutil.copytree(self.policy,outside)
        protected_file=outside/'.env';protected_file.write_text('Labeled protected fixture.\n')
        copyfile=shutil.copyfile
        def safe_copy(source,dest,*args,**kwargs):
            self.assertNotEqual(Path(source),protected_file)
            return copyfile(source,dest,*args,**kwargs)
        with patch.object(gate.shutil,'copyfile',side_effect=safe_copy):
            self.assertEqual(gate.evaluate(self.home,self.ws,self.page,self.body(),outside),[])
    def test_prewrite_rejects_protected_outside_and_linked_paths(self):
        self.rule('L05','frontmatter')
        linked=self.home/'linked';linked.symlink_to(self.root,target_is_directory=True)
        for path in [self.home/'.env',self.root/'outside.md',linked/'page.md']:
            with self.subTest(path=path),self.assertRaises(ValueError):gate.evaluate(self.home,self.ws,path,'fake',self.policy)
    def test_prewrite_rejects_missing_or_linked_managed_home(self):
        self.rule('L05','frontmatter')
        missing=self.root/'absent'
        linked=self.root/'linked-home';linked.symlink_to(self.home,target_is_directory=True)
        for home in [missing,linked]:
            with self.subTest(home=home),self.assertRaises(ValueError):
                gate.evaluate(home,self.ws,home/'PAGE.md',self.body(),self.policy)
    def test_agent_edit_checks_proposed_replacement(self):
        self.rule('L05','frontmatter','system:PAGE.md')
        event=dict(tool_name='Edit',tool_input=dict(file_path=str(self.page),old_string='workspace: system',new_string='workspace: gone'))
        self.assertTrue(gate.hook(event,self.home,self.ws,self.policy))
        self.assertIn('workspace: system',self.page.read_text())
        with self.assertRaises(ValueError):gate.hook(dict(tool_name='Bash',tool_input={'command':'rm PAGE.md'}),self.home,self.ws,self.policy)
    def test_portfolio_alias_uses_workspace_rules_on_the_safe_copy(self):
        self.rule('L05', 'frontmatter', 'workspace:NOTE.md')
        original = self.ws / 'shop'
        renamed = self.ws / 'shop-hq'
        original.rename(renamed)
        original.symlink_to(renamed.name, target_is_directory=True)
        target = original / 'NOTE.md'
        target.write_text(self.body(workspace='shop'))
        self.assertEqual([], gate.evaluate(self.home, self.ws, target,
                                          self.body(workspace='shop'), self.policy))
        findings = gate.evaluate(self.home, self.ws, target,
                                 self.body(workspace='unknown'), self.policy)
        self.assertEqual(['L05'], [row['rule_id'] for row in findings])
        self.assertEqual('shop', engine.Lint(self.home, self.ws, self.policy).context(renamed / 'NOTE.md')[2])
        self.assertIn('workspace: shop', target.read_text())

    def test_portfolio_write_refuses_leave_and_return_chain(self):
        self.rule('L05', 'frontmatter', 'workspace:NOTE.md')
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'back').symlink_to(self.ws / 'shop', target_is_directory=True)
        alias = self.ws / 'chain'
        alias.symlink_to(outside / 'back', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'leaves portfolio'):
            gate.evaluate(self.home, self.ws, alias / 'NOTE.md', self.body(), self.policy)

    def hook_cli(self,event):
        for name in ['lint.py','lint_gate.py','paths.py']:
            shutil.copyfile(BASE/name,self.home/'base'/name)
        return subprocess.run([sys.executable,'-B',str(self.home/'base/lint_gate.py'),'--mode','hook',
            '--home',str(self.home),'--workspaces',str(self.ws)],input=event if isinstance(event,str) else json.dumps(event),capture_output=True,text=True)
    def assert_deny(self,result):
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout)
        self.assertEqual(set(value),{'hookSpecificOutput'})
        output=value['hookSpecificOutput']
        self.assertEqual(output['hookEventName'],'PreToolUse')
        self.assertEqual(output['permissionDecision'],'deny')
        self.assertTrue(output['permissionDecisionReason'])
    def test_hook_cli_passes_invalid_page_write(self):
        # g-checks-never-block-work-except-secrets (fe36ef3): a page finding warns elsewhere; the save hook does not deny it.
        self.rule('L05','frontmatter','system:PAGE.md');before=self.page.read_bytes()
        result=self.hook_cli(dict(tool_name='Write',tool_input=dict(file_path=str(self.page),content='# Missing Front Matter\n')))
        self.assertEqual((result.returncode,result.stdout,result.stderr),(0,'',''))
        self.assertEqual(self.page.read_bytes(),before)
    def test_hook_cli_passes_silently_for_valid_and_warning_only_writes(self):
        self.rule('L05','frontmatter','system:PAGE.md')
        event=dict(tool_name='Write',tool_input=dict(file_path=str(self.page),content=self.body()))
        result=self.hook_cli(event);self.assertEqual((result.returncode,result.stdout,result.stderr),(0,'',''))
        with (self.policy/'rules.tsv').open() as stream:
            rows=list(csv.DictReader(stream,delimiter='\t'))
        rows[0]['level']='warning'
        table(self.policy/'rules.tsv',list(rows[0]),rows)
        event['tool_input']['content']='# Warning Fixture\n'
        result=self.hook_cli(event);self.assertEqual((result.returncode,result.stdout,result.stderr),(0,'',''))
    def test_hook_cli_denies_unreadable_and_secret_events_only(self):
        # g-checks-never-block-work-except-secrets (fe36ef3): unreadable input fails closed and a secret path is denied; other events pass.
        self.rule('L05','frontmatter','system:PAGE.md')
        for event in ['{invalid json',dict(tool_name='Write',tool_input={'file_path':str(self.home/'.env'),'content':'fake fixture'})]:
            with self.subTest(event=event):self.assert_deny(self.hook_cli(event))
        for event in [[],dict(tool_name='Bash',tool_input={'command':'rm PAGE.md'})]:
            with self.subTest(event=event):self.assertEqual(self.hook_cli(event).stdout,'')
    def test_non_hook_cli_keeps_findings_list_and_failure_exit(self):
        self.rule('L05','frontmatter','system:PAGE.md')
        for name in ['lint.py','lint_gate.py','paths.py']:shutil.copyfile(BASE/name,self.home/'base'/name)
        body=self.root/'draft.md';body.write_text('# Missing Front Matter\n')
        result=subprocess.run([sys.executable,'-B',str(self.home/'base/lint_gate.py'),'--mode','write','--home',str(self.home),
            '--workspaces',str(self.ws),'--target',str(self.page),'--body',str(body)],capture_output=True,text=True)
        # g-checks-never-block-work-except-secrets (fe36ef3): write mode prints the findings list and exits 0 (warnings only).
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout))
    def test_commit_and_release_cli_propagate_failure(self):
        self.rule('L05','frontmatter','system:PAGE.md');self.page.write_text('# Broken\n')
        for mode in ['commit','release']:
            with self.subTest(mode=mode),patch.object(gate,'commit_guard'),patch.object(gate,'evaluate',return_value=[dict(level='error')]):
                self.assertEqual(gate.main(['--mode',mode,'--home',str(self.home),'--workspaces',str(self.ws)]),1)
    def test_commit_refuses_worktree_bytes_that_differ_from_index(self):
        with self.assertRaises(ValueError):
            gate.commit_guard(self.home,self.ws,self.policy,runner=lambda *a,**k:SimpleNamespace(returncode=1,stdout=''))
    def test_commit_refuses_untracked_managed_link_targets(self):
        self.rule('L05','frontmatter','system:PAGE.md')
        calls=iter([SimpleNamespace(returncode=0),SimpleNamespace(returncode=0,stdout=str(self.page)+'\0')])
        with self.assertRaises(ValueError):
            gate.commit_guard(self.home,self.ws,self.policy,runner=lambda *a,**k:next(calls))
    def visual_receipts(self):
        css=self.home/'config/lint/brand.css';script=self.home/'base/lint_render.py'
        image=self.home/'runs/fixture-image.png';image.parent.mkdir();image.write_bytes(b'Labeled synthetic screenshot fixture; not live proof.')
        rows=[dict(home='system',page='PAGE.md',source_sha256=sha(self.page),renderer_sha256=hashlib.sha256(script.read_bytes()+css.read_bytes()).hexdigest(),width=str(w),overflow='0',status='pass',reviewer='SYNTHETIC FIXTURE',image='runs/fixture-image.png',image_sha256=sha(image)) for w in (390,1440)]
        table(self.policy/'visual-reviews.tsv',list(rows[0]),rows)
        return image
    def visual_copy_regression(self,mode):
        if mode=='clean':self.shipped_rules('L02','L13')
        image=self.visual_receipts()
        if mode!='clean':
            moved=self.home/'history/visual/fixture-image.png';moved.parent.mkdir(parents=True)
            image.rename(moved);image=moved
            ledger=self.policy/'visual-reviews.tsv'
            ledger.write_text(ledger.read_text().replace('runs/fixture-image.png','history/visual/fixture-image.png'))
        if mode=='missing':image.unlink()
        elif mode=='changed':image.write_bytes(b'Changed synthetic fixture.')
        unrelated=image.parent/'unrelated.png';unrelated.write_bytes(b'Unrelated labeled fixture; never read.')
        secret=self.home/'.env/fixture.png';secret.parent.mkdir();secret.write_bytes(b'Protected labeled fixture; never read.')
        ledger=self.policy/'visual-reviews.tsv'
        with ledger.open() as stream:rows=list(csv.DictReader(stream,delimiter='\t'))
        unused=dict(rows[0],page='UNSELECTED.md',image='.env/fixture.png')
        table(ledger,list(rows[0]),rows+[unused])
        self.allow_current_top()
        before=self.page.read_bytes();image_before=image.read_bytes() if image.exists() else None
        direct=engine.Lint(self.home,self.ws,self.policy).run()
        copyfile=shutil.copyfile;read_bytes=Path.read_bytes;copied=[]
        def selected_copy(source,dest,*args,**kwargs):
            source=Path(source);self.assertNotIn(source,[unrelated,secret]);self.assertFalse(engine.protected(source))
            result=copyfile(source,dest,*args,**kwargs)
            if source==image:
                self.assertEqual(sha(source),sha(Path(dest)));copied.append(source)
            return result
        def selected_read(source,*args,**kwargs):
            self.assertNotIn(source,[unrelated,secret]);self.assertFalse(engine.protected(source))
            return read_bytes(source,*args,**kwargs)
        with patch.object(gate.shutil,'copyfile',side_effect=selected_copy),patch.object(Path,'read_bytes',selected_read):
            checked=gate.evaluate(self.home,self.ws,self.page,self.page.read_text(),self.policy)
        wanted=[r for r in direct if r['rule_id']=='L13' and r['path']==str(self.page)]
        got=[r for r in checked if r['rule_id']=='L13' and r['path']==str(self.page)]
        self.assertEqual(got,[])  # An unchanged write adds no visual-review finding.
        self.assertEqual(len(wanted),0 if mode in ('clean','full') else 2)
        self.assertEqual(self.page.read_bytes(),before)
        self.assertEqual(image.read_bytes() if image.exists() else None,image_before)
        self.assertEqual(copied,[])
        return checked,direct
    def test_prewrite_preserves_visual_reviews_with_clean_shipped_rules(self):
        self.visual_copy_regression('clean')
    def test_prewrite_preserves_visual_reviews_with_full_shipped_rules(self):
        self.visual_copy_regression('full')
    def test_prewrite_missing_visual_image_still_fails(self):
        self.visual_copy_regression('missing')
    def test_prewrite_changed_visual_image_still_fails(self):
        self.visual_copy_regression('changed')
    def test_l13_requires_exact_current_visual_reviews(self):
        self.rule('L13','brand_page','system:PAGE.md')
        self.assertEqual(len(self.run_rule('L13')),2)
        image=self.visual_receipts();self.assertEqual(self.run_rule('L13'),[])
        image.write_bytes(b'changed');self.assertEqual(len(self.run_rule('L13')),2)
    def test_l13_source_css_and_renderer_changes_invalidate_review(self):
        self.rule('L13','brand_page','system:PAGE.md');self.visual_receipts()
        css=self.home/'config/lint/brand.css';original=css.read_text()
        css.write_text(original+'\n/* Changed style. */\n')
        self.assertEqual(len(self.run_rule('L13')),2)
        css.write_text(original)
        script=self.home/'base/lint_render.py';original_script=script.read_text()
        script.write_text(original_script+'\n# Changed renderer.\n')
        self.assertEqual(len(self.run_rule('L13')),2)
        script.write_text(original_script)
        self.page.write_text(self.body(body='# Example\n\nChanged fact.\n'))
        self.assertEqual(len(self.run_rule('L13')),2)
    def test_prewrite_blocks_new_visual_review_findings(self):
        self.rule('L13','brand_page','system:PAGE.md');self.visual_receipts()
        body=self.body(body='# Example\n\nChanged fact.\n')
        rows=gate.evaluate(self.home,self.ws,self.page,body,self.policy)
        self.assertEqual(len(rows),2)
        self.assertTrue(all('Missing current visual review' in r['what'] for r in rows))
    def test_l13_brand_copy_and_headings_fail(self):
        self.rule('L13','brand_page','system:PAGE.md');self.page.write_text(self.body(body='# lowercase\n\nUnlock potential.\n'))
        self.assertTrue(any('lowercase' in r['what'] for r in self.run_rule('L13')))
        self.assertTrue(any('prohibited' in r['what'] for r in self.run_rule('L13')))
    def test_renderer_keeps_html_and_executable_urls_inert(self):
        result=renderer.render('# Example\n\n<script>alert(1)</script>\n\n[bad](javascript:alert)\n\n| A | B |\n|---|---|\n| a | b |\n','/* fixture */')
        self.assertNotIn('<script>',result);self.assertNotIn('href="javascript:',result)
        self.assertIn('class="table-scroll"',result);self.assertIn('name="viewport"',result)
    def test_actual_skill_entry_runs_handler_without_system_lint(self):
        # T738: a ship runs the skill's own checks; skill_ship.py no longer runs the system-wide lint first.
        tree=ast.parse((self.home/'skillwright/tools/skill_ship.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        namespace={'parser':lambda:SimpleNamespace(parse_args=lambda:SimpleNamespace(command='publish',handler=lambda args:0)),
                   'Path':Path,'__file__':str(self.home/'skillwright/tools/skill_ship.py'),'subprocess':subprocess,'sys':sys,'json':json}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-release-main','exec'),namespace)
        with patch.object(subprocess,'run',side_effect=AssertionError('the system lint ran')) as run:
            self.assertEqual(namespace['main'](),0)
        run.assert_not_called()

if __name__=='__main__':unittest.main()
