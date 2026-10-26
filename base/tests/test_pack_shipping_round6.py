"""The installer refuses excluded business packs and loads only default core packs."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
from base.tests.support import shipped_paths
_fox_test_setup()
import json
from pathlib import Path
import tempfile
import unittest
from base import install_workspace as installer
ROOT=Path(__file__).resolve().parents[2]
class PackShipping(unittest.TestCase):
    def test_default_core_and_excluded_packs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(); target=root/'target'; live=root/'live';target.mkdir();live.mkdir()
            values={}
            for module in installer.BASE_MODULES:
                manifest,_=installer.load_manifest(ROOT,module)
                for entry in manifest['files']:
                    for key in installer.PLACEHOLDER.findall((ROOT/module/entry['from']).read_text()): values[key]='fixture-'+key
            values.pop('approved_tags',None)
            values.pop('timestamp',None)
            values.update({'workspace':'cedar-shop','workspace_purpose':'A made-up shop'})
            plan=installer.plan_install(modules_root=ROOT,target=target,live_vault=live,
                workspace_type='personal',raw_modules=','.join(sorted(installer.BASE_MODULES)),
                values=values,
                target_workspace='cedar-shop',install_timestamp='2026-01-01T00:00:00Z',
                approved_tags=[],database=None,actor=None)
            self.assertEqual(set(plan['modules']),installer.BASE_MODULES)
            self.assertFalse(set(plan['modules']) & {'design','amazon','commerce','ugc','tiktok-shop','treasury'})
        listed = {path.relative_to(ROOT).as_posix() for path in shipped_paths(ROOT)}
        for pack in ('design','amazon','commerce','ugc','tiktok-shop','treasury'):
            file=installer.pack_policy.manifest_path(ROOT,pack)
            # g-business-packs-do-not-ship (44cee23): local add-ons are not core fixtures.
            if file.relative_to(ROOT).as_posix() not in listed: continue
            self.assertIs(json.loads(file.read_text()).get('ships'),False)
            with self.assertRaisesRegex(installer.InstallError,'not shipped'): installer.load_manifest(ROOT,pack)
    def test_local_pack_outside_product_manifest_is_not_shipped(self):
        # 231264d / g-business-packs-do-not-ship: local packs are outside the core manifest.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            local = root / 'modules/commerce'
            local.mkdir(parents=True)
            (local / 'install.json').write_text('{"ships": true}\n')
            (root / 'base').mkdir()
            (root / 'base/product-manifest.tsv').write_text('path\tbytes\tsha256\n')
            self.assertEqual(installer.pack_policy.shipped_names(root, ['commerce', 'wiki']), ['wiki'])
    def test_private_identifiers_absent_in_core(self):
        # g-people-ships-with-small-talk (231264d): inspect shipped paths, never a person's local packs.
        for path in shipped_paths(ROOT):
            if not path.is_file() or 'tests' in path.parts or path.suffix=='.gz': continue
            try: text=path.read_text()
            except UnicodeError: continue
            from base.tests.privacy_support import account_name
            for name in (account_name() + '_confirmation', 'ask_' + account_name()):
                self.assertNotIn(name,text,str(path))
