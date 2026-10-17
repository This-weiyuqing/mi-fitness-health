"""创建本机专用合成数据库；运行中不调用云端接口。"""
import sqlite3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/mi-fitness-mcp-cn/src'))
from mi_fitness_mcp.models import DailyActivity
from mi_fitness_mcp.storage import Database

target = ROOT / 'work/audit2-container-validation'
target.mkdir(exist_ok=True)
(target / 'state/data').mkdir(parents=True, exist_ok=True)
(target / 'state/credentials').mkdir(parents=True, exist_ok=True)
(target / 'state/config/mi-fitness-mcp').mkdir(parents=True, exist_ok=True)
(target / 'state/config/mi-fitness-mcp/config.json').write_text(json.dumps({
    'mode': 'mi_fitness_cloud', 'region': 'cn', 'timezone': 'Asia/Shanghai',
    'database_path': '/state/data/mi_fitness.db', 'auto_sync_on_start': False}), encoding='utf-8')
(target / 'keyring_master').write_text('synthetic-only-keyring-unlock-value-20261017', encoding='utf-8')
db = Database(target / 'state/data/mi_fitness.db')
db.insert_daily_activity(DailyActivity(id='synthetic-day', provider='mi_fitness', source_type='cloud_session',
    user_id='synthetic-owner', date='2026-10-15', steps=4691, active_kcal=596, distance_m=2979))
with db._get_connection() as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS api_keys (key TEXT PRIMARY KEY,label TEXT,user_id TEXT NOT NULL,pass_token TEXT NOT NULL,region TEXT NOT NULL DEFAULT \'cn\',created_at TEXT NOT NULL,last_used_at TEXT,revoked INTEGER NOT NULL DEFAULT 0)')
    conn.execute("INSERT OR IGNORE INTO api_keys(key,label,user_id,pass_token,region,created_at) VALUES ('mif_sk_syntheticlocal','synthetic only','synthetic-owner','synthetic-token','cn','2026-10-17')")
    conn.commit()
print('Synthetic container fixture ready; no real health records or credentials used.')
