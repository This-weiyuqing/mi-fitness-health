import importlib.util
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/mi-fitness-mcp-cn/src'))
from mi_fitness_mcp.services.query_service import QueryService


@pytest.mark.parametrize('method',['_aggregate_by_week','_aggregate_by_month'])
def test_latest_aggregation_uses_latest_date_instead_of_sum(method):
    service=QueryService(None,'synthetic')
    result=getattr(service,method)([{'date':'2026-10-16','value':9},{'date':'2026-10-15','value':2}],'latest')
    assert result[0]['value']==9


def runtime():
    spec=importlib.util.spec_from_file_location('audit_runtime',ROOT/'outputs/nas-deployment/runtime.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_repeated_login_for_same_account_keeps_sync_but_multiple_accounts_are_rejected(tmp_path):
    db=tmp_path/'health.sqlite'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE api_keys (key TEXT,user_id TEXT,region TEXT,created_at TEXT,revoked INTEGER)')
        c.executemany('INSERT INTO api_keys VALUES (?,?,?,?,0)',[('old','owner','cn','2026-10-15'),('new','owner','cn','2026-10-16')])
    assert runtime().load_single_key(db)=='new'
    with sqlite3.connect(db) as c:c.execute("INSERT INTO api_keys VALUES ('other','another-owner','cn','2026-10-17',0)")
    with pytest.raises(RuntimeError):runtime().load_single_key(db)


def test_cached_credential_does_not_repeat_expensive_unlock_or_bypass_revocation(tmp_path,monkeypatch):
    from mi_fitness_mcp import api
    from mi_fitness_mcp.storage import Database
    from starlette.requests import Request

    db=Database(tmp_path/'health.sqlite')
    with db._get_connection() as c:
        c.execute('CREATE TABLE api_keys (key TEXT,user_id TEXT,region TEXT,pass_token TEXT,revoked INTEGER,last_used_at TEXT)')
        c.execute("INSERT INTO api_keys VALUES ('synthetic-key','owner','cn','',0,NULL)")
        c.commit()
    state=SimpleNamespace(default_context=None,db=db,config=None,contexts={},key_contexts={},key_context_lock=threading.RLock())
    request=Request({'type':'http','headers':[(b'x-api-key',b'synthetic-key')],'app':SimpleNamespace(state=state)})
    calls=[]
    clock=[100.0]
    monkeypatch.setattr(api,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    def unlock(key):
        calls.append(key)
        time.sleep(0.05)
        return 'synthetic-account-token'
    monkeypatch.setattr(api,'load_api_key_secret',unlock)
    monkeypatch.setattr(api,'_build_context',lambda *args:SimpleNamespace(query_service=object()))
    barrier=threading.Barrier(2)
    def resolve():
        barrier.wait()
        return api._resolve_context(request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _:resolve(),range(2)))
    assert len(calls)==1, '每个请求都执行昂贵的密钥环解锁，概览五个请求被串行拖慢'
    clock[0]+=61
    api._resolve_context(request)
    assert len(calls)==2, '短期缓存到期后必须重新读取密钥环'
    with db._get_connection() as c:
        c.execute("UPDATE api_keys SET revoked=1 WHERE key='synthetic-key'");c.commit()
    with pytest.raises(api.HTTPException):api._resolve_context(request)
    state.default_context=SimpleNamespace(query_service=object())
    bad=Request({'type':'http','headers':[(b'x-api-key',b'unknown-key')],'app':SimpleNamespace(state=state)})
    with pytest.raises(api.HTTPException):api._resolve_context(bad)


@pytest.mark.asyncio
async def test_ambiguous_key_prefix_cannot_revoke_multiple_authorizations(tmp_path,monkeypatch):
    from mi_fitness_mcp import api
    from mi_fitness_mcp.storage import Database
    from starlette.requests import Request
    db=Database(tmp_path/'keys.sqlite')
    with db._get_connection() as c:
        c.execute('CREATE TABLE api_keys (key TEXT,revoked INTEGER)')
        c.executemany('INSERT INTO api_keys VALUES (?,0)',[('mif_sk_abcde0000',),('mif_sk_abcde1111',)])
        c.commit()
    deleted=[]
    monkeypatch.setattr(api,'_require_admin',lambda request:None)
    monkeypatch.setattr(api,'delete_api_key_secret',deleted.append)
    request=Request({'type':'http','headers':[],'app':SimpleNamespace(state=SimpleNamespace(db=db))})
    with pytest.raises(api.HTTPException) as error:
        await api.revoke_key('mif_sk_abcde',request)
    assert error.value.status_code==409
    assert not deleted
    with db._get_connection() as c:assert c.execute('SELECT sum(revoked) FROM api_keys').fetchone()[0]==0
