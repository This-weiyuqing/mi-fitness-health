"""公开节假日日历：本地优先、异步更新，不发送健康记录或登录凭据。"""
import datetime as dt
import json
import os
import threading
import time
import urllib.parse
from pathlib import Path

SOURCE = 'https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json'
MAX_BYTES = 65536


def validate_calendar(value, year):
    if not isinstance(value, dict) or type(value.get('year')) is not int or value['year'] != year:
        raise ValueError('日历年份不符')
    papers, days = value.get('papers'), value.get('days')
    if not isinstance(papers, list) or not papers or not all(
        isinstance(p, str) and urllib.parse.urlparse(p).scheme == 'https'
        and (urllib.parse.urlparse(p).hostname or '').endswith('.gov.cn') for p in papers
    ):
        raise ValueError('缺少官方日历来源')
    if not isinstance(days, list) or not 1 <= len(days) <= 120:
        raise ValueError('日历尚未发布或记录无效')
    seen = set()
    for row in days:
        if not isinstance(row, dict) or type(row.get('isOffDay')) is not bool:
            raise ValueError('无效日期分类')
        if not isinstance(row.get('date'), str):
            raise ValueError('无效日期')
        date = dt.date.fromisoformat(row['date'])
        if date.year != year or date.isoformat() != row['date'] or date in seen:
            raise ValueError('无效或重复日期')
        seen.add(date)
    return {'year': year, 'papers': papers, 'days': [
        {'date': r['date'], 'isOffDay': r['isOffDay']} for r in days
    ]}


def download_calendar(year):
    # 固定公开地址、TLS 验证、无重定向/凭据，限制下载体积和等待时间。
    import httpx
    with httpx.Client(trust_env=False, timeout=3, follow_redirects=False) as client:
        with client.stream('GET', SOURCE.format(year=year)) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError('日历文件过大')
    return json.loads(body)


class CalendarStore:
    def __init__(self, directory, bundled, fetcher=download_calendar):
        self.directory, self.bundled = Path(directory), Path(bundled)
        self.fetcher = fetcher
        self.lock = threading.Lock()
        self.values, self.attempted, self.pending = {}, {}, set()
        self.running = False

    def get(self, year):
        with self.lock:
            if year in self.values:
                return self.values[year]
            for path in [self.directory / f'{year}.json', self.bundled / f'{year}.json']:
                try:
                    if path.stat().st_size > MAX_BYTES:
                        continue
                    value = validate_calendar(json.loads(path.read_text(encoding='utf-8')), year)
                    self.values[year] = value
                    return value
                except (OSError, ValueError, TypeError, KeyError):
                    continue
            return None

    def refresh(self, year):
        try:
            value = validate_calendar(self.fetcher(year), year)
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f'{year}.json'
            temporary = path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(value, ensure_ascii=False) + '\n', encoding='utf-8')
            os.replace(temporary, path)
            with self.lock:
                self.values[year] = value
        except (OSError, ValueError, TypeError, KeyError):
            pass
        except Exception:
            # 下载超时/连接失败保持旧缓存，不能阻塞健康查询或覆盖已知日历。
            pass

    def schedule(self, years):
        current = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).year
        with self.lock:
            for year in years:
                if 2004 <= year <= current + 1 and time.monotonic() - self.attempted.get(year, -86400) >= 86400:
                    self.pending.add(year)
                    self.attempted[year] = time.monotonic()
            if self.pending and not self.running:
                self.running = True
                threading.Thread(target=self._drain, daemon=True, name='holiday-calendar').start()

    def _drain(self):
        while True:
            with self.lock:
                if not self.pending:
                    self.running = False
                    return
                year = min(self.pending)
                self.pending.remove(year)
            self.refresh(year)


def register_calendar(app, assets_path):
    from flask import jsonify, request
    store = CalendarStore(os.environ.get('MI_FITNESS_CALENDAR_DIR', '/tmp/health-calendar'),
                          assets_path / 'static' / 'calendars')
    app.extensions['workday_calendar'] = store

    @app.get('/api/calendar')
    def calendar():
        try:
            start, end = int(request.args['start']), int(request.args['end'])
            if not (2004 <= start <= end <= 2100 and end - start <= 10):
                raise ValueError()
        except (KeyError, ValueError):
            return jsonify({'error': '无效日历年份范围'}), 400
        years = list(range(start, end + 1))
        values = {str(year): store.get(year) for year in years}
        # 按需每日检查，同时预取来年，浏览器只访问本机网页服务。
        current = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).year
        store.schedule(set(years) | {current, current + 1})
        return jsonify({'years': {key: value for key, value in values.items() if value is not None}})
