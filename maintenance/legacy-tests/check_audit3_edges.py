"""在本机 Linux 候选镜像内核查数据边界；无真实账号或网络。"""
import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from mi_fitness_mcp import api
from mi_fitness_mcp.models import DailyActivity, StressSample, Workout
from mi_fitness_mcp.storage import Database
from mi_fitness_mcp.services.sync_service import SyncService

CN = timezone(timedelta(hours=8))
with tempfile.TemporaryDirectory(prefix='audit3-edges-') as temporary:
    db = Database(Path(temporary) / 'synthetic.sqlite')
    item = DailyActivity(id='day-A', provider='mi_fitness', source_type='cloud_session', user_id='A',
        date='2026-10-16', steps=1111, active_kcal=100, distance_m=1000)
    db.insert_daily_activity(item)
    with db._get_connection() as conn:
        conn.execute('CREATE TABLE api_keys (key TEXT,label TEXT,user_id TEXT,pass_token TEXT,region TEXT,created_at TEXT,revoked INTEGER DEFAULT 0)')
        conn.commit()
    try:
        db.insert_daily_activity(item.model_copy(update={'user_id':'B','steps':2222}))
    except ValueError:
        pass
    else:
        raise AssertionError('Account collision not blocked')
    try:
        api._create_key_record(db, 'B', 'synthetic', 'cn', 'other')
    except api.HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError('Second owner authorization accepted')
    assert db.query_daily_activity('A','2026-10-16','2026-10-16')[0]['steps'] == 1111
    db.update_sync_state('heart_rate', datetime(2026,10,16,9,tzinfo=CN), user_id='A')
    assert db.get_sync_state('heart_rate', user_id='B') is None
    class Adapter:
        user_id='A'
        region='cn'
        calls=[]
        def is_connected(self): return True
        async def iter_heart_rate(self,start,end):
            self.calls.append((start,end))
            if False: yield None
    adapter=Adapter()
    result=asyncio.run(SyncService(adapter,db).sync_data_type('heart_rate',end_date='2026-10-16'))
    assert result['status']=='ok' and adapter.calls==[('2026-10-16','2026-10-16')]
    for index,hour in enumerate((1,9)):
        db.insert_stress_sample(StressSample(id=f'stress-{index}',provider='mi_fitness',source_type='cloud_session',user_id='A',
            timestamp=datetime(2026,10,16,hour,tzinfo=CN),stress_score=30,level='medium'))
    coverage=next(row for row in db.get_data_coverage('A') if row['data_type']=='stress')
    assert coverage['days_with_data']==1 and coverage['first_date']=='2026-10-16'
    exercise=Workout(id='exercise',workout_id='exercise',provider='mi_fitness',source_type='cloud_session',user_id='A',
        activity_type='running',start_at=datetime(2026,10,16,9,tzinfo=CN),end_at=datetime(2026,10,16,9,30,tzinfo=CN),duration_minutes=30)
    db.insert_workout(exercise)
    db.insert_workout(exercise.model_copy(update={'total_steps':4000,'avg_pace_sec_per_km':300}))
    row=db.query_workouts('A','2026-10-16','2026-10-16')[0]
    assert row['total_steps']==4000 and row['avg_pace_sec_per_km']==300
print(json.dumps({'account_isolation':'ok','cursor_isolation':'ok','same_day_incremental':'ok','coverage_dates':'ok','workout_updates':'ok'}))
