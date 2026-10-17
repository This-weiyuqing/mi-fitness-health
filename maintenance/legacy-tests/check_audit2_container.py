"""对本机隔离 Linux 容器做鉴权及持久化验收。"""
import json
import sqlite3
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]
with httpx.Client(base_url='http://127.0.0.1:18372', trust_env=False, timeout=20) as client:
    assert client.get('/').status_code == 401
    assert client.get('/proxy/api/auth/keys').status_code == 401
    assert client.get('/', auth=('admin', 'wrong')).status_code == 401
    client.auth = ('admin', 'synthetic-web-for-local-test')
    page = client.get('/')
    assert page.status_code == 200 and '20261016-ui2' in page.text
    response = client.get('/proxy/api/summary', params={'start_date': '2026-10-15', 'end_date': '2026-10-15'},
        headers={'X-API-Key': 'mif_sk_syntheticlocal'})
    assert response.status_code == 200, response.status_code
    assert response.json()['data'][0]['steps'] == 4691
    assert response.json()['data'][0]['active_kcal'] == 596
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/proxy/api/auth/keys').status_code == 200
    assert client.get('/proxy/api/auth/keys', headers={'X-API-Key': 'mif_sk_invalid'}).status_code == 200
    assert client.delete('/proxy/api/auth/keys/mif_sk_syntheticlocal', headers={'Origin': 'https://untrusted.invalid'}).status_code == 403
    assert client.get('/proxy/api/summary', params={'start_date': '2026-10-15', 'end_date': '2026-10-15'},
        headers={'X-API-Key': 'mif_sk_invalid'}).status_code == 401
with sqlite3.connect(ROOT / 'work/audit2-container-validation/state/data/mi_fitness.db') as conn:
    assert conn.execute("SELECT count(*) FROM api_keys WHERE pass_token!=''").fetchone()[0] == 0
    assert conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
print(json.dumps({'browser_auth': 'ok', 'query': 'ok', 'csrf_block': 'ok', 'invalid_api_key': 'denied',
    'sqlite_integrity': 'ok', 'sqlite_plaintext_tokens': 0, 'fixture': 'synthetic only'}, indent=2))
