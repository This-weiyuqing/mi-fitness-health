"""数据边界修复回归：全部为本机合成数据。"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/mi-fitness-mcp-cn/src'))
from mi_fitness_mcp import api
from mi_fitness_mcp.models import DailyActivity, StressSample, Workout, SleepSession
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.services.sync_service import SyncService
from mi_fitness_mcp.storage import Database

CN = timezone(timedelta(hours=8))


def database(tmp_path):
    db = Database(tmp_path / 'synthetic.sqlite')
    with db._get_connection() as conn:
        conn.execute("CREATE TABLE api_keys (key TEXT PRIMARY KEY,label TEXT,user_id TEXT,pass_token TEXT,region TEXT,created_at TEXT,last_used_at TEXT,revoked INTEGER DEFAULT 0)")
        conn.commit()
    return db


@pytest.mark.parametrize('existing', ['revoked_key', 'health_data'])
def test_new_authorization_cannot_change_database_owner(tmp_path, monkeypatch, existing):
    db = database(tmp_path)
    if existing == 'revoked_key':
        with db._get_connection() as conn:
            conn.execute("INSERT INTO api_keys VALUES ('old','old','A','','cn','2026-10-01',NULL,1)")
            conn.commit()
    else:
        db.insert_daily_activity(DailyActivity(id='day-A', provider='mi_fitness', source_type='cloud_session',
            user_id='A', date='2026-10-16', steps=1111, active_kcal=100, distance_m=1000))
    stored = []
    monkeypatch.setattr(api, 'store_api_key_secret', lambda *args: stored.append(args) or True)
    with pytest.raises(api.HTTPException) as exc:
        api._create_key_record(db, 'B', 'synthetic', 'cn', 'other')
    assert exc.value.status_code == 409
    assert not stored


def test_same_owner_reauthorization_allowed_but_region_switch_rejected(tmp_path, monkeypatch):
    db = database(tmp_path)
    monkeypatch.setattr(api, 'store_api_key_secret', lambda *args: True)
    first = api._create_key_record(db, 'A', 'synthetic', 'cn', 'first')
    second = api._create_key_record(db, 'A', 'synthetic', 'cn', 'second')
    assert first != second
    with pytest.raises(api.HTTPException) as exc:
        api._create_key_record(db, 'A', 'synthetic', 'us', 'other-region')
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_manual_sync_refuses_context_for_another_data_owner(tmp_path):
    db = database(tmp_path)
    db.insert_daily_activity(DailyActivity(id='day-A', provider='mi_fitness', source_type='cloud_session',
        user_id='A', date='2026-10-16', steps=1111, active_kcal=100, distance_m=1000))
    ctx = SimpleNamespace(user_id='B', region='cn', sync_service=SimpleNamespace(db=db), adapter=None)
    with pytest.raises(api.HTTPException) as exc:
        await api._run_sync(ctx, None, {'sync_id': 'synthetic'})
    assert exc.value.status_code == 409


class Adapter:
    def __init__(self, owner):
        self.user_id = owner
        self.calls = []
    def is_connected(self): return True
    async def iter_heart_rate(self, start, end):
        self.calls.append((start, end))
        if False: yield None


@pytest.mark.asyncio
async def test_same_day_incremental_uses_calendar_day(tmp_path):
    db = database(tmp_path)
    adapter = Adapter('A')
    # 旧版全局游标也必须安全，不能将当天 09:00 与午夜比较后拒绝。
    db.update_sync_state('heart_rate', datetime(2026, 10, 16, 9, tzinfo=CN))
    db.update_sync_state('heart_rate', datetime(2026, 10, 16, 9, tzinfo=CN), user_id='A')
    await SyncService(adapter, db).sync_data_type('heart_rate', end_date='2026-10-16')
    assert adapter.calls
    assert adapter.calls[-1][1] == '2026-10-16'


def test_direct_and_batch_writes_cannot_overwrite_another_owner(tmp_path):
    db = database(tmp_path)
    item = DailyActivity(id='same-day', provider='mi_fitness', source_type='cloud_session', user_id='A',
        date='2026-10-16', steps=1111, active_kcal=100, distance_m=1000)
    db.insert_daily_activity(item)
    other = item.model_copy(update={'user_id': 'B', 'steps': 2222})
    with pytest.raises(ValueError, match='账号'):
        db.insert_daily_activity(other)
    with pytest.raises(ValueError, match='账号'):
        db.insert_records_batch('daily_activity', [other])
    assert QueryService(db, 'A').get_daily_summaries('2026-10-16', '2026-10-16')[0]['steps'] == 1111


def test_concurrent_first_authorizations_bind_exactly_one_owner(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    db = database(tmp_path)
    monkeypatch.setattr(api, 'store_api_key_secret', lambda *args: True)
    barrier = threading.Barrier(2)
    def create(owner):
        barrier.wait()
        try:
            api._create_key_record(db, owner, 'synthetic', 'cn', owner)
            return 'ok'
        except api.HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, ['A', 'B']), key=str) == [409, 'ok']
    with db._get_connection() as conn:
        assert conn.execute('SELECT count(*) FROM api_keys').fetchone()[0] == 1


@pytest.mark.asyncio
async def test_another_account_cursor_is_not_used_for_first_incremental_sync(tmp_path):
    db = database(tmp_path)
    db.update_sync_state('heart_rate', datetime(2026, 10, 15, tzinfo=CN))
    adapter = Adapter('B')
    await SyncService(adapter, db).sync_data_type('heart_rate', end_date='2026-10-16')
    assert adapter.calls[0][0] == '2026-09-17'


def test_cursor_storage_is_scoped_by_owner(tmp_path):
    db = database(tmp_path)
    stamp = datetime(2026, 10, 16, 9, tzinfo=CN)
    db.update_sync_state('heart_rate', stamp, user_id='A')
    assert db.get_sync_state('heart_rate', user_id='A')['last_record_timestamp'] == stamp.isoformat()
    assert db.get_sync_state('heart_rate', user_id='B') is None


@pytest.mark.asyncio
async def test_native_mcp_status_reads_current_owner_cursor(tmp_path, monkeypatch):
    from mi_fitness_mcp import server
    db = database(tmp_path)
    db.update_sync_state('heart_rate', datetime(2026,10,16,9,tzinfo=CN), user_id='A')
    class DisconnectedAdapter:
        user_id = 'A'
        last_error = None
        last_health_check_at = None
        async def health_check(self): return False
    monkeypatch.setattr(server, 'db', db)
    monkeypatch.setattr(server, 'adapter', DisconnectedAdapter())
    monkeypatch.setattr(server, 'sync_service', None)
    monkeypatch.setattr(server, 'config', SimpleNamespace(mode='mi_fitness_cloud',region='cn',health_check_timeout_seconds=1))
    result = await server._handle_get_connection_status()
    assert result['last_sync_at'] is not None
    assert 'heart_rate' in result['available_data_types']


def test_coverage_counts_local_measurement_and_sleep_wake_days(tmp_path):
    db = database(tmp_path)
    for index, hour in enumerate((1, 9)):
        db.insert_stress_sample(StressSample(id=f'stress-{index}', provider='mi_fitness', source_type='cloud_session',
            user_id='A', timestamp=datetime(2026, 10, 16, hour, tzinfo=CN), stress_score=30, level='medium'))
    db.insert_sleep_session(SleepSession(id='sleep-A', sleep_id='sleep-A', provider='mi_fitness', source_type='cloud_session',
        user_id='A', start_at=datetime(2026, 10, 15, 23, tzinfo=CN), end_at=datetime(2026, 10, 16, 7, tzinfo=CN),
        duration_minutes=480, time_asleep_minutes=480, time_awake_minutes=0))
    coverage = {row['data_type']: row for row in db.get_data_coverage('A')}
    for kind in ('stress', 'sleep'):
        assert coverage[kind]['first_date'] == coverage[kind]['last_date'] == '2026-10-16'
        assert coverage[kind]['days_with_data'] == 1


def test_repeated_workout_sync_updates_all_mutable_fields(tmp_path):
    db = database(tmp_path)
    item = Workout(id='exercise', workout_id='exercise', provider='mi_fitness', source_type='cloud_session', user_id='A',
        activity_type='walking', start_at=datetime(2026, 10, 16, 9, tzinfo=CN),
        end_at=datetime(2026, 10, 16, 9, 30, tzinfo=CN), duration_minutes=30)
    db.insert_workout(item)
    changes = {'total_steps': 4000, 'avg_pace_sec_per_km': 300, 'max_pace_sec_per_km': 240,
        'activity_type': 'running', 'end_at': datetime(2026, 10, 16, 9, 40, tzinfo=CN)}
    db.insert_workout(item.model_copy(update=changes))
    result = QueryService(db, 'A').get_workouts('2026-10-16', '2026-10-16')[0]
    for key, value in changes.items():
        assert result[key] == (value.isoformat() if isinstance(value, datetime) else value)
