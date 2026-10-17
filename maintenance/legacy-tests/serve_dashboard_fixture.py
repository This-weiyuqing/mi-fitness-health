"""仅本机界面核验：使用固定示例响应，不连接 NAS 或小米云。"""
import logging
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'work/mi-fitness-mcp-cn/src'))
from flask import jsonify, request
from mi_fitness_mcp.web import create_app

logging.getLogger('werkzeug').disabled=True
app=create_app(backend_url='http://127.0.0.1:1')
fixtures={
    'summary':[{'date':'2026-10-15','steps':4691,'active_kcal':596,'distance_m':2979},{'date':'2026-10-16','steps':4063,'active_kcal':250,'distance_m':2385}],
    'heart-rate':[{'timestamp':'2026-10-16T09:00:00+08:00','bpm':62},{'timestamp':'2026-10-15T09:00:00+08:00','bpm':58}],
    'sleep':[{'end_at':'2026-10-16T08:54:00+08:00','duration_minutes':517},{'end_at':'2026-10-15T07:55:00+08:00','duration_minutes':474}],
    'spo2':[{'timestamp':'2026-10-16T09:00:00+08:00','spo2_pct':98},{'timestamp':'2026-10-15T09:00:00+08:00','spo2_pct':96}],
    'stress':[{'timestamp':'2026-10-16T09:00:00+08:00','stress_score':0},{'timestamp':'2026-10-15T09:00:00+08:00','stress_score':60}],
}

@app.before_request
def local_fixture():
    if request.path=='/api/proxy_status':
        return jsonify({'backend_reachable':True,'backend_latency_ms':1})
    if request.path.startswith('/proxy/api/'):
        rows=fixtures.get(request.path.rsplit('/',1)[-1],[])
        return jsonify({'status':'ok','count':len(rows),'data':rows})

@app.after_request
def exercise_preset(response):
    if response.mimetype=='text/html' and request.args.get('preset')=='30d':
        html=response.get_data(as_text=True)
        clock="<script>const RealTestDate=Date; window.Date=class extends RealTestDate {constructor(...args){super(...(args.length?args:['2026-10-16T12:00:00+08:00']));}static now(){return new RealTestDate('2026-10-16T12:00:00+08:00').getTime();}};</script>"
        click="<script>document.addEventListener('DOMContentLoaded',()=>setTimeout(()=>document.getElementById('preset-30d').click(),100));</script>"
        html=html.replace('<script src="/static/js/app.js',clock+'<script src="/static/js/app.js',1)
        html=html.replace('</body>',click+'</body>')
        response.set_data(html)
    return response

app.run(host='127.0.0.1',port=18362,debug=False,use_reloader=False)
