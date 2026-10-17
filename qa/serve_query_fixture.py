"""仅本机合成数据入口；不加载用户配置、凭据或同步适配器。"""
import argparse
import json
import os
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mi_fitness_mcp.storage import Database

ROOT = Path(__file__).resolve().parents[1]
KINDS = ('activity', 'heartrate', 'sleep', 'workouts', 'body', 'spo2', 'stress', 'abnormal')
OWNER = 'synthetic-owner'
KEY = 'synthetic-query-key'
PASSWORD = 'synthetic-web-password'


def artifact_path(value):
    path = Path(value).resolve()
    if not path.is_relative_to(ROOT / 'artifacts'):
        raise ValueError('合成数据和输出必须位于本仓库 artifacts 目录')
    return path


def generate(path, density=1):
    path = artifact_path(path)
    if path.exists():
        raise FileExistsError('拒绝覆盖已有文件：' + str(path))
    db = Database(path)
    tz = timezone(timedelta(hours=8))
    with db._get_connection() as conn:
        def insert(table, rows):
            fields = ('id', 'provider', 'source_type', 'user_id') + tuple(rows[0])
            conn.executemany(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                [(f'{table}-{offset:08}', 'synthetic', 'generated', OWNER, *row.values()) for offset, row in enumerate(rows)])
        for table, count, field in [('heart_rate_samples', 3000, 'bpm'), ('spo2_samples', 1000, 'spo2_pct'), ('stress_samples', 1000, 'stress_score')]:
            rows = []
            for day in range(30):
                base = datetime(2026, 9, 18, tzinfo=tz) + timedelta(days=day)
                for n in range(count * density):
                    stamp = (base + timedelta(seconds=n * 86400 / (count * density))).isoformat()
                    row = dict(timestamp=stamp)
                    row[field] = 55 + n % 70 if field == 'bpm' else 92 + n % 9 if field == 'spo2_pct' else n % 102
                    if field == 'bpm':
                        row['sample_type'] = ('passive', 'resting', 'active')[n % 3]
                    if field == 'stress_score':
                        row['level'] = 'synthetic-source'
                    rows.append(row)
            insert(table, rows)
        for table in ('daily_activity', 'sleep_sessions', 'workouts', 'body_measurements', 'abnormal_heart_beat_events'):
            rows = []
            for day in range(30):
                d = date(2026, 9, 18) + timedelta(days=day)
                stamp = d.isoformat() + 'T08:00:00+08:00'
                for n in range(2):
                    if table == 'daily_activity':
                        row = dict(date=d.isoformat(), device_id=f'device-{n}', steps=2000 + day * 10 + n, distance_m=1800 + day, active_kcal=100 + n, total_kcal=1000 + day)
                    elif table == 'sleep_sessions':
                        row = dict(sleep_id=f's-{day}-{n}', start_at=(d - timedelta(days=1)).isoformat() + 'T23:00:00+08:00', end_at=stamp, duration_minutes=495 if n == 0 else 30, time_asleep_minutes=480 if n == 0 else 30, time_awake_minutes=15 if n == 0 else 0, is_nap=n, stages=json.dumps([dict(stage='deep', minutes=120), dict(stage='light', minutes=280), dict(stage='rem', minutes=80)]) if n == 0 else None)
                    elif table == 'workouts':
                        row = dict(workout_id=f'w-{day}-{n}', activity_type='run', start_at=stamp, end_at=d.isoformat() + 'T09:00:00+08:00', duration_minutes=60, distance_m=8000, calories_kcal=400)
                    elif table == 'body_measurements':
                        row = dict(timestamp=stamp, device_id=f'device-{n}', weight_kg=70 + day / 10 + n / 100, bmi=22, body_fat_pct=20)
                    else:
                        row = dict(event_id=f'a-{day}-{n}', start_at=stamp, end_at=d.isoformat() + 'T08:01:00+08:00', duration_seconds=60)
                    rows.append(row)
            insert(table, rows)
        conn.execute('CREATE TABLE api_keys (key TEXT PRIMARY KEY,user_id TEXT,pass_token TEXT,region TEXT,revoked INTEGER DEFAULT 0)')
        conn.executemany('INSERT INTO api_keys VALUES (?,?,?,?,0)', [(KEY, OWNER, '', 'cn'), ('synthetic-other-key', 'synthetic-other', '', 'cn')])
        conn.commit()
    return path


class ReadOnlyDatabase(Database):
    def __init__(self, path):
        self.db_path = artifact_path(path)
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def backend(path):
    # 替换 lifespan 只为隔离配置和密钥环；路由、鉴权、查询服务使用产品实现。
    from mi_fitness_mcp import api
    from mi_fitness_mcp.services.query_service import QueryService
    db = ReadOnlyDatabase(path)
    @asynccontextmanager
    async def lifespan(app):
        app.state.db = db
        app.state.default_context = None
        app.state.key_contexts = {}
        app.state.key_context_lock = threading.RLock()
        for key, owner in [(KEY, OWNER), ('synthetic-other-key', 'synthetic-other')]:
            ctx = api.UserContext(owner, 'synthetic-unused', 'cn', query_service=QueryService(db, owner))
            app.state.key_contexts[key] = dict(expires=time.monotonic() + 86400, identity=(owner, 'cn', ''), context=ctx)
        yield
    api.app.router.lifespan_context = lifespan
    return api.app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['generate', 'backend', 'web'])
    parser.add_argument('--db', default=str(ROOT / 'artifacts/query-summary/synthetic-1x.db'))
    parser.add_argument('--density', type=int, choices=[1, 10], default=1)
    parser.add_argument('--port', type=int, default=18431)
    parser.add_argument('--backend-url', default='http://127.0.0.1:18431')
    parser.add_argument('--server-key', action='store_true')
    parser.add_argument('--host', default='127.0.0.1', choices=['127.0.0.1', '0.0.0.0'])
    args = parser.parse_args()
    for name in ('MI_FITNESS_API_KEY', 'MI_FITNESS_ADMIN_KEY'):
        os.environ.pop(name, None)
    os.environ['MI_FITNESS_ALLOWED_HOSTS'] = '127.0.0.1,localhost,backend,web'
    os.environ['MI_FITNESS_WEB_PASSWORD'] = PASSWORD
    os.environ['MI_FITNESS_CALENDAR_DIR'] = str(ROOT / 'artifacts/query-summary/calendar')
    if args.mode == 'generate':
        print(generate(args.db, args.density))
    elif args.mode == 'backend':
        import uvicorn
        uvicorn.run(backend(args.db), host=args.host, port=args.port, access_log=False)
    else:
        from mi_fitness_mcp.web import create_app
        app = create_app(backend_url=args.backend_url, api_key=KEY if args.server_key else None)
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
