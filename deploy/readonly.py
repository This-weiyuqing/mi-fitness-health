"""受限只读 MCP：复用查询服务，数据库与凭据表双重隔离。"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.storage import Database

TABLES = {'daily_activity', 'sleep_sessions', 'body_measurements', 'heart_rate_samples',
          'workouts', 'spo2_samples', 'stress_samples', 'abnormal_heart_beat_events'}
METHODS = {'daily_activity': 'get_daily_summaries', 'sleep': 'get_sleep_sessions',
           'body_measurements': 'get_body_measurements', 'heart_rate': 'get_heart_rate_samples',
           'workouts': 'get_workouts', 'spo2': 'get_spo2_samples', 'stress': 'get_stress_samples',
           'abnormal_heart_beat': 'get_abnormal_heart_beat_events'}
PRIVATE_FIELDS = {'user_id', 'device_id', 'id', 'source_record_id', 'sleep_id', 'workout_id', 'event_id'}


class ReadOnlyDatabase(Database):
    def __init__(self, path):
        self.db_path = Path(path).resolve()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')

        def authorize(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ:
                return sqlite3.SQLITE_OK if table in TABLES else sqlite3.SQLITE_DENY
            if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        conn.set_authorizer(authorize)
        try:
            yield conn
        finally:
            conn.close()


def strip_private(value):
    if isinstance(value, dict):
        return {k: strip_private(v) for k, v in value.items() if k not in PRIVATE_FIELDS}
    if isinstance(value, list):
        return [strip_private(v) for v in value]
    return value


def query_records(path, kind, start_date, end_date):
    if kind not in METHODS:
        raise ValueError('不支持的健康数据类型')
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if not 0 <= (end - start).days < 366:
        raise ValueError('单次查询范围必须为 1 至 366 天')
    db = ReadOnlyDatabase(path)
    with db._get_connection() as conn:
        users = set()
        for table in sorted(TABLES):
            users.update(r[0] for r in conn.execute('SELECT DISTINCT user_id FROM ' + table))
    if len(users) != 1:
        raise ValueError('数据库中需要恰好一个健康数据账号')
    service = QueryService(db, next(iter(users)))
    records = getattr(service, METHODS[kind])(start.isoformat(), end.isoformat())
    if len(records) > 2000:
        raise ValueError('结果超过 2000 条，请缩小日期范围；未截断或省略数据')
    return strip_private(records)


def main(transport='stdio'):
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    database = Path(os.environ.get('HEALTH_READONLY_DB', '/health/mi_fitness.db'))
    mcp = FastMCP('NAS Health Read Only', host='0.0.0.0', port=8323, log_level='WARNING',
                  stateless_http=True, json_response=True,
                  transport_security=TransportSecuritySettings(
                      allowed_hosts=['localhost:*', '127.0.0.1:*', 'readonly:8323'],
                      allowed_origins=[]))

    @mcp.tool(annotations={'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False})
    def get_health_records(kind: str, start_date: str, end_date: str) -> dict:
        """查询 NAS 已保存的健康记录，不触发同步。日期为北京时间 YYYY-MM-DD。

        kind: daily_activity、sleep、body_measurements、heart_rate、workouts、spo2、stress、abnormal_heart_beat。
        单次最多 366 天和 2000 条，超限请缩小范围。单位：步、米、千卡、分钟、kg、bpm、百分比。
        """
        records = query_records(database, kind, start_date, end_date)
        return {'timezone': 'Asia/Shanghai', 'kind': kind, 'count': len(records), 'data': records}

    mcp.run(transport=transport)


if __name__ == '__main__':
    main()
