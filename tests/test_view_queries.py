import json
from contextlib import contextmanager

import pytest

from mi_fitness_mcp.storage import Database
from mi_fitness_mcp.storage.view_queries import ViewRepository, ViewSelection
from mi_fitness_mcp.services.view_query_service import ViewQueryService


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / 'synthetic.db')


def insert(db, table, **fields):
    fields = {'provider': 'synthetic', 'source_type': 'test', 'user_id': 'owner', **fields}
    with db._get_connection() as connection:
        connection.execute(
            f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
            tuple(fields.values()),
        )
        connection.commit()


def test_selection_before_limit_and_paging(db):
    for n in range(31):
        insert(db, 'stress_samples', id=f's{n:02}', timestamp=f'2026-10-15T00:{n:02}:00Z',
               stress_score=26 + n if n < 25 else 90, level='source-level')
    service = ViewQueryService(db, 'owner')
    selection = ViewSelection('stress', '2026-10-15', '2026-10-15', pressure_level='mild', limit=11)
    result = service.get_view(selection)
    assert result['statistics']['count'] == 11
    assert result['statistics']['primary_mean'] == pytest.approx(sum(range(40, 51)) / 11)
    assert result['page']['total'] == 11
    assert len(result['page']['rows']) == 10
    page = service.get_page(selection, 2)
    assert set(page) == {'status', 'kind', 'range', 'page'}
    assert len(page['page']['rows']) == 1
    exported = list(service.iter_export(selection))
    assert exported == result['page']['rows'] + page['page']['rows']
    assert [r['stress_score'] for r in exported] == list(range(50, 39, -1))
    assert all(row['level'] == 'source-level' for row in exported)


def test_equal_timestamps_stable_order_and_owner_isolation(db):
    for n in range(24):
        insert(db, 'body_measurements', id=f'b{n:02}', timestamp='2026-10-15T00:00:00Z',
               device_id=f'private-device-{n}', weight_kg=60 + n)
    insert(db, 'body_measurements', id='outsider', user_id='other', device_id='other',
           timestamp='2026-10-15T00:00:00Z', weight_kg=999)
    service = ViewQueryService(db, 'owner')
    selection = ViewSelection('body', '2026-10-15', '2026-10-15')
    pages = [service.get_page(selection, n)['page']['rows'] for n in (1, 2, 3)]
    records = sum(pages, [])
    assert records == list(service.iter_export(selection))
    assert pages[0] == service.get_page(selection)['page']['rows']
    assert [r['weight_kg'] for r in records] == list(range(83, 59, -1))
    assert len({r['id'] for r in records}) == 24
    assert not any(set(row) & {'user_id', 'device_id', 'source_record_id', 'provider'} for row in records)
    limited = service.get_view(ViewSelection('body', '2026-10-15', '2026-10-15', latest_only=True))
    assert limited['statistics']['count'] == 1
    assert limited['statistics']['latest']['weight_kg'] == 83
    for n, sample_type in enumerate(['resting', 'passive', 'active']):
        insert(db, 'heart_rate_samples', id=f'h{n}', timestamp='2026-10-15T00:00:00Z',
               bpm=60 + n * 10, sample_type=sample_type)
    resting = service.get_view(ViewSelection('heartrate', '2026-10-15', '2026-10-15', sample_type='resting', limit=1))
    assert resting['statistics']['primary_mean'] == 60
    assert resting['page']['rows'][0]['sample_type'] == 'resting'


def test_china_midnight_sleep_and_nulls(db):
    insert(db, 'sleep_sessions', id='night', sleep_id='night', start_at='2026-10-14T16:00:00Z',
           end_at='2026-10-15T00:15:00Z', duration_minutes=495, time_asleep_minutes=480,
           time_awake_minutes=15, stages=json.dumps([{'stage': 'deep', 'minutes': 120}]))
    insert(db, 'sleep_sessions', id='nap', sleep_id='nap', start_at='2026-10-15T05:00:00Z',
           end_at='2026-10-15T05:30:00Z', duration_minutes=30, time_asleep_minutes=30,
           time_awake_minutes=0, is_nap=1, stages=None)
    insert(db, 'sleep_sessions', id='next', sleep_id='next', start_at='2026-10-15T15:00:00Z',
           end_at='2026-10-15T16:30:00Z', duration_minutes=90, time_asleep_minutes=90,
           time_awake_minutes=0, stages='not-json')
    service = ViewQueryService(db, 'owner')
    result = service.get_view(ViewSelection('sleep', '2026-10-15', '2026-10-17'))
    assert result['statistics']['primary_sum'] == 600
    assert result['statistics']['mean_daily_asleep_minutes'] == 300
    assert result['statistics']['mean_daily_deep_minutes'] == 120
    assert result['statistics']['nap_count'] == 1
    assert result['coverage'] == 2
    assert result['points'][0]['values'] == [2, None, None, 6.5]
    assert result['points'][1]['values'] == [None, None, None, 1.5]
    assert result['points'][2]['missing'] is True
    assert service.get_view(ViewSelection('sleep', '2026-10-15', '2026-10-15', include_naps=False))['statistics']['primary_sum'] == 480
    for n, timestamp in enumerate(['2026-10-14T16:00:00Z', '2026-10-15T00:00:00+08:00', '2026-10-14 16:00:00']):
        insert(db, 'heart_rate_samples', id=f't{n}', timestamp=timestamp, bpm=60 + n, sample_type='passive')
    assert service.get_view(ViewSelection('heartrate', '2026-10-15', '2026-10-15'))['statistics']['count'] == 3
    insert(db, 'stress_samples', id='zero', timestamp='2026-10-14T16:00:00Z', stress_score=0, level='zero')
    zero = service.get_view(ViewSelection('stress', '2026-10-15', '2026-10-16'))
    assert zero['statistics']['primary_mean'] == 0
    assert zero['points'][1]['values'] == [None]


def test_sleep_daily_report_supersedes_raw_and_old_report(db):
    for row_id, source, collected, minutes in [('raw', 'raw:1', '2026-10-15', 400),
            ('old', 'daily_report:1', '2026-10-15T01:00:00Z', 450),
            ('new', 'daily_report:2', '2026-10-15T02:00:00Z', 480)]:
        insert(db, 'sleep_sessions', id=row_id, sleep_id=row_id, source_record_id=source,
               collected_at=collected, start_at='2026-10-14T15:00:00Z', end_at='2026-10-14T23:00:00Z',
               duration_minutes=minutes, time_asleep_minutes=minutes, time_awake_minutes=0)
    result = ViewQueryService(db, 'owner').get_view(ViewSelection('sleep', '2026-10-15', '2026-10-15'))
    assert result['statistics']['count'] == 1
    assert result['statistics']['primary_sum'] == 480


def test_body_real_instant_order_precedes_text_and_id(db):
    for row_id, timestamp, weight in [('z', '2026-10-15T09:00:00+08:00', 80),
            ('a', '2026-10-15T02:00:00Z', 70), ('y', '2026-10-14T15:59:59Z', 999)]:
        insert(db, 'body_measurements', id=row_id, timestamp=timestamp, weight_kg=weight)
    service = ViewQueryService(db, 'owner')
    result = service.get_view(ViewSelection('body', '2026-10-15', '2026-10-15', limit=1))
    assert result['statistics']['latest']['id'] == 'a'
    assert result['statistics']['primary_mean'] == 70
    assert result['points'][0]['values'] == [70]


def test_submillisecond_timestamps_still_order_by_real_instant(db):
    for row_id, timestamp, weight in [
        ('z', '2026-10-15T09:00:00.000100+08:00', 80),
        ('a', '2026-10-15T01:00:00.000200Z', 70),
        ('x', '2026-10-15T01:00:00.999900Z', 60),
        ('b', '2026-10-15T01:00:01.000000Z', 50),
    ]:
        insert(db, 'body_measurements', id=row_id, timestamp=timestamp, weight_kg=weight)
    rows = list(ViewQueryService(db, 'owner').iter_export(ViewSelection('body', '2026-10-15', '2026-10-15')))
    assert [row['id'] for row in rows] == ['b', 'x', 'a', 'z']


@pytest.mark.parametrize('level, expected', [('relaxed', [25, 1]), ('mild', [50, 26]),
    ('moderate', [80, 51]), ('severe', [100, 81]), ('unclassified', [101, 0])])
def test_pressure_numeric_bands_ignore_source_level(db, level, expected):
    for n, value in enumerate([0, 1, 25, 26, 50, 51, 80, 81, 100, 101]):
        insert(db, 'stress_samples', id=str(n), timestamp=f'2026-10-15T00:{n:02}:00Z',
               stress_score=value, level='unrelated-source-value')
    rows = list(ViewQueryService(db, 'owner').iter_export(ViewSelection('stress', '2026-10-15', '2026-10-15', pressure_level=level)))
    assert [row['stress_score'] for row in rows] == expected


def test_export_close_releases_short_read_transaction(db, monkeypatch):
    insert(db, 'stress_samples', id='one', timestamp='2026-10-15T00:00:00Z', stress_score=26, level='source')
    original = ViewRepository.snapshot
    closed = []
    @contextmanager
    def observed(repository):
        with original(repository) as connection:
            try:
                yield connection
            finally:
                closed.append(True)
    monkeypatch.setattr(ViewRepository, 'snapshot', observed)
    generator = ViewQueryService(db, 'owner').iter_export(ViewSelection('stress', '2026-10-15', '2026-10-15'))
    assert next(generator)['stress_score'] == 26
    assert not closed
    generator.close()
    assert closed == [True]


def test_first_view_uses_one_read_snapshot(db, monkeypatch):
    service = ViewQueryService(db, 'owner')
    original = ViewRepository.snapshot
    connections = []

    @contextmanager
    def observed(repository):
        with original(repository) as connection:
            assert connection.in_transaction
            connections.append(connection)
            yield connection

    monkeypatch.setattr(ViewRepository, 'snapshot', observed)
    traces = []
    for method in ['statistics', 'points', 'page']:
        implementation = getattr(ViewRepository, method)

        def wrapped(self, *args, _method=implementation, **kwargs):
            connection = kwargs.get('connection', args[-1])
            assert connection is connections[-1]
            assert connection.in_transaction
            traces.append(connection)
            return _method(self, *args, **kwargs)

        monkeypatch.setattr(ViewRepository, method, wrapped)
    service.get_view(ViewSelection('stress', '2026-10-15', '2026-10-15'))
    assert len(connections) == 1
    assert len(traces) == 3
    assert all(connection is connections[0] for connection in traces)


def test_large_input_uses_sql_paging(db, monkeypatch):
    with db._get_connection() as connection:
        connection.executemany("INSERT INTO stress_samples(id,provider,source_type,user_id,timestamp,stress_score,level) VALUES(?,?,?,?,?,?,?)",
            [(f's{n:05}', 'synthetic', 'test', 'owner', f'2026-10-15T00:00:{n % 60:02}.{n:06}Z', n % 101, 'source') for n in range(20000)])
        connection.commit()
    def forbidden(*args, **kwargs):
        raise AssertionError('must aggregate and page in SQLite')
    monkeypatch.setattr(db, 'query_stress_samples', forbidden)
    monkeypatch.setattr(ViewRepository, 'iter_records', forbidden)
    statements = []
    original = ViewRepository.snapshot
    @contextmanager
    def observed(repository):
        with original(repository) as connection:
            connection.set_trace_callback(statements.append)
            yield connection
    monkeypatch.setattr(ViewRepository, 'snapshot', observed)
    result = ViewQueryService(db, 'owner').get_view(ViewSelection('stress', '2026-10-15', '2026-10-15'), 2)
    assert result['statistics']['count'] == 20000
    assert len(result['page']['rows']) == 10
    assert len(result['points']) == 1
    assert any('LIMIT 10 OFFSET 10' in sql for sql in statements)
    assert not any('SELECT * FROM stress_samples' in sql for sql in statements)


@pytest.mark.parametrize('kwargs', [dict(kind='unknown'), dict(start_date='2026-02-30'), dict(end_date='2026-10-14'), dict(limit=0), dict(limit=True), dict(pressure_level='sql injection'), dict(start_date='2000-01-01')])
def test_invalid_selections(kwargs):
    values = dict(kind='stress', start_date='2026-10-15', end_date='2026-10-16')
    with pytest.raises(ValueError):
        ViewSelection(**(values | kwargs))


@pytest.mark.parametrize('page', [0, -1, True, 1.5, 1000001])
def test_invalid_pages(db, page):
    with pytest.raises(ValueError):
        ViewQueryService(db, 'owner').get_page(ViewSelection('stress', '2026-10-15', '2026-10-15'), page)
