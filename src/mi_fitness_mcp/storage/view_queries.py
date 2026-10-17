"""健康视图的共享筛选、SQLite 聚合与有界明细读取。"""

import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterator

from mi_fitness_mcp.storage import Database


@dataclass(frozen=True)
class _Kind:
    table: str
    time: str
    primary: str
    fields: tuple[str, ...]


KINDS = {
    'activity': _Kind('daily_activity', 'date', 'steps', ('date', 'steps', 'distance_m', 'active_kcal', 'total_kcal', 'floors', 'active_minutes')),
    'heartrate': _Kind('heart_rate_samples', 'timestamp', 'bpm', ('timestamp', 'bpm', 'sample_type')),
    'sleep': _Kind('sleep_sessions', 'end_at', '_asleep', ('sleep_id', 'start_at', 'end_at', 'duration_minutes', 'time_asleep_minutes', 'time_awake_minutes', 'sleep_score', 'is_nap', 'stages')),
    'workouts': _Kind('workouts', 'start_at', 'duration_minutes', ('workout_id', 'activity_type', 'start_at', 'end_at', 'duration_minutes', 'distance_m', 'calories_kcal', 'avg_heart_rate_bpm', 'max_heart_rate_bpm', 'avg_pace_sec_per_km', 'max_pace_sec_per_km', 'total_steps')),
    'body': _Kind('body_measurements', 'timestamp', 'weight_kg', ('timestamp', 'weight_kg', 'bmi', 'body_fat_pct', 'muscle_mass_kg', 'water_pct', 'bone_mass_kg', 'visceral_fat_score', 'basal_metabolism_kcal', 'metabolic_age')),
    'spo2': _Kind('spo2_samples', 'timestamp', 'spo2_pct', ('timestamp', 'spo2_pct')),
    'stress': _Kind('stress_samples', 'timestamp', 'stress_score', ('timestamp', 'stress_score', 'level')),
    'abnormal': _Kind('abnormal_heart_beat_events', 'start_at', 'duration_seconds', ('event_id', 'start_at', 'end_at', 'duration_seconds')),
}
PRESSURE_BANDS = {'relaxed': (1, 25), 'mild': (26, 50), 'moderate': (51, 80), 'severe': (81, 100)}


@dataclass(frozen=True)
class ViewSelection:
    kind: str
    start_date: str
    end_date: str
    sample_type: str | None = None
    include_naps: bool = True
    pressure_level: str | None = None
    latest_only: bool = False
    limit: int | None = None

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError('不支持的查询类型')
        try:
            start, end = date.fromisoformat(self.start_date), date.fromisoformat(self.end_date)
        except (TypeError, ValueError):
            raise ValueError('日期必须为 YYYY-MM-DD') from None
        if start.isoformat() != self.start_date or end.isoformat() != self.end_date:
            raise ValueError('日期必须为 YYYY-MM-DD')
        if not 1 <= (end - start).days + 1 <= 3660:
            raise ValueError('请选择有效日期范围（最多3660天）')
        if self.limit is not None and (type(self.limit) is not int or self.limit <= 0):
            raise ValueError('数量限制必须为正整数')
        if self.pressure_level is not None and self.pressure_level not in (*PRESSURE_BANDS, 'unclassified'):
            raise ValueError('不支持的压力等级')
        if self.sample_type is not None and (not isinstance(self.sample_type, str) or not self.sample_type or len(self.sample_type) > 100):
            raise ValueError('采样类型必须为非空短字符串')
        if type(self.include_naps) is not bool or type(self.latest_only) is not bool:
            raise ValueError('小睡及最新记录筛选必须为布尔值')

    @property
    def days(self) -> int:
        return (date.fromisoformat(self.end_date) - date.fromisoformat(self.start_date)).days + 1

    @property
    def stride(self) -> int:
        return math.ceil(self.days / 120)


def _check_page(page: int):
    if type(page) is not int or not 1 <= page <= 1000000:
        raise ValueError('页码必须为1至1000000的整数')


class ViewRepository:
    def __init__(self, db: Database, user_id: str):
        self.db = db
        self.user_id = user_id

    @contextmanager
    def snapshot(self):
        with self.db._get_connection() as connection:
            connection.execute('PRAGMA query_only = ON')
            connection.execute('BEGIN')
            try:
                yield connection
            finally:
                connection.rollback()

    def _selection(self, selection: ViewSelection) -> tuple[str, list]:
        """所有入口共用同一 CTE；先精确筛选，再按真实时刻和主键取最近 N 条。"""
        spec = KINDS[selection.kind]
        start, end = date.fromisoformat(selection.start_date), date.fromisoformat(selection.end_date)
        if selection.kind == 'activity':
            wide_start, wide_end = selection.start_date, selection.end_date
            day_sql = 'date(date)'
            moment_sql, fraction_sql = 'unixepoch(date)', '0'
        else:
            # ISO 文本粗筛保留时区偏移余量；无时区时间按 SQLite 的 UTC 语义解释。
            wide_start = (start - timedelta(days=min(2, (start - date.min).days))).isoformat()
            wide_end = (end + timedelta(days=min(2, (date.max - end).days))).isoformat() + 'T23:59:59.999999'
            # SQLite 的日期解析会把小数秒四舍五入到毫秒，跨午夜时甚至会进位。
            # 用整秒解析时区，另保留小数秒排序，避免微秒记录被主键错误重排。
            timestamp = spec.time
            zone = f"CASE WHEN substr({timestamp}, -6, 1) IN ('+', '-') THEN substr({timestamp}, -6) WHEN substr({timestamp}, -1) = 'Z' THEN 'Z' ELSE '' END"
            whole_second = f'(substr({timestamp}, 1, 19) || ({zone}))'
            day_sql = f"date({whole_second}, '+8 hours')"
            moment_sql = f'unixepoch({whole_second})'
            fraction_sql = f"CASE WHEN substr({timestamp}, 20, 1) = '.' THEN CAST(ROUND(CAST('0.' || substr({timestamp}, 21) AS REAL) * 1000000000) AS INTEGER) ELSE 0 END"
        fields = ', '.join(('id', *spec.fields))
        private = ', source_record_id, collected_at' if selection.kind == 'sleep' else ''
        sql = f"""WITH candidates AS (
            SELECT {fields}{private}, {day_sql} AS _day, {moment_sql} AS _moment, {fraction_sql} AS _fraction
            FROM {spec.table} WHERE user_id = ? AND {spec.time} >= ? AND {spec.time} <= ?
        ), ranged AS (
            SELECT * FROM candidates WHERE _day BETWEEN ? AND ?
        )"""
        parameters = [self.user_id, wide_start, wide_end, selection.start_date, selection.end_date]
        source = 'ranged'
        if selection.kind == 'activity':
            # 与旧 QueryService 一致：设备活动先合为日报，三个可选字段回退 0。
            sums = []
            for field in spec.fields:
                if field == 'date':
                    continue
                expression = f'SUM({field})'
                if field in ('total_kcal', 'floors', 'active_minutes'):
                    expression = f'COALESCE({expression}, 0)'
                sums.append(f'{expression} AS {field}')
            sql += f", normalized AS (SELECT MAX(id) AS id, _day AS date, _day, MAX(_moment) AS _moment, 0 AS _fraction, {', '.join(sums)} FROM ranged GROUP BY _day)"
            source = 'normalized'
        elif selection.kind == 'sleep':
            sql += """, reports AS (
                SELECT *, MAX(CASE WHEN source_record_id LIKE 'daily_report:%' THEN COALESCE(collected_at, '') END)
                    OVER (PARTITION BY _day) AS _report FROM ranged
            ), sessions AS (
                SELECT * FROM reports WHERE _report IS NULL OR
                    (source_record_id LIKE 'daily_report:%' AND COALESCE(collected_at, '') = _report)
            ), normalized AS (
                SELECT *, COALESCE(time_asleep_minutes, duration_minutes) AS _asleep"""
            # JSON 只在 SQLite 内展开；缺失阶段和非法源 JSON 均保留 NULL。
            for phase in ('deep', 'light', 'rem'):
                value = "CASE WHEN j.type = 'object' THEN j.value ELSE '{}' END"
                sql += f""", (SELECT SUM(json_extract({value}, '$.minutes'))
                    FROM json_each(CASE WHEN json_valid(stages) THEN
                        CASE WHEN json_type(stages) = 'array' THEN stages ELSE '[]' END ELSE '[]' END) AS j
                    WHERE json_extract({value}, '$.stage') = '{phase}'
                    AND json_type({value}, '$.minutes') IN ('integer', 'real')) AS _{phase}"""
            sql += ' FROM sessions)'
            source = 'normalized'
        filters = []
        if selection.kind == 'heartrate' and selection.sample_type is not None:
            filters.append('sample_type = ?')
            parameters.append(selection.sample_type)
        if selection.kind == 'sleep' and not selection.include_naps:
            filters.append('COALESCE(is_nap, 0) = 0')
        if selection.kind == 'stress' and selection.pressure_level is not None:
            if selection.pressure_level == 'unclassified':
                filters.append('(stress_score IS NULL OR stress_score < 1 OR stress_score > 100)')
            else:
                filters.append('stress_score BETWEEN ? AND ?')
                parameters.extend(PRESSURE_BANDS[selection.pressure_level])
        limit = 1 if selection.latest_only else selection.limit if selection.limit is not None else -1
        sql += f", selected AS (SELECT * FROM {source} {'WHERE ' + ' AND '.join(filters) if filters else ''} ORDER BY _moment DESC, _fraction DESC, id DESC LIMIT ?) "
        parameters.append(limit)
        return sql, parameters

    def _projection(self, selection: ViewSelection) -> str:
        fields = ['id', *KINDS[selection.kind].fields]
        if selection.kind == 'sleep':
            fields.extend(('_asleep', '_deep', '_light', '_rem'))
        return ', '.join(fields)

    def _record(self, row: sqlite3.Row, selection: ViewSelection) -> dict:
        record = dict(row)
        if selection.kind == 'sleep':
            record['is_nap'] = bool(record['is_nap'])
            try:
                stages = json.loads(record['stages']) if record['stages'] else None
                record['stages'] = stages if isinstance(stages, list) else None
            except (TypeError, ValueError):
                record['stages'] = None
        return record

    def statistics(self, selection: ViewSelection, connection: sqlite3.Connection) -> dict:
        sql, parameters = self._selection(selection)
        field = KINDS[selection.kind].primary
        expressions = ['COUNT(*) AS count', 'COUNT(DISTINCT _day) AS coverage',
                       f'SUM({field}) AS primary_sum', f'AVG({field}) AS primary_mean',
                       f'MIN({field}) AS primary_min', f'MAX({field}) AS primary_max']
        if selection.kind in ('activity', 'workouts'):
            expressions.append('SUM(distance_m) AS total_distance_m')
        if selection.kind == 'activity':
            expressions.extend(('SUM(active_kcal) AS total_active_kcal', 'SUM(total_kcal) AS total_calories_kcal',
                'COUNT(DISTINCT _day) AS activity_days',
                '(SELECT AVG(value) FROM (SELECT SUM(steps) AS value FROM selected GROUP BY _day)) AS mean_daily_steps'))
        elif selection.kind == 'workouts':
            expressions.append('SUM(calories_kcal) AS total_calories_kcal')
        elif selection.kind == 'heartrate':
            expressions.extend(("AVG(CASE WHEN sample_type = 'passive' THEN bpm END) AS passive_mean_bpm",
                                "AVG(CASE WHEN sample_type = 'resting' THEN bpm END) AS resting_mean_bpm"))
        elif selection.kind == 'sleep':
            expressions.extend(('SUM(CASE WHEN is_nap THEN 1 ELSE 0 END) AS nap_count',
                '(SELECT AVG(value) FROM (SELECT SUM(_asleep) AS value FROM selected GROUP BY _day)) AS mean_daily_asleep_minutes',
                '(SELECT AVG(value) FROM (SELECT SUM(_deep) AS value FROM selected GROUP BY _day)) AS mean_daily_deep_minutes'))
        result = dict(connection.execute(sql + 'SELECT ' + ', '.join(expressions) + ' FROM selected', parameters).fetchone())
        if selection.kind == 'sleep' and result['nap_count'] is None:
            result['nap_count'] = 0
        if selection.kind in ('body', 'abnormal'):
            row = connection.execute(sql + f'SELECT {self._projection(selection)} FROM selected ORDER BY _moment DESC, _fraction DESC, id DESC LIMIT 1', parameters).fetchone()
            result['latest'] = self._record(row, selection) if row is not None else None
        return result

    def points(self, selection: ViewSelection, connection: sqlite3.Connection) -> list[dict]:
        sql, parameters = self._selection(selection)
        field = KINDS[selection.kind].primary
        sql += ', bucketed AS (SELECT *, CAST((julianday(_day) - julianday(?)) / ? AS INTEGER) AS _bucket FROM selected) '
        parameters.extend((selection.start_date, selection.stride))
        if selection.kind == 'body':
            sql += f', ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY _bucket ORDER BY _moment DESC, _fraction DESC, id DESC) AS _rank FROM bucketed WHERE {field} IS NOT NULL) SELECT _bucket, {field} AS v0 FROM ranked WHERE _rank = 1'
        else:
            if selection.kind == 'sleep':
                values = ['SUM(_asleep)', 'SUM(_deep)', 'SUM(_light)', 'SUM(_rem)']
            elif selection.kind == 'heartrate':
                values = ["AVG(CASE WHEN sample_type = 'passive' THEN bpm END)",
                          "AVG(CASE WHEN sample_type = 'resting' THEN bpm END)",
                          "AVG(CASE WHEN sample_type NOT IN ('passive', 'resting') OR sample_type IS NULL THEN bpm END)"]
            else:
                aggregate = 'SUM' if selection.kind in ('activity', 'workouts') else 'AVG'
                values = ['COUNT(*)' if selection.kind == 'abnormal' else f'{aggregate}({field})']
            sql += 'SELECT _bucket, ' + ', '.join(f'{expression} AS v{n}' for n, expression in enumerate(values)) + ' FROM bucketed GROUP BY _bucket'
        buckets = {row['_bucket']: dict(row) for row in connection.execute(sql, parameters)}
        count = 4 if selection.kind == 'sleep' else 3 if selection.kind == 'heartrate' else 1
        start = date.fromisoformat(selection.start_date)
        points = []
        for day in range(0, selection.days, selection.stride):
            row = buckets.get(day // selection.stride)
            values = [row[f'v{n}'] for n in range(count)] if row else [None] * count
            if selection.kind == 'sleep':
                total, *stages = values
                phase_sum = sum(value or 0 for value in stages)
                if total is None:
                    values = [None] * 4
                elif phase_sum > total:
                    values = [None, None, None, total / 60]
                else:
                    values = [None if value is None else value / 60 for value in stages]
                    values.append(max(0, total - phase_sum) / 60)
            points.append(dict(date=(start + timedelta(days=day)).isoformat(), values=values, missing=all(value is None for value in values)))
        return points

    def page(self, selection: ViewSelection, page: int, connection: sqlite3.Connection) -> dict:
        _check_page(page)
        sql, parameters = self._selection(selection)
        total = connection.execute(sql + 'SELECT COUNT(*) FROM selected', parameters).fetchone()[0]
        rows = connection.execute(sql + f'SELECT {self._projection(selection)} FROM selected ORDER BY _moment DESC, _fraction DESC, id DESC LIMIT 10 OFFSET ?', [*parameters, (page - 1) * 10])
        return dict(number=page, size=10, total=total, rows=[self._record(row, selection) for row in rows])

    def iter_records(self, selection: ViewSelection, connection: sqlite3.Connection) -> Iterator[dict]:
        sql, parameters = self._selection(selection)
        cursor = connection.execute(sql + f'SELECT {self._projection(selection)} FROM selected ORDER BY _moment DESC, _fraction DESC, id DESC', parameters)
        try:
            while batch := cursor.fetchmany(256):
                for row in batch:
                    yield self._record(row, selection)
        finally:
            cursor.close()
