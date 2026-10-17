import asyncio
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/mi-fitness-mcp-cn/src'))
from mi_fitness_mcp import storage
from mi_fitness_mcp.models import HeartRateSample
from mi_fitness_mcp.services.sync_service import SyncService


def samples(count):
    start=datetime(2026,10,15,tzinfo=timezone.utc)
    return [HeartRateSample(id=f'synthetic-{i}',provider='mi_fitness',source_type='cloud_session',user_id='synthetic-user',timestamp=start+timedelta(minutes=i),bpm=70) for i in range(count)]


def test_bulk_records_commit_once_remain_idempotent_and_rollback_together(tmp_path,monkeypatch):
    db=storage.Database(tmp_path/'health.sqlite')
    assert callable(getattr(db,'insert_records_batch',None)), '缺少批量事务，每条记录都在提交'
    statements=[]
    connect=sqlite3.connect

    def traced(*args,**kwargs):
        conn=connect(*args,**kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(storage.sqlite3,'connect',traced)
    records=samples(250)
    db.insert_records_batch('heart_rate',records)
    assert sum(s=='COMMIT' for s in statements)==1
    db.insert_records_batch('heart_rate',records)
    with db._get_connection() as c:
        assert c.execute('SELECT count(*) FROM heart_rate_samples').fetchone()[0]==250
    valid=samples(1)[0].model_copy(update={'id':'rollback-proof'})
    invalid=valid.model_copy(update={'id':'invalid','user_id':None})
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_records_batch('heart_rate',[valid,invalid])
    with db._get_connection() as c:
        assert c.execute("SELECT count(*) FROM heart_rate_samples WHERE id='rollback-proof'").fetchone()[0]==0


@pytest.mark.asyncio
async def test_disk_wait_during_sync_does_not_block_request_event_loop(tmp_path):
    class SlowDiskDatabase(storage.Database):
        def insert_heart_rate_sample(self, sample, **kwargs):
            time.sleep(0.01)
            return super().insert_heart_rate_sample(sample,**kwargs)

    class Adapter:
        def is_connected(self): return True
        async def iter_heart_rate(self,start,end):
            for record in samples(40): yield record

    db=SlowDiskDatabase(tmp_path/'health.sqlite')
    service=SyncService(Adapter(),db)
    task=asyncio.create_task(service.sync_data_type('heart_rate','2026-10-15','2026-10-15'))
    await asyncio.sleep(0.01)
    responsive=not task.done()
    result=await task
    assert responsive, '磁盘写入阻塞了整个请求事件循环'
    assert result['status']=='ok'
    with db._get_connection() as c:
        assert c.execute('SELECT count(*) FROM heart_rate_samples').fetchone()[0]==40
