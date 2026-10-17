"""仅针对本机合成容器库核查备份和只读查询。"""
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, '/opt/health')
import runtime
from readonly import ReadOnlyDatabase, query_records

source = Path('/state/data/mi_fitness.db')
backup = runtime.backup_database(source, '/state/backups')
with sqlite3.connect(backup) as conn:
    assert conn.execute('SELECT steps FROM daily_activity').fetchone()[0] == 4691
    assert conn.execute('SELECT count(*) FROM api_keys').fetchone()[0] == 0
    assert conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
assert query_records(source, 'daily_activity', '2026-10-15', '2026-10-15')[0]['steps'] == 4691
db = ReadOnlyDatabase(source)
with db._get_connection() as conn:
    for statement in ('SELECT * FROM api_keys', 'DELETE FROM daily_activity'):
        try:
            conn.execute(statement)
        except sqlite3.DatabaseError:
            continue
        raise AssertionError('Read-only boundary bypass')
print(json.dumps({'backup_restore': 'ok', 'backup_credentials_removed': True,
    'readonly_health_query': 'ok', 'credential_table_denied': True, 'database_write_denied': True}))
