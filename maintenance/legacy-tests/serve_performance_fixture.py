"""仅本机浏览器性能复现，固定合成30天记录，无真实账号或云端请求。"""
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/mi-fitness-mcp-cn/src'))
from flask import jsonify, request, send_file
from mi_fitness_mcp.web import create_app

logging.getLogger('werkzeug').disabled = True
app = create_app(backend_url='http://127.0.0.1:1')
start = datetime(2026, 9, 18, tzinfo=timezone(timedelta(hours=8)))
def samples(count, field, value):
    return [{'timestamp': (start + timedelta(seconds=i*30*86400/count)).isoformat(), field: value} for i in range(count)]
fixtures = {
    'summary': [{'date': (start+timedelta(days=i)).date().isoformat(), 'steps': 6000+i, 'active_kcal': 500+i, 'distance_m': 4000+i} for i in range(30)],
    'heart-rate': samples(19, 'bpm', 62),
    'sleep': [{'end_at': (start+timedelta(days=i,hours=8)).isoformat(), 'duration_minutes': 450} for i in range(30)],
    'spo2': samples(2000, 'spo2_pct', 97),
    'stress': samples(3000, 'stress_score', 30),
}

@app.before_request
def local_fixture():
    if request.path == '/api/proxy_status':
        return jsonify({'backend_reachable': True, 'backend_latency_ms': 1})
    if request.path.startswith('/proxy/api/'):
        rows = fixtures.get(request.path.rsplit('/',1)[-1], [])
        sd, ed = request.args.get('start_date'), request.args.get('end_date')
        if sd and ed:
            rows = [row for row in rows if sd <= (row.get('date') or row.get('end_at') or row.get('timestamp'))[:10] <= ed]
        return jsonify({'status':'ok','count':len(rows),'data':rows})

@app.route('/benchmark/before.js')
def baseline_script():
    return send_file(ROOT/'work/perf-validation/app.before.js', mimetype='application/javascript')

@app.route('/benchmark/before.css')
def baseline_styles():
    return send_file(ROOT/'work/perf-validation/style.before.css', mimetype='text/css')

@app.after_request
def baseline_version(response):
    if response.mimetype == 'text/html' and request.args.get('version') == 'before':
        import re
        text = re.sub(r'/static/js/app\.js\?v=[^"\s]+', '/benchmark/before.js', response.get_data(as_text=True))
        response.set_data(re.sub(r'/static/css/style\.css(?:\?v=[^"\s]+)?', '/benchmark/before.css', text))
    return response

app.run(host='127.0.0.1', port=18363, debug=False, use_reloader=False)
