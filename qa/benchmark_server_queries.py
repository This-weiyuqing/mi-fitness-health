"""合成只读库的旧查询基线、新汇总、分页与 CSV 对照；输出到 artifacts。"""
import argparse
import csv
import gc
import io
import json
import math
import shutil
import subprocess
import time
import tracemalloc
from collections import Counter
from dataclasses import replace

from serve_query_fixture import KINDS, OWNER, ROOT, ReadOnlyDatabase, artifact_path, generate
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.services.view_query_service import ViewQueryService
from mi_fitness_mcp.storage.view_queries import KINDS as SPECS, ViewSelection
from mi_fitness_mcp.api import VIEW_CSV_COLUMNS, _view_csv_chunks

METHODS = dict(zip(KINDS, ['get_daily_summaries', 'get_heart_rate_samples', 'get_sleep_sessions', 'get_workouts', 'get_body_measurements', 'get_spo2_samples', 'get_stress_samples', 'get_abnormal_heart_beat_events']))


def measured(call):
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    value = call()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return value, dict(seconds=round(elapsed, 4), python_peak_bytes=peak)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def test_payload_does_not_scale_with_raw_samples(results):
    for kind in ('heartrate', 'spo2', 'stress'):
        a, b = [next(row for row in results if row['density'] == density and row['kind'] == kind) for density in (1, 10)]
        assert b['raw_count'] == a['raw_count'] * 10
        assert b['summary_bytes'] < a['summary_bytes'] * 1.25, (kind, a, b)
        assert a['detail_rows'] == b['detail_rows'] == 10
        assert a['point_count'] == b['point_count'] == 30


def cards(kind, result):
    s = result['statistics']
    return {
        'activity': [s.get('primary_sum'), s.get('total_active_kcal'), (s.get('total_distance_m') or 0) / 1000, result['coverage']],
        'heartrate': [s.get('passive_mean_bpm'), s.get('resting_mean_bpm'), s.get('primary_min'), s.get('primary_max')],
        'sleep': [s.get('mean_daily_asleep_minutes'), result['coverage'], s.get('mean_daily_deep_minutes'), s.get('nap_count')],
        'workouts': [s['count'], s.get('primary_sum'), (s.get('total_distance_m') or 0) / 1000, s.get('total_calories_kcal')],
        'body': [(s.get('latest') or {}).get('weight_kg'), (s.get('latest') or {}).get('bmi'), (s.get('latest') or {}).get('body_fat_pct'), s['count']],
        'spo2': [s.get('primary_mean'), s.get('primary_min'), s.get('primary_max'), result['coverage']],
        'stress': [s.get('primary_mean'), s.get('primary_min'), s.get('primary_max'), result['coverage']],
        'abnormal': [s['count'], s.get('primary_sum'), result['coverage'], None],
    }[kind]


def close_enough(actual, expected):
    if isinstance(expected, (int, float)):
        assert math.isclose(actual, expected, abs_tol=1e-8), (actual, expected)
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected):
            close_enough(a, b)
    elif isinstance(expected, dict):
        for key, value in expected.items():
            close_enough(actual[key], value)
    else:
        assert actual == expected, (actual, expected)


def consistency(db, node):
    old, new = QueryService(db, OWNER), ViewQueryService(db, OWNER)
    checked = []
    for days, start in [(7, '2026-10-11'), (30, '2026-09-18')]:
        for kind in KINDS:
            selection = ViewSelection(kind, start, '2026-10-17')
            rows = getattr(old, METHODS[kind])(start, selection.end_date)
            expected = json.loads(subprocess.run([node, str(ROOT / 'qa/view-statistics-oracle.cjs')], cwd=ROOT,
                input=encoded(dict(kind=kind, rows=rows, range=dict(start=start, end=selection.end_date))).decode('utf-8'),
                text=True, encoding='utf-8', capture_output=True, check=True).stdout)
            result = new.get_view(selection)
            if kind == 'body':
                # 多设备同刻的旧接口次序未定义，冻结oracle保持原样；单独按批准规格验新主键次序。
                with db._get_connection() as conn:
                    stable = dict(conn.execute('SELECT id,weight_kg,bmi,body_fat_pct FROM body_measurements WHERE user_id=? ORDER BY timestamp DESC,id DESC LIMIT 1', (OWNER,)).fetchone())
                assert result['statistics']['latest']['id'] == stable['id']
                close_enough(cards(kind, result)[:3], [stable['weight_kg'], stable['bmi'], stable['body_fat_pct']])
                assert cards(kind, result)[3] == expected['cards'][3]
                close_enough(result['statistics']['primary_mean'], sum(row['weight_kg'] for row in rows) / len(rows))
                for point in result['points']:
                    with db._get_connection() as conn:
                        wanted = conn.execute('SELECT weight_kg FROM body_measurements WHERE user_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp DESC,id DESC LIMIT 1', (OWNER, point['date'])).fetchone()[0]
                    close_enough(point['values'], [wanted])
            else:
                close_enough(cards(kind, result), expected['cards'])
                close_enough(result['points'], expected['points'])
            assert result['coverage'] == expected['coverage']
            assert result['statistics']['count'] == expected['count']
            # CSV 与旧查询逐行业务字段集合核对；投影附加字段另由专项测试验证。
            data = b''.join(_view_csv_chunks(new, selection)).decode('utf-8-sig')
            parsed = list(csv.reader(io.StringIO(data)))
            columns = [field for field, _ in VIEW_CSV_COLUMNS[kind]]
            shared = [field for field in columns if all(field in row for row in rows)]
            def cell(value):
                return '' if value is None else json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(int(value)) if isinstance(value, bool) else str(value)
            actual = Counter(tuple(row[columns.index(field)] for field in shared) for row in parsed[1:])
            wanted = Counter(tuple(str(bool(row.get(field))) if field == 'is_nap' else cell(row.get(field)) for field in shared) for row in rows)
            assert actual == wanted, (kind, days, 'CSV集合不一致')
            # 有界31条检查分页并集；body/workouts/abnormal 包含相同时间的稳定id次序。
            limited = replace(selection, limit=31)
            exported = list(new.iter_export(limited))
            pages = sum([new.get_page(limited, page)['page']['rows'] for page in range(1, (len(exported) + 9) // 10 + 1)], [])
            assert pages == exported
            assert len({row['id'] for row in pages}) == len(pages)
            assert new.get_page(limited, 1)['page']['rows'] == pages[:10]
            checked.append(dict(kind=kind, days=days, count=len(rows), csv_rows=len(parsed) - 1, pagination_rows=len(pages)))
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'artifacts/query-summary/benchmark.json'))
    parser.add_argument('--node', default=shutil.which('node') or 'D:/nodejs/node.exe')
    args = parser.parse_args()
    output = artifact_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(scope='本机合成数据；没有NAS性能实测', measurements=[], consistency=[])
    for density in (1, 10):
        path = output.parent / f'synthetic-{density}x.db'
        if not path.exists():
            generate(path, density)
        db = ReadOnlyDatabase(path)
        old, new = QueryService(db, OWNER), ViewQueryService(db, OWNER)
        for kind in ('heartrate', 'spo2', 'stress'):
            rows, baseline = measured(lambda: getattr(old, METHODS[kind])('2026-09-18', '2026-10-17'))
            raw_bytes = len(encoded(dict(status='ok', count=len(rows), data=rows)))
            raw_count = len(rows)
            del rows
            result, summary = measured(lambda: new.get_view(ViewSelection(kind, '2026-09-18', '2026-10-17')))
            assert set(result) == {'status', 'kind', 'range', 'statistics', 'points', 'coverage', 'stride', 'page'}
            assert len(result['page']['rows']) == 10 and len(result['points']) <= 120
            row = dict(density=density, kind=kind, raw_count=raw_count, raw_json_bytes=raw_bytes, summary_bytes=len(encoded(result)), detail_rows=len(result['page']['rows']), point_count=len(result['points']), baseline=baseline, summary=summary)
            report['measurements'].append(row)
            print(json.dumps(row), flush=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if density == 1:
            report['consistency'] = consistency(db, args.node)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    test_payload_does_not_scale_with_raw_samples(report['measurements'])
    report['test_payload_does_not_scale_with_raw_samples'] = 'PASS'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('PASS: 16组统计/CSV/分页对照；1x/10x首屏有界。')


if __name__ == '__main__':
    main()
