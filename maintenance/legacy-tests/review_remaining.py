"""本机隔离复现审查发现；仅使用合成数据，不连接 NAS 或小米云。"""
import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/mi-fitness-mcp-cn/src'))
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.models import BodyMeasurement
from mi_fitness_mcp.storage import Database
from mi_fitness_mcp.web import create_app


async def pagination():
    adapter = MiFitnessCloudAdapter(user_id='synthetic', pass_token='synthetic', region='cn')
    async def request(*args):
        return {'data_list': [{'time': 123}], 'has_more': True}
    adapter._request = request
    rows = await adapter._fetch_key('heart_rate', '2026-10-15', '2026-10-16')
    return {'has_more_without_cursor_silently_accepted': len(rows) == 1}


def corrections():
    with tempfile.TemporaryDirectory(prefix='health-review-') as directory:
        db = Database(Path(directory) / 'synthetic.sqlite')
        first = BodyMeasurement(id='synthetic-weight', provider='mi_fitness',
            source_type='cloud_session', user_id='synthetic', timestamp=datetime.now(timezone.utc),
            weight_kg=87.3, bone_mass_kg=None, basal_metabolism_kcal=None)
        db.insert_body_measurement(first)
        db.insert_body_measurement(first.model_copy(update={'bone_mass_kg': 3.1, 'basal_metabolism_kcal': 1800}))
        record = db.query_body_measurements('synthetic', '2000-01-01', '2100-01-01')[0]
        return {'late_body_fields_not_updated': record['bone_mass_kg'] is None and record['basal_metabolism_kcal'] is None}


def proxy_privilege():
    seen = []
    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def request(self, **kwargs):
            seen.append(kwargs)
            import httpx
            return httpx.Response(200, json={'status': 'ok'})
    with patch('mi_fitness_mcp.web.httpx.Client', FakeClient):
        app = create_app(backend_url='http://backend:8321', admin_key='SYNTHETIC_ADMIN')
        response = app.test_client().delete('/proxy/api/auth/keys/mif_sk_demo')
    return {'unauthenticated_browser_request_gets_admin_header': response.status_code == 200 and seen[0]['headers'].get('X-Admin-Key') == 'SYNTHETIC_ADMIN'}


if __name__ == '__main__':
    print(json.dumps({**asyncio.run(pagination()), **corrections(), **proxy_privilege()}, indent=2))
