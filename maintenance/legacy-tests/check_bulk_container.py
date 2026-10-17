import asyncio
import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

root=Path(tempfile.mkdtemp())
os.environ['XDG_CONFIG_HOME']=str(root/'config')
os.environ['XDG_DATA_HOME']=str(root/'data')
os.environ['HOME']=str(root)
from mi_fitness_mcp.api import app
from mi_fitness_mcp.models import HeartRateSample
from mi_fitness_mcp.services.sync_service import SyncService
from mi_fitness_mcp.storage import Database


class SlowDisk(Database):
    def insert_heart_rate_sample(self, sample, **kwargs):
        time.sleep(0.01)
        return super().insert_heart_rate_sample(sample, **kwargs)


class SyntheticAdapter:
    def is_connected(self): return True
    async def iter_heart_rate(self,start,end):
        stamp=datetime(2026,10,15,tzinfo=timezone.utc)
        for i in range(40):
            yield HeartRateSample(id=f'local-proof-{i}',provider='mi_fitness',source_type='cloud_session',user_id='synthetic-only',timestamp=stamp+timedelta(minutes=i),bpm=70)


async def main():
    db=SlowDisk(root/'health.sqlite')
    service=SyncService(SyntheticAdapter(),db)
    task=asyncio.create_task(service.sync_data_type('heart_rate','2026-10-15','2026-10-15'))
    await asyncio.sleep(0.02)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
        started=time.perf_counter()
        r=await client.get('/')
        elapsed=time.perf_counter()-started
        responsive=not task.done()
    result=await task
    with sqlite3.connect(db.db_path) as c:
        rows=c.execute('SELECT count(*) FROM heart_rate_samples').fetchone()[0]
        integrity=c.execute('PRAGMA quick_check').fetchone()[0]
    report={'linux_http_status_during_disk_wait':r.status_code,'request_returned_while_sync_active':responsive,'local_request_ms':round(elapsed*1000,1),'synthetic_records_stored':rows,'sync_status':result['status'],'database_quick_check':integrity}
    print(json.dumps(report))
    assert r.status_code==200 and responsive and rows==40 and integrity=='ok'


asyncio.run(main())
