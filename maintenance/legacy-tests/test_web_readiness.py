"""本机模拟容器切换时的短暂连接重置，不访问 NAS。"""
import importlib.util
from pathlib import Path
import urllib.error

import pytest

def helper():
    path=Path(__file__).resolve().parents[2]/'outputs/frontend-performance-fix/wait-web-ready.py'
    assert path.exists(), '更新就绪检查缺少容错重试'
    spec=importlib.util.spec_from_file_location('web_ready',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

class Response:
    status=200
    def __init__(self,body): self.body=body
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,*args): return self.body

def test_readiness_retries_connection_reset_and_stale_page():
    outcomes=[ConnectionResetError(),Response(b'old-ui'),Response(b'20261017-ui3')]
    class Opener:
        def open(self,*args,**kwargs):
            value=outcomes.pop(0)
            if isinstance(value,Exception): raise value
            return value
    helper().wait_for_ready(Opener(),object(),pause=lambda seconds:None)
    assert not outcomes

def test_readiness_has_bounded_failure():
    calls=[]
    class Opener:
        def open(self,*args,**kwargs):
            calls.append(1);raise ConnectionResetError()
    with pytest.raises(RuntimeError,match='就绪'):
        helper().wait_for_ready(Opener(),object(),attempts=3,pause=lambda seconds:None)
    assert len(calls)==3

def test_bad_password_is_not_treated_as_slow_startup():
    class Opener:
        def open(self,*args,**kwargs):
            raise urllib.error.HTTPError('http://local',401,'denied',{},None)
    with pytest.raises(RuntimeError,match='鉴权'):
        helper().wait_for_ready(Opener(),object(),pause=lambda seconds:None)
