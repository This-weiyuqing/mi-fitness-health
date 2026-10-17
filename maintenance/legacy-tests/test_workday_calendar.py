"""日历缓存和失败恢复验证，仅使用本机临时目录与模拟下载。"""
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mi-fitness-mcp-cn/src'))
from mi_fitness_mcp.workday_calendar import CalendarStore, validate_calendar

def data(year=2026):
    return {'year':year,'papers':['https://www.gov.cn/zhengce/example.htm'],'days':[{'date':f'{year}-01-01','name':'元旦','isOffDay':True}]}

class CalendarTest(unittest.TestCase):
    def test_reject_placeholder_wrong_year_and_malformed(self):
        for value in [{'year':2027,'papers':[],'days':[]},{**data(),'year':2027},{**data(),'days':[{'date':'2026-02-30','isOffDay':True}]},{**data(),'days':[{'date':'2026-01-01','isOffDay':1}]}]:
            with self.assertRaises(ValueError):validate_calendar(value,2026)

    def test_persist_refresh_and_keep_good_cache_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=CalendarStore(Path(tmp),Path(tmp)/'seed',fetcher=lambda year:data(year))
            store.refresh(2026)
            self.assertEqual(store.get(2026)['days'][0]['isOffDay'],True)
            restored=CalendarStore(Path(tmp),Path(tmp)/'seed',fetcher=lambda year:(_ for _ in ()).throw(OSError('offline')))
            self.assertEqual(restored.get(2026)['year'],2026)
            restored.refresh(2026)
            self.assertEqual(restored.get(2026)['year'],2026)
            restored.refresh(2027)
            self.assertIsNone(restored.get(2027))

    def test_empty_next_year_is_not_cached_as_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=CalendarStore(Path(tmp),Path(tmp)/'seed',fetcher=lambda year:{'year':year,'days':[],'papers':[]})
            store.refresh(2027)
            self.assertIsNone(store.get(2027));self.assertFalse((Path(tmp)/'2027.json').exists())

    def test_bundled_2026_is_available_without_network(self):
        root=Path(__file__).resolve().parents[1]/'mi-fitness-mcp-cn/src/mi_fitness_mcp/web_assets/static/calendars'
        with tempfile.TemporaryDirectory() as tmp:
            store=CalendarStore(Path(tmp),root)
            value=store.get(2026)
            self.assertIsNotNone(value)
            days={r['date']:r['isOffDay'] for r in value['days']}
            self.assertFalse(days['2026-09-20']);self.assertFalse(days['2026-10-10']);self.assertTrue(days['2026-10-01'])

    def test_schedule_is_nonblocking_deduplicated_and_future_limited(self):
        import threading
        import time
        entered, release = threading.Event(), threading.Event()
        calls=[]
        def fetch(year):
            calls.append(year);entered.set();release.wait(2);return data(year)
        with tempfile.TemporaryDirectory() as tmp:
            store=CalendarStore(Path(tmp),Path(tmp)/'seed',fetcher=fetch)
            started=time.monotonic();store.schedule([2026,2099]);store.schedule([2026])
            self.assertLess(time.monotonic()-started,.5);self.assertTrue(entered.wait(1))
            release.set()
            for _ in range(100):
                if not store.running:break
                time.sleep(.01)
            self.assertEqual(calls,[2026]);self.assertIsNotNone(store.get(2026))

    def test_calendar_route_uses_existing_auth_and_rejects_invalid_ranges(self):
        from mi_fitness_mcp.web import create_app
        import base64
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{'MI_FITNESS_WEB_PASSWORD':'Synthetic-calendar-only','MI_FITNESS_CALENDAR_DIR':tmp}):
            app=create_app();client=app.test_client()
            headers={'Authorization':'Basic '+base64.b64encode(b'admin:Synthetic-calendar-only').decode()}
            with patch.object(app.extensions['workday_calendar'],'schedule'):
                self.assertEqual(client.get('/api/calendar?start=2026&end=2026').status_code,401)
                result=client.get('/api/calendar?start=2026&end=2027',headers=headers)
                self.assertEqual(result.status_code,200);self.assertIn('2026',result.json['years']);self.assertNotIn('2027',result.json['years'])
                self.assertEqual(client.get('/api/calendar?start=2026&end=2100',headers=headers).status_code,400)
                self.assertEqual(client.get('/api/calendar?start=2026&end=2026',headers={**headers,'Origin':'https://untrusted.example'}).status_code,403)

if __name__=='__main__':unittest.main()
