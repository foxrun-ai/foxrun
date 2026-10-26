"""Privacy test patterns use the host identity or explicit audit input."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import json
import os
from pathlib import Path
import pwd
import re


def patterns():
    path = os.environ.get('FOXRUN_TEST_AUDIT_PATTERNS')
    if path:
        return json.loads(Path(path).read_text())
    account = pwd.getpwuid(os.getuid())
    names = [account.pw_name, account.pw_dir]
    names.extend(re.split(r'[ ._-]+', account.pw_name))
    return [('owner', '|'.join(re.escape(name) for name in names if len(name) > 2))]


def account_name():
    return re.split(r'[ ._-]+', pwd.getpwuid(os.getuid()).pw_name)[0]
