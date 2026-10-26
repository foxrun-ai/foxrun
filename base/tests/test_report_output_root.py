"""Report storage can change without changing the workspace row scope."""
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import workspace_reports as reports

class Source:
    tables={'activity'}
    workspace='foxrun-dev'
    def __init__(self,path):self.path=path
    def rows(self,name):
        return [{'id':1,'at':'2026-10-16T12:00:00Z','verb':'checked','subject_type':'task','subject_id':'T1'}] if name=='activity' else []

class ReportOutputTests(unittest.TestCase):
    def test_output_root_routes_both_ops_and_history_and_keeps_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);dev=root/'foxrun-dev';hq=root/'foxrun-hq'
            source=Source(root/'data.db')
            pages,_=reports.render(dev,source,'2026-10-17',output_root=hq)
            self.assertTrue(all(path.is_relative_to(hq) for path in pages))
            self.assertIn(hq/'ops/DASHBOARD.md',pages)
            self.assertIn(hq/'history/LOG.md',pages)
            self.assertIn('workspace: foxrun-dev',pages[hq/'ops/DASHBOARD.md'])
            self.assertIn('workspace: foxrun-dev',pages[hq/'history/LOG.md'])

    def test_frozen_daily_manifest_is_read_from_output_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);dev=root/'foxrun-dev';hq=root/'foxrun-hq';source=Source(root/'data.db')
            first,_=reports.render(dev,source,'2026-10-17',output_root=hq)
            for path,body in first.items():path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body)
            second,_=reports.render(dev,source,'2026-10-18',output_root=hq)
            self.assertEqual(first[hq/'history/daily/2026-10-16.md'],second[hq/'history/daily/2026-10-16.md'])

    def test_default_root_keeps_existing_business_behavior(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);workspace=root/'sample-shop'
            pages,_=reports.render(workspace,Source(root/'data.db'),'2026-10-17')
            self.assertTrue(all(path.is_relative_to(workspace) for path in pages))

if __name__=='__main__':unittest.main()
