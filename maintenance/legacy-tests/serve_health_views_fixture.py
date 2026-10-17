"""本机界面验收用合成数据，不连接 NAS 或小米云。"""
import datetime as dt
import logging
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'work/mi-fitness-mcp-cn/src'))
from flask import jsonify,request
from mi_fitness_mcp.web import create_app

logging.getLogger('werkzeug').disabled=True
app=create_app(backend_url='http://127.0.0.1:1')
app.config['TEMPLATES_AUTO_RELOAD']=True
days=[dt.date(2026,9,18)+dt.timedelta(days=i) for i in range(30)]
fixtures={'summary':[],'sleep':[],'heart-rate':[],'spo2':[],'stress':[], 'workouts':[], 'body-measurements':[], 'abnormal-heart-beat':[]}
for i,day in enumerate(days):
    key=day.isoformat()
    fixtures['summary'].append({'date':key,'steps':3500+i*173%7000,'distance_m':3000+i*101,'active_kcal':300+i*11})
    if i<29:
        minutes=390+i*17%160
        fixtures['sleep'].append({'start_at':f'{day-dt.timedelta(days=1)}T23:10:00+08:00','end_at':key+'T07:20:00+08:00','time_asleep_minutes':minutes,'duration_minutes':minutes,'time_awake_minutes':12,'sleep_score':80+i%9,'is_nap':False,'stages':[{'stage':'deep','minutes':120+i%25},{'stage':'light','minutes':minutes-210-i%25},{'stage':'rem','minutes':90}]})
    fixtures['heart-rate'].append({'timestamp':key+'T08:00:00+08:00','bpm':55+i%17,'sample_type':'resting'})
    for j in range(300):
        time=(dt.datetime.combine(day,dt.time(9))+dt.timedelta(minutes=j)).isoformat()+'+08:00'
        fixtures['heart-rate'].append({'timestamp':time,'bpm':60+(i+j)%35,'sample_type':'passive'})
        if j%4==0:fixtures['spo2'].append({'timestamp':time,'spo2_pct':95+j%5})
        if j%3==0:fixtures['stress'].append({'timestamp':time,'stress_score':j%60,'level':'low' if j%60<30 else 'medium'})
fixtures['body-measurements']=[{'timestamp':'2026-10-15T09:33:00+08:00','weight_kg':87.3,'bmi':28.2,'body_fat_pct':26.3,'muscle_mass_kg':69.8,'water_pct':51.7,'bone_mass_kg':3.4}]

@app.before_request
def fixture():
    if request.path=='/api/proxy_status':return jsonify({'backend_reachable':True,'backend_latency_ms':2})
    if request.path.startswith('/proxy/api/'):
        rows=fixtures.get(request.path.rsplit('/',1)[-1],[])
        lo,hi=request.args.get('start_date',''),request.args.get('end_date','9999')
        rows=[r for r in rows if lo<=str(r.get('date') or r.get('timestamp') or r.get('end_at') or r.get('start_at'))[:10]<=hi]
        sample=request.args.get('sample_type')
        if sample:rows=[r for r in rows if r.get('sample_type')==sample]
        level=request.args.get('level')
        if level:rows=[r for r in rows if r.get('level')==level]
        if request.args.get('latest_only')=='true':rows=rows[-1:]
        if request.args.get('limit'):rows=rows[:int(request.args['limit'])]
        return jsonify({'status':'ok','count':len(rows),'data':rows})

app.run(host='127.0.0.1',port=18364,debug=False,use_reloader=False)
