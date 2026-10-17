"""容器内执行的真实链路检查，只输出验收布尔值与任务状态。"""
import gzip
import json
import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, '/opt/health')
import runtime

db_path = Path('/state/data/mi_fitness.db')
key = runtime.load_single_key(db_path)
mode = sys.argv[1]
with httpx.Client(base_url='http://127.0.0.1:8321',headers={'X-API-Key':key},trust_env=False,timeout=25) as client:
    if mode == 'start':
        r=client.post('/api/sync',json={'start_date':'2026-10-15','end_date':'2026-10-16','background':True})
        r.raise_for_status()
        Path('/state/linux-check-task.json').write_text(json.dumps(r.json()),encoding='utf-8')
        print(json.dumps({'status':r.json()['status']}))
    elif mode == 'poll':
        task=json.loads(Path('/state/linux-check-task.json').read_text(encoding='utf-8'))
        r=client.get('/api/sync/'+task['sync_id'])
        r.raise_for_status()
        result=r.json()
        print(json.dumps({'status':result['status'],'types':[{'type':t['data_type'],'status':t['status']} for t in result.get('results',[])]}))
    elif mode == 'verify':
        params={'start_date':'2026-10-15','end_date':'2026-10-16'}
        summaries=client.get('/api/summary',params=params); summaries.raise_for_status()
        yesterday=next(d for d in summaries.json()['data'] if d['date']=='2026-10-15')
        sleep=client.get('/api/sleep',params=params);sleep.raise_for_status()
        sessions=sleep.json()['data']
        weights=client.get('/api/body-measurements',params=params);weights.raise_for_status()
        print(json.dumps({'daily_matches_phone':yesterday['steps']==4691 and yesterday['active_kcal']==596,
                          'sleep_matches_phone':len(sessions)==2 and sorted(s['duration_minutes'] for s in sessions)==[474,517],
                          'weight_matches_phone':any(w.get('weight_kg')==87.3 for w in weights.json()['data'])}))
        raw_count=0
        paths=set()
        for f in Path('/state/raw').glob('*.jsonl.gz'):
            with gzip.open(f,'rt',encoding='utf-8') as lines:
                for line in lines:
                    entry=json.loads(line);raw_count+=1;paths.add(entry['path'])
        backup=runtime.backup_database(db_path,Path('/state/backups'))
        with sqlite3.connect(backup) as c:
            clean=c.execute('SELECT count(*) FROM api_keys').fetchone()[0]==0
            good=c.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            rows=c.execute('SELECT count(*) FROM daily_activity').fetchone()[0]
        with sqlite3.connect(db_path) as c:
            plaintext=c.execute("SELECT count(*) FROM api_keys WHERE pass_token!=''").fetchone()[0]
        print(json.dumps({'raw_health_responses_archived':raw_count,'only_allowed_health_paths':paths<=runtime.HEALTH_PATHS,'backup_quick_check_ok':good,'backup_excludes_api_credentials':clean,'backup_daily_rows':rows,'plaintext_token_rows':plaintext}))
    else:
        raise SystemExit('未知模式')
