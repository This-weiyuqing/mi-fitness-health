import gzip
import importlib.util
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

RUNTIME = Path(__file__).resolve().parents[2] / 'outputs/nas-deployment/runtime.py'


def runtime():
    assert RUNTIME.exists(), '缺少部署运行支持：安全归档、断线补偿和备份'
    spec = importlib.util.spec_from_file_location('deployment_runtime', RUNTIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_preserves_health_versions_but_rejects_auth_endpoints(tmp_path):
    m = runtime()
    for steps in (1000, 1100):
        m.archive_response(tmp_path, '/app/v1/data/get_aggregated_fitness_data_by_time', {'key': 'steps'}, {'steps': steps})
    files = list(tmp_path.glob('*.jsonl.gz'))
    assert len(files) == 1
    with gzip.open(files[0], 'rt', encoding='utf-8') as f:
        assert [json.loads(line)['result']['steps'] for line in f] == [1000, 1100]
    with pytest.raises(ValueError):
        m.archive_response(tmp_path, '/pass/serviceLoginAuth2', {}, {'passToken': 'never-archive'})
    assert len(list(tmp_path.glob('*'))) == 1


def test_failed_sync_never_moves_success_cursor_and_recovery_covers_gap():
    m = runtime()
    state = {'last_success_date': '2026-10-01'}
    assert m.sync_start(state, date(2026, 10, 16)) == '2026-09-29'
    m.finish_sync(state, {'status': 'partial'}, date(2026, 10, 16))
    assert state['last_success_date'] == '2026-10-01'
    m.finish_sync(state, {'status': 'ok'}, date(2026, 10, 16))
    assert state['last_success_date'] == '2026-10-16'


def test_online_backup_restores_without_credentials_and_without_touching_original(tmp_path):
    m = runtime()
    source = tmp_path / 'live.sqlite'
    with sqlite3.connect(source) as c:
        c.execute('CREATE TABLE daily_activity (steps INTEGER)')
        c.execute('INSERT INTO daily_activity VALUES (1000)')
        c.execute('CREATE TABLE api_keys (key TEXT, pass_token TEXT)')
        c.execute("INSERT INTO api_keys VALUES ('test-api-key', 'test-account-token')")
    backup = m.backup_database(source, tmp_path / 'backups')
    with sqlite3.connect(backup) as c:
        assert c.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        assert c.execute('SELECT steps FROM daily_activity').fetchone()[0] == 1000
        assert c.execute('SELECT count(*) FROM api_keys').fetchone()[0] == 0
    with sqlite3.connect(source) as c:
        assert c.execute('SELECT count(*) FROM api_keys').fetchone()[0] == 1


def test_worker_recovers_after_network_failure_without_losing_gap(tmp_path, monkeypatch):
    import httpx

    m = runtime()
    m.STATE = tmp_path
    db = tmp_path / 'data/mi_fitness.db'
    db.parent.mkdir()
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE daily_activity (steps INTEGER)')
        c.execute('CREATE TABLE api_keys (key TEXT, revoked INTEGER, user_id TEXT, region TEXT, created_at TEXT)')
        c.execute("INSERT INTO api_keys VALUES ('synthetic-key',0,'synthetic-user','cn','2026-10-01')")
    status_file = tmp_path / 'automation/status.json'
    m.atomic_json(status_file, {'last_success_date':'2026-10-01'})
    original_client = httpx.Client
    offline = True
    observed_starts = []

    def respond(request):
        if offline:
            raise httpx.ConnectError('synthetic offline', request=request)
        if request.method == 'POST':
            observed_starts.append(json.loads(request.content)['start_date'])
            return httpx.Response(200, json={'sync_id':'synthetic-task','status':'accepted'})
        return httpx.Response(200, json={'status':'ok'})

    class StopWorker(Exception):
        pass

    def sleep(seconds):
        if seconds in (300,1800):
            raise StopWorker()

    monkeypatch.setattr(httpx,'Client',lambda **kw: original_client(transport=httpx.MockTransport(respond),**kw))
    monkeypatch.setattr(m.time,'sleep',sleep)
    with pytest.raises(StopWorker):
        m.worker()
    failed=json.loads(status_file.read_text(encoding='utf-8'))
    assert failed['status']=='error' and failed['last_success_date']=='2026-10-01'
    offline=False
    with pytest.raises(StopWorker):
        m.worker()
    recovered=json.loads(status_file.read_text(encoding='utf-8'))
    assert recovered['status']=='ok' and recovered['last_success_date']!='2026-10-01'
    assert observed_starts==['2026-09-29']
