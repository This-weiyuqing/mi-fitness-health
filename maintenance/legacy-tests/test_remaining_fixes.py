"""隔离回归：不使用真实账号、不访问 NAS 或云端。"""
import asyncio
import base64
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/mi-fitness-mcp-cn/src'))
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.models import BodyMeasurement
from mi_fitness_mcp.storage import Database
from mi_fitness_mcp.web import create_app


def basic(password):
    return {'Authorization': 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()}


@pytest.mark.parametrize('path,method', [('/', 'get'), ('/api/proxy_status', 'get'),
    ('/proxy/api/auth/keys', 'get'), ('/proxy/api/auth/keys/mif_sk_demo', 'delete')])
def test_web_requires_browser_auth_before_injecting_admin(path, method):
    client = create_app(admin_key='synthetic-admin').test_client()
    result = getattr(client, method)(path)
    assert result.status_code == 401
    assert 'Basic' in result.headers['WWW-Authenticate']


def test_authenticated_browser_admin_proxy_keeps_credentials_local(monkeypatch):
    monkeypatch.setenv('MI_FITNESS_WEB_PASSWORD', 'synthetic-web-password')
    captured = []
    class Client:
        def __init__(self, **kwargs): pass
        def request(self, **kwargs):
            captured.append(kwargs)
            return httpx.Response(200, json={'status': 'ok'})
    monkeypatch.setattr('mi_fitness_mcp.web.httpx.Client', Client)
    client = create_app(admin_key='synthetic-admin').test_client()
    assert client.get('/', headers=basic('synthetic-admin')).status_code == 401
    result = client.get('/proxy/api/auth/keys', headers=basic('synthetic-web-password'))
    assert result.status_code == 200
    assert captured[0]['headers']['X-Admin-Key'] == 'synthetic-admin'
    assert not any(key.lower() == 'authorization' for key in captured[0]['headers'])
    assert result.headers.get('Cache-Control') == 'no-store'
    response = client.delete('/proxy/api/auth/keys/demo', headers={**basic('synthetic-web-password'), 'Origin': 'https://untrusted.example'})
    assert response.status_code == 403
    assert len(captured) == 1


def test_explicit_https_origin_supports_tls_termination_without_trusting_forwarded_headers(monkeypatch):
    monkeypatch.setenv('MI_FITNESS_WEB_ORIGIN', 'https://health.example')
    client = create_app(admin_key='synthetic-admin').test_client()
    assert client.get('/', headers={**basic('synthetic-admin'), 'Origin': 'https://health.example'}).status_code == 200
    assert client.get('/', headers={**basic('synthetic-admin'), 'Origin': 'https://other.example',
        'X-Forwarded-Host': 'other.example', 'X-Forwarded-Proto': 'https'}).status_code == 403


def test_stale_health_api_key_does_not_lock_browser_out_of_reauthorization(monkeypatch):
    captured = []
    class Client:
        def __init__(self, **kwargs): pass
        def request(self, **kwargs):
            captured.append(kwargs)
            return httpx.Response(200, json={})
    monkeypatch.setattr('mi_fitness_mcp.web.httpx.Client', Client)
    client = create_app(admin_key='synthetic-admin').test_client()
    headers = {**basic('synthetic-admin'), 'X-API-Key': 'mif_sk_revoked'}
    client.post('/proxy/api/auth/qr/start', headers=headers)
    assert not any(key.lower() == 'x-api-key' for key in captured[0]['headers'])
    assert captured[0]['headers']['X-Admin-Key'] == 'synthetic-admin'
    client.get('/proxy/api/summary', headers=headers)
    assert any(key.lower() == 'x-api-key' and value == 'mif_sk_revoked' for key, value in captured[1]['headers'].items())


def test_body_measurement_later_sync_updates_all_body_fields(tmp_path):
    db = Database(tmp_path / 'synthetic.sqlite')
    item = BodyMeasurement(id='synthetic', provider='mi_fitness', source_type='cloud_session',
        user_id='synthetic', timestamp=datetime(2026, 10, 15, 9, tzinfo=timezone.utc), weight_kg=87.3)
    db.insert_body_measurement(item)
    additions = {'bone_mass_kg': 3.1, 'visceral_fat_score': 9, 'basal_metabolism_kcal': 1800, 'metabolic_age': 30}
    db.insert_body_measurement(item.model_copy(update=additions))
    result = db.query_body_measurements('synthetic', '2026-10-15', '2026-10-15')[0]
    assert {key: result[key] for key in additions} == additions


@pytest.mark.parametrize('method,list_name', [('_fetch_key', 'data_list'), ('_fetch_sport_records_by_time', 'sport_records')])
@pytest.mark.parametrize('bad_cursor', [None, '', 123])
def test_incomplete_pagination_fails_instead_of_succeeding(monkeypatch, method, list_name, bad_cursor):
    adapter = MiFitnessCloudAdapter(user_id='synthetic', pass_token='synthetic', region='cn')
    calls = []
    async def request(*args):
        calls.append(args)
        return {list_name: [], 'has_more': True, 'next_key': bad_cursor}
    monkeypatch.setattr(adapter, '_request', request)
    args = ('heart_rate', '2026-10-15', '2026-10-16') if method == '_fetch_key' else ('2026-10-15', '2026-10-16')
    with pytest.raises(ValueError, match='pagination cursor'):
        asyncio.run(getattr(adapter, method)(*args))
    assert len(calls) == 1


@pytest.mark.parametrize('method,list_name', [('_fetch_key', 'data_list'), ('_fetch_sport_records_by_time', 'sport_records')])
def test_valid_pagination_returns_all_pages(monkeypatch, method, list_name):
    adapter = MiFitnessCloudAdapter(user_id='synthetic', pass_token='synthetic', region='cn')
    async def request(base, path, payload):
        if payload.get('next_key') == 'page2':
            return {list_name: [{'id': 2}], 'has_more': False}
        return {list_name: [{'id': 1}], 'has_more': True, 'next_key': 'page2'}
    monkeypatch.setattr(adapter, '_request', request)
    args = ('heart_rate', '2026-10-15', '2026-10-16') if method == '_fetch_key' else ('2026-10-15', '2026-10-16')
    assert asyncio.run(getattr(adapter, method)(*args)) == [{'id': 1}, {'id': 2}]


@pytest.mark.parametrize('method,list_name', [('_fetch_key', 'data_list'), ('_fetch_sport_records_by_time', 'sport_records')])
def test_missing_record_list_is_not_treated_as_empty_success(monkeypatch, method, list_name):
    adapter = MiFitnessCloudAdapter(user_id='synthetic', pass_token='synthetic', region='cn')
    async def request(*args):
        return {'has_more': False}
    monkeypatch.setattr(adapter, '_request', request)
    args = ('heart_rate', '2026-10-15', '2026-10-16') if method == '_fetch_key' else ('2026-10-15', '2026-10-16')
    with pytest.raises(ValueError, match='response'):
        asyncio.run(getattr(adapter, method)(*args))


def test_concurrent_qr_polls_issue_only_one_key(monkeypatch):
    import time
    from types import SimpleNamespace
    from starlette.requests import Request
    from mi_fitness_mcp import api
    monkeypatch.setenv('MI_FITNESS_ADMIN_KEY', 'synthetic-admin')
    state = SimpleNamespace(db=None, qr_sessions={'qr': {'status': 'waiting', 'lp': 'http://synthetic.invalid',
        'created_at': time.time(), 'expires_in': 300, 'region': 'cn'}})
    request = Request({'type': 'http', 'headers': [(b'x-admin-key', b'synthetic-admin')],
        'app': SimpleNamespace(state=state)})
    keys = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args):
            await asyncio.sleep(0.01)
            return httpx.Response(200, json={'code': 0, 'userId': 'synthetic', 'passToken': 'synthetic'})
    def create(*args):
        key = 'synthetic-' + str(len(keys))
        keys.append(key)
        return key
    monkeypatch.setattr(api.httpx, 'AsyncClient', Client)
    monkeypatch.setattr(api, '_create_key_record', create)
    async def polls():
        return await asyncio.gather(api.qr_poll('qr', request), api.qr_poll('qr', request))
    results = asyncio.run(polls())
    assert len(keys) == 1
    assert results[0]['api_key'] == results[1]['api_key']
