"""第二轮补充审查复现；仅本机临时 SQLite 与合成账号，不访问网络。"""
import asyncio
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/mi-fitness-mcp-cn/src'))
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.models import StressSample, Workout
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.services.sync_service import SyncService
from mi_fitness_mcp.storage import Database

CN = timezone(timedelta(hours=8))


async def daily_for(owner, steps):
    adapter = MiFitnessCloudAdapter(user_id=owner, pass_token='synthetic', region='cn')
    adapter._connected = True
    adapter._client = object()
    async def reports(key, start, end):
        value = {'steps': steps, 'distance': steps} if key == 'steps' else {'calories': 100}
        return [{'time': int(datetime(2026, 10, 16, tzinfo=CN).timestamp()), 'value': value}]
    adapter._fetch_daily_reports = reports
    return [row async for row in adapter.iter_daily_activity('2026-10-16', '2026-10-16')][0]


async def check(directory):
    db = Database(directory / 'synthetic.sqlite')
    first = await daily_for('synthetic-A', 1111)
    second = await daily_for('synthetic-B', 2222)
    db.insert_daily_activity(first)
    db.insert_daily_activity(second)
    a = QueryService(db, 'synthetic-A').get_daily_summaries('2026-10-16', '2026-10-16')
    b = QueryService(db, 'synthetic-B').get_daily_summaries('2026-10-16', '2026-10-16')
    assert first.id == second.id
    assert a[0]['steps'] == 2222 and b == []

    db.update_sync_state('heart_rate', datetime(2026, 10, 16, 9, tzinfo=CN))
    adapter = MiFitnessCloudAdapter(user_id='synthetic-A', pass_token='synthetic', region='cn')
    adapter._connected = True
    adapter._client = object()
    try:
        await SyncService(adapter, db).sync_data_type('heart_rate', end_date='2026-10-16')
    except ValueError as exc:
        assert str(exc) == 'start_date must not be after end_date'
        sync_error = str(exc)
    else:
        raise AssertionError('Expected same-day incremental rejection was not reproduced')

    db.update_sync_state('daily_activity', datetime(2026, 10, 15, tzinfo=CN))
    seen_ranges = []
    class SecondAccountAdapter:
        user_id = 'synthetic-B'
        def is_connected(self): return True
        async def iter_daily_activity(self, start, end):
            seen_ranges.append((start, end))
            if False:
                yield None
    await SyncService(SecondAccountAdapter(), db).sync_data_type('daily_activity', end_date='2026-10-16')
    assert seen_ranges[0][0] == '2026-10-15'

    for index, hour in enumerate((1, 9)):
        db.insert_stress_sample(StressSample(id=f'synthetic-stress-{index}', provider='mi_fitness',
            source_type='cloud_session', user_id='synthetic-A', timestamp=datetime(2026, 10, 16, hour, tzinfo=CN),
            stress_score=30, level='medium'))
    service = QueryService(db, 'synthetic-A')
    samples = service.get_stress_samples('2026-10-16', '2026-10-16')
    coverage = next(row for row in service.get_data_coverage() if row['data_type'] == 'stress')
    assert len(samples) == 2
    assert coverage['first_date'] == '2026-10-15' and coverage['days_with_data'] == 2

    exercise = Workout(id='synthetic-workout', workout_id='synthetic-workout', provider='mi_fitness',
        source_type='cloud_session', user_id='synthetic-A', activity_type='running',
        start_at=datetime(2026, 10, 16, 9, tzinfo=CN), end_at=datetime(2026, 10, 16, 9, 30, tzinfo=CN),
        duration_minutes=30)
    db.insert_workout(exercise)
    db.insert_workout(exercise.model_copy(update={'total_steps': 4000, 'avg_pace_sec_per_km': 300}))
    updated = service.get_workouts('2026-10-16', '2026-10-16')[0]
    assert updated['total_steps'] is None and updated['avg_pace_sec_per_km'] is None
    return {
        'cross_account_collision': {'owner_A_steps_after_owner_B_sync': a[0]['steps'], 'owner_B_records': len(b)},
        'same_day_incremental_sync': sync_error,
        'shared_cursor': {'new_account_first_sync_start': seen_ranges[0][0], 'expected_without_another_account_cursor': '2026-09-17'},
        'coverage_timezone_mismatch': {'requested_day_records': len(samples), 'first_date': coverage['first_date'], 'days_with_data': coverage['days_with_data']},
        'workout_correction_lost': {'supplied_steps': 4000, 'stored_steps': updated['total_steps'], 'supplied_pace': 300, 'stored_pace': updated['avg_pace_sec_per_km']},
    }


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='health-edge-review-') as temporary:
        print(json.dumps(asyncio.run(check(Path(temporary))), indent=2))
