"""Standard-library test fixtures for the preserved function assertions."""
from __future__ import annotations
import contextlib
import importlib
import inspect
import io
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

class MonkeyPatch:
    def __init__(self): self.stack=contextlib.ExitStack()
    def setattr(self,target,name,value=None,raising=True):
        if isinstance(target,str):
            module,attribute=target.rsplit('.',1)
            if value is None: value=name
            target=importlib.import_module(module); name=attribute
        self.stack.enter_context(mock.patch.object(target,name,value,create=not raising))
    def setenv(self,name,value): self.stack.enter_context(mock.patch.dict(os.environ,{name:str(value)}))
    def delenv(self,name,raising=True):
        if raising and name not in os.environ: raise KeyError(name)
        old=os.environ.pop(name,None)
        if old is not None: self.stack.callback(os.environ.__setitem__,name,old)
    def undo(self): self.stack.close()

class Capture:
    def __init__(self): self.out=io.StringIO(); self.err=io.StringIO()
    def readouterr(self):
        result=SimpleNamespace(out=self.out.getvalue(),err=self.err.getvalue())
        self.out.seek(0); self.out.truncate(); self.err.seek(0); self.err.truncate()
        return result

@contextlib.contextmanager
def raises(error,match=None):
    try: yield
    except error as exc:
        if match is not None and re.search(match,str(exc)) is None:
            raise AssertionError('exception did not match '+repr(match)+': '+str(exc))
    else: raise AssertionError('expected '+error.__name__)

def function_suite(namespace,parameters=None):
    suite=unittest.TestSuite(); parameters=parameters or {}
    for name,func in sorted(namespace.items()):
        if not name.startswith('test_') or not inspect.isfunction(func): continue
        variants=parameters.get(name,[{}])
        for index,variant in enumerate(variants):
            def run(func=func,variant=variant):
                with tempfile.TemporaryDirectory(prefix='agent-test-') as temp, contextlib.ExitStack() as stack:
                    monkeypatch=MonkeyPatch(); stack.callback(monkeypatch.undo)
                    capture=Capture()
                    stack.enter_context(contextlib.redirect_stdout(capture.out))
                    stack.enter_context(contextlib.redirect_stderr(capture.err))
                    args={'tmp_path':Path(temp).resolve(),'monkeypatch':monkeypatch,'capsys':capture,**variant}
                    if 'world' in inspect.signature(func).parameters:
                        args['world']=namespace['world'](args['tmp_path'],monkeypatch)
                    func(**{key:args[key] for key in inspect.signature(func).parameters})
            run.__name__=name+('['+str(index)+']' if len(variants)>1 else '')
            suite.addTest(unittest.FunctionTestCase(run,description=run.__name__))
    return suite
