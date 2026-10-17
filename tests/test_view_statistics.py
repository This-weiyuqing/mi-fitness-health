import json
import shutil
import subprocess
from pathlib import Path

import pytest

from mi_fitness_mcp.storage import Database
from mi_fitness_mcp.storage.view_queries import ViewSelection
from mi_fitness_mcp.services.view_query_service import ViewQueryService
from mi_fitness_mcp.services.query_service import QueryService

from test_view_queries import insert


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node') or 'D:/nodejs/node.exe'


def seed(db, kind):
    table, time_field, base = {
        'activity': ('daily_activity', 'date', dict(steps=100, distance_m=80, active_kcal=5)),
        'heartrate': ('heart_rate_samples', 'timestamp', dict(bpm=72, sample_type='passive')),
        'sleep': ('sleep_sessions', 'end_at', dict(sleep_id='s', start_at='2026-10-14T14:00:00Z', duration_minutes=495, time_asleep_minutes=480, time_awake_minutes=15, stages=json.dumps([dict(stage='deep', minutes=100), dict(stage='light', minutes=300), dict(stage='rem', minutes=80)]))),
        'workouts': ('workouts', 'start_at', dict(workout_id='w', end_at='2026-10-15T02:00:00Z', activity_type='run', duration_minutes=50, distance_m=8000, calories_kcal=400)),
        'body': ('body_measurements', 'timestamp', dict(weight_kg=75, bmi=22, body_fat_pct=20)),
        'spo2': ('spo2_samples', 'timestamp', dict(spo2_pct=96)),
        'stress': ('stress_samples', 'timestamp', dict(stress_score=0, level='source')),
        'abnormal': ('abnormal_heart_beat_events', 'start_at', dict(event_id='a', end_at='2026-10-15T02:00:00Z', duration_seconds=30)),
    }[kind]
    rows = []
    for n in range(4):
        row = dict(base, id=f'id{n}', **{time_field: f'2026-10-{15 + n // 3:02}' + ('' if kind == 'activity' else f'T0{n}:00:00Z')})
        if kind == 'activity':
            row.update(device_id=f'd{n}', steps=n * 100, total_kcal=None, active_minutes=None)
        elif kind == 'heartrate':
            row.update(bpm=60 + n * 20, sample_type=['resting', 'passive', 'passive', 'active'][n])
        elif kind == 'sleep':
            row.update(sleep_id=str(n), is_nap=n == 1)
            if n == 1:
                row.update(time_asleep_minutes=30, duration_minutes=30, stages=None)
            if n == 2:
                row['stages'] = json.dumps([dict(stage='deep', minutes=999)])
        elif kind == 'body':
            row['weight_kg'] = 75 - n
        elif kind == 'spo2':
            row['spo2_pct'] = 94 + n
        elif kind == 'stress':
            row['stress_score'] = [0, 26, 81, 101][n]
        elif kind == 'workouts':
            row['workout_id'] = str(n)
        elif kind == 'abnormal':
            row['event_id'] = str(n)
        insert(db, table, **row)
        if kind == 'sleep':
            row['stages'] = json.loads(row['stages']) if row['stages'] else None
        rows.append(row)
    if kind == 'activity':
        grouped = {}
        for row in rows:
            day = grouped.setdefault(row['date'], dict(date=row['date'], steps=0, distance_m=0, active_kcal=0, total_kcal=0, floors=0, active_minutes=0))
            for key in ['steps', 'distance_m', 'active_kcal', 'total_kcal', 'floors', 'active_minutes']:
                day[key] += row.get(key) or 0
        rows = list(grouped.values())
    return rows


@pytest.mark.parametrize('kind', ['activity', 'heartrate', 'sleep', 'workouts', 'body', 'spo2', 'stress', 'abnormal'])
@pytest.mark.parametrize('end_date', ['2026-10-17', '2027-10-15'])
def test_all_eight_kinds_match_frontend_baseline(tmp_path, kind, end_date):
    db = Database(tmp_path / 'synthetic.db')
    rows = seed(db, kind)
    expected = json.loads(subprocess.run([NODE, str(ROOT / 'qa/view-statistics-oracle.cjs')], cwd=ROOT,
        input=json.dumps(dict(kind=kind, rows=rows, range=dict(start='2026-10-15', end=end_date))), text=True,
        encoding='utf-8', capture_output=True, check=True).stdout)
    result = ViewQueryService(db, 'owner').get_view(ViewSelection(kind, '2026-10-15', end_date))
    s = result['statistics']
    cards = {
        'activity': [s.get('primary_sum'), s.get('total_active_kcal'), None if s.get('total_distance_m') is None else s['total_distance_m'] / 1000, result['coverage']],
        'heartrate': [s.get('passive_mean_bpm'), s.get('resting_mean_bpm'), s.get('primary_min'), s.get('primary_max')],
        'sleep': [s.get('mean_daily_asleep_minutes'), result['coverage'], s.get('mean_daily_deep_minutes'), s.get('nap_count')],
        'workouts': [s['count'], s.get('primary_sum'), None if s.get('total_distance_m') is None else s['total_distance_m'] / 1000, s.get('total_calories_kcal')],
        'body': [s.get('latest', {}).get('weight_kg'), s.get('latest', {}).get('bmi'), s.get('latest', {}).get('body_fat_pct'), s['count']],
        'spo2': [s.get('primary_mean'), s.get('primary_min'), s.get('primary_max'), result['coverage']],
        'stress': [s.get('primary_mean'), s.get('primary_min'), s.get('primary_max'), result['coverage']],
        'abnormal': [s['count'], s.get('primary_sum'), result['coverage'], None],
    }[kind]
    assert cards == pytest.approx(expected['cards'], abs=1e-9)
    assert result['coverage'] == expected['coverage']
    assert result['stride'] == expected['stride']
    assert s['count'] == expected['count']
    assert len(result['points']) <= 120
    for actual, wanted in zip(result['points'], expected['points'], strict=True):
        assert actual['date'] == wanted['date']
        assert actual['values'] == pytest.approx(wanted['values'], abs=1e-9)
        assert actual['missing'] == wanted['missing']
    if 'average' in expected['references']:
        reference = s['mean_daily_steps'] if kind == 'activity' else s['mean_daily_asleep_minutes'] / 60 if kind == 'sleep' else s['primary_mean']
        assert reference == pytest.approx(expected['references']['average'], abs=1e-9)


def test_overview_and_empty_statistics(tmp_path):
    db = Database(tmp_path / 'synthetic.db')
    service = ViewQueryService(db, 'owner')
    empty = service.get_view(ViewSelection('stress', '2026-10-15', '2026-10-15'))
    assert empty['statistics']['primary_mean'] is None
    assert empty['statistics']['primary_sum'] is None
    assert empty['page'] == dict(number=1, size=10, total=0, rows=[])
    for kind in ['activity', 'heartrate', 'sleep', 'spo2', 'stress']:
        seed(db, kind)
    overview = service.get_overview('2026-10-15', '2026-10-17')
    assert set(overview) == {'steps', 'active_kcal', 'distance_m', 'resting_mean_bpm', 'mean_daily_asleep_minutes', 'mean_spo2_pct', 'mean_stress', 'activity_days', 'sleep_days', 'resting_count', 'spo2_count'}
    assert overview['steps'] == 600
    assert overview['resting_mean_bpm'] == 60
    assert overview['mean_daily_asleep_minutes'] == 735
    assert overview['activity_days'] == 2
    assert overview['sleep_days'] == 2
    assert overview['resting_count'] == 1
    assert overview['spo2_count'] == 4


def test_sleep_reports_match_existing_query_service_and_frontend(tmp_path):
    db = Database(tmp_path / 'synthetic.db')
    for row_id, source, collected, minutes, nap in [
        ('raw', 'source:raw', '2026-10-15T01:00:00Z', 420, False),
        ('old', 'daily_report:old', '2026-10-15T02:00:00Z', 450, False),
        ('night', 'daily_report:new-night', '2026-10-15T03:00:00Z', 480, False),
        ('nap', 'daily_report:new-nap', '2026-10-15T03:00:00Z', 30, True),
    ]:
        insert(db, 'sleep_sessions', id=row_id, sleep_id=row_id, source_record_id=source,
            collected_at=collected, start_at='2026-10-14T23:00:00+08:00', end_at='2026-10-15T07:00:00+08:00',
            duration_minutes=minutes + 15, time_asleep_minutes=minutes, time_awake_minutes=15, is_nap=nap,
            stages=json.dumps([dict(stage='deep', minutes=100)]) if not nap else None)
    for include_naps in (True, False):
        records = QueryService(db, 'owner').get_sleep_sessions('2026-10-15', '2026-10-15', include_naps=include_naps)
        expected = json.loads(subprocess.run([NODE, str(ROOT / 'qa/view-statistics-oracle.cjs')], cwd=ROOT,
            input=json.dumps(dict(kind='sleep', rows=records, range=dict(start='2026-10-15', end='2026-10-15'))),
            text=True, encoding='utf-8', capture_output=True, check=True).stdout)
        result = ViewQueryService(db, 'owner').get_view(ViewSelection('sleep', '2026-10-15', '2026-10-15', include_naps=include_naps))
        assert result['statistics']['count'] == expected['count']
        assert result['statistics']['mean_daily_asleep_minutes'] == expected['cards'][0]
        assert result['points'] == expected['points']


def test_legacy_sleep_actual_fallback_and_json_stage_types(tmp_path):
    db = Database(tmp_path / 'synthetic.db')
    # 仅此合成库放宽旧字段约束，以验证历史 NULL 值的回退与 JSON 容错。
    with db._get_connection() as connection:
        connection.execute('CREATE TABLE legacy_sleep AS SELECT * FROM sleep_sessions')
        connection.execute('DROP TABLE sleep_sessions')
        connection.execute('ALTER TABLE legacy_sleep RENAME TO sleep_sessions')
        connection.commit()
    insert(db, 'sleep_sessions', id='legacy', sleep_id='legacy', start_at='2026-10-14T23:00:00+08:00',
        end_at='2026-10-15T07:00:00+08:00', duration_minutes=480, time_asleep_minutes=None,
        time_awake_minutes=0, stages=json.dumps(['ignored', dict(stage='deep', minutes='120'),
            dict(stage='deep', minutes=60), dict(stage='deep', minutes=None), dict(stage='light', minutes=300)]))
    result = ViewQueryService(db, 'owner').get_view(ViewSelection('sleep', '2026-10-15', '2026-10-15'))
    assert result['statistics']['primary_sum'] == 480
    assert result['statistics']['mean_daily_deep_minutes'] == 60
    assert result['points'][0]['values'] == [1, 5, None, 2]


def test_activity_limit_applies_to_daily_summary_and_optional_zero_fallback(tmp_path):
    db = Database(tmp_path / 'synthetic.db')
    seed(db, 'activity')
    service = ViewQueryService(db, 'owner')
    selection = ViewSelection('activity', '2026-10-15', '2026-10-17', limit=1)
    result = service.get_view(selection)
    assert result['statistics']['count'] == 1
    assert result['statistics']['primary_sum'] == 300
    assert result['statistics']['mean_daily_steps'] == 300
    assert result['page']['rows'][0]['total_kcal'] == 0
    assert result['page']['rows'][0]['active_minutes'] == 0
    assert list(service.iter_export(selection)) == result['page']['rows']
