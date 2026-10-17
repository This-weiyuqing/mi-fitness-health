"""部署补充：复用上游同步与查询，增加归档、凭据保护及定时维护。"""

import gzip
import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

STATE = Path(os.environ.get('HEALTH_STATE', '/state'))
HEALTH_PATHS = {
    '/app/v1/data/get_fitness_data_by_time',
    '/app/v1/data/get_aggregated_fitness_data_by_time',
    '/app/v1/data/get_sport_records_by_time',
}


def archive_response(directory, api_path, arguments, result):
    if api_path not in HEALTH_PATHS:
        raise ValueError('拒绝归档非健康数据接口')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    record = {'received_at': now.isoformat(), 'path': api_path, 'arguments': arguments, 'result': result}
    with gzip.open(directory / (now.date().isoformat() + '.jsonl.gz'), 'at', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')


def sync_start(state, today):
    # 留三天重叠窗口；离线后从上次完整成功前开始补齐，不只取最近几天。
    last = state.get('last_success_date')
    return (date.fromisoformat(last) - timedelta(days=2) if last else today - timedelta(days=29)).isoformat()


def finish_sync(state, result, today):
    state['last_attempt_at'] = datetime.now(timezone.utc).isoformat()
    state['status'] = result.get('status', 'error')
    if result.get('status') == 'ok':
        state['last_success_date'] = today.isoformat()
        state.pop('error_type', None)


def backup_database(source, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = directory / ('health-' + stamp + '.sqlite')
    pending = target.with_suffix('.pending')
    with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(pending)) as dst:
            src.backup(dst)
            dst.execute('PRAGMA secure_delete=ON')
            if dst.execute("SELECT 1 FROM sqlite_master WHERE name='api_keys'").fetchone():
                dst.execute('DELETE FROM api_keys')
            dst.commit()
            dst.execute('VACUUM')
            if dst.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('备份完整性检查失败')
    pending.replace(target)
    # 保留最近 30 份每日备份；只处理本程序命名的备份文件。
    for old in sorted(directory.glob('health-*.sqlite'), reverse=True)[30:]:
        old.unlink()
    return target


def setup_credentials():
    import keyring
    from keyrings.cryptfile.cryptfile import CryptFileKeyring
    from mi_fitness_mcp import security

    master_file = Path(os.environ.get('HEALTH_KEY_FILE', '/run/secrets/keyring_master'))
    master = master_file.read_text(encoding='utf-8').strip()
    if len(master) < 32:
        raise RuntimeError('缺少有效的独立密钥环解锁文件')
    ring = CryptFileKeyring()
    ring.file_path = str(STATE / 'credentials' / 'encrypted-keyring.cfg')
    ring.keyring_key = master
    keyring.set_keyring(ring)

    def encrypted_store(api_key, token):
        # 加密失败直接中止，不沿用上游降级为 SQLite 明文的行为。
        keyring.set_password(security.SERVICE_NAME, security._account_for(api_key), token)
        return True

    security.store_api_key_secret = encrypted_store


def enable_archive():
    from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter

    original = MiFitnessCloudAdapter._request

    async def request_and_archive(self, base_url, api_path, payload):
        result = await original(self, base_url, api_path, payload)
        archive_response(STATE / 'raw', api_path, payload, result)
        return result

    MiFitnessCloudAdapter._request = request_and_archive


def load_single_key(db_path):
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as c:
        rows = c.execute('SELECT key,user_id,region FROM api_keys WHERE revoked=0 ORDER BY created_at DESC,rowid DESC').fetchall()
    if not rows or len({(row[1], row[2]) for row in rows}) != 1:
        raise RuntimeError('仅允许一个账号和地区的有效授权')
    return rows[0][0]


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    pending.replace(path)


def worker():
    import httpx

    state_file = STATE / 'automation' / 'status.json'
    state = json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
    database = STATE / 'data' / 'mi_fitness.db'
    while True:
        today = datetime.now(timezone(timedelta(hours=8))).date()
        try:
            if database.exists() and state.get('backup_date') != today.isoformat():
                backup_database(database, STATE / 'backups')
                state['backup_date'] = today.isoformat()
            key = load_single_key(database)
            with httpx.Client(base_url='http://backend:8321', headers={'X-API-Key': key}, timeout=20, trust_env=False) as client:
                response = client.post('/api/sync', json={
                    'start_date': sync_start(state, today), 'end_date': today.isoformat(), 'background': True,
                })
                response.raise_for_status()
                task = response.json()['sync_id']
                deadline = time.monotonic() + 2400
                while time.monotonic() < deadline:
                    response = client.get('/api/sync/' + task)
                    response.raise_for_status()
                    result = response.json()
                    if result.get('status') not in ('accepted', 'queued', 'running'):
                        finish_sync(state, result, today)
                        break
                    time.sleep(10)
                else:
                    finish_sync(state, {'status': 'timeout'}, today)
        except Exception as exc:
            # 不将云端错误正文、账号标识或认证参数写入日志。
            finish_sync(state, {'status': 'error'}, today)
            state['error_type'] = type(exc).__name__
        atomic_json(state_file, state)
        print(json.dumps({'event': 'maintenance', 'status': state.get('status'), 'backup_date': state.get('backup_date')}), flush=True)
        time.sleep(1800 if state.get('status') == 'ok' else 300)


def main():
    os.umask(0o077)
    mode = sys.argv[1]
    if mode == 'api':
        setup_credentials()
        enable_archive()
        import uvicorn
        from mi_fitness_mcp.api import app
        uvicorn.run(app, host='0.0.0.0', port=8321, access_log=False)
    elif mode == 'web':
        logging.getLogger('werkzeug').disabled = True
        from mi_fitness_mcp.web import create_app
        app = create_app(backend_url='http://backend:8321', admin_key=os.environ['MI_FITNESS_ADMIN_KEY'])
        app.run(host='0.0.0.0', port=8322, debug=False, use_reloader=False)
    elif mode == 'worker':
        worker()
    elif mode == 'mcp':
        from readonly import main as readonly_main
        readonly_main('streamable-http')
    else:
        raise ValueError('未知运行模式')


if __name__ == '__main__':
    main()
