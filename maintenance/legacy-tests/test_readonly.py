import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/mi-fitness-mcp-cn/src'))
from mi_fitness_mcp.models import DailyActivity
from mi_fitness_mcp.storage import Database


def readonly():
    path = ROOT / 'outputs/nas-deployment/readonly.py'
    assert path.exists(), '缺少服务端强制只读查询入口'
    spec = importlib.util.spec_from_file_location('health_readonly', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readonly_database_denies_writes_and_credential_reads(tmp_path):
    m = readonly()
    path = tmp_path / 'health.sqlite'
    db = Database(path)
    db.insert_daily_activity(DailyActivity(id='proof',provider='mi_fitness',source_type='cloud_session',user_id='private-user',date='2026-10-15',steps=1000,distance_m=700,active_kcal=50))
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE api_keys (key TEXT)')
        c.execute("INSERT INTO api_keys VALUES ('private-key')")
    ro = m.ReadOnlyDatabase(path)
    with ro._get_connection() as c:
        assert c.execute('SELECT steps FROM daily_activity').fetchone()[0] == 1000
        with pytest.raises(sqlite3.DatabaseError):
            c.execute('DELETE FROM daily_activity')
        with pytest.raises(sqlite3.DatabaseError):
            c.execute('SELECT key FROM api_keys')
    records = m.query_records(path, 'daily_activity', '2026-10-15', '2026-10-15')
    assert records[0]['steps'] == 1000
    assert 'private-user' not in str(records)
    with pytest.raises(ValueError):
        m.query_records(path, 'api_keys', '2026-10-15', '2026-10-15')
    with pytest.raises(ValueError):
        m.query_records(path, 'daily_activity', '2020-01-01', '2026-10-15')
