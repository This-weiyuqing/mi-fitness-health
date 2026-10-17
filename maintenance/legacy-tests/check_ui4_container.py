"""仅本机 Linux 容器验收，使用临时虚构凭据，不连接 NAS。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

docker='C:/Users/35861/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe'
prefix=[docker,'--context','desktop-linux']
image='local/mi-fitness-nas:20261017-ui4'
name='mi-fitness-ui4-local-check'
env={**os.environ,'MI_FITNESS_WEB_PASSWORD':'Local-UI4-Validation-Only','MI_FITNESS_ADMIN_KEY':'local-validation-admin-key'}
def run(args,stdin=None):
    p=subprocess.run(prefix+args,input=stdin.encode('utf-8') if stdin is not None else None,capture_output=True,env=env)
    if p.returncode:raise RuntimeError(p.stderr.decode('utf-8')[-1800:])
    return p.stdout.decode('utf-8')

check=r'''
import os,json,time,base64,urllib.request,urllib.error
token=base64.b64encode(('admin:'+os.environ['MI_FITNESS_WEB_PASSWORD']).encode()).decode()
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(path,auth=True):
 r=urllib.request.Request('http://127.0.0.1:8322'+path,headers={'Authorization':'Basic '+token} if auth else {})
 with opener.open(r,timeout=3) as response:return response.status,response.read().decode('utf-8')
for i in range(30):
 try:
  status,html=get('/');break
 except OSError:time.sleep(.5)
else:raise RuntimeError('网页容器未就绪')
assert status==200 and '20261017-ui4' in html
for kind in ['activity','heartrate','sleep','workouts','body','spo2','stress','abnormal']:
 assert 'id="healthView-'+kind+'"' in html
assets={}
for path,marker in [('/static/js/health-views.js','HealthViews'),('/static/js/health-ui.js','loadHealthView'),('/static/css/health.css','health-cards'),('/static/js/app.js','reloadActiveView')]:
 status,text=get(path);assert status==200 and marker in text;assets[path]=len(text)
try:get('/',False)
except urllib.error.HTTPError as e:assert e.code==401
else:raise RuntimeError('匿名访问未被拦截')
assert 'inspector-collapsed' in html and 'id="inspectorPanel" hidden' in html
print(json.dumps({'authenticated_http':200,'anonymous_http':401,'query_views':8,'console_default_collapsed':True,'assets':assets}))
'''
try:
    run(['run','-d','--name',name,'--network','none','--read-only','--tmpfs','/tmp:rw,noexec,nosuid,size=32m','--cap-drop','ALL','--security-opt','no-new-privileges:true','--memory','256m','--cpus','0.5','-e','MI_FITNESS_WEB_PASSWORD','-e','MI_FITNESS_ADMIN_KEY',image,'web'])
    result=json.loads(run(['exec','-i',name,'python','-'],check))
    config=json.loads(run(['inspect',name]))[0]
    assert config['HostConfig']['ReadonlyRootfs'] and config['HostConfig']['NetworkMode']=='none'
    assert not config['HostConfig']['PortBindings']
    result['network']='none';result['host_ports']=[]
    run(['exec','-i',name,'sh','-n'],Path('outputs/health-query-ui4/update-web.sh').read_text(encoding='utf-8'))
    result['installer_shell_syntax']='ok'
    result['image_id']=json.loads(run(['image','inspect',image]))[0]['Id']
    Path('outputs/health-query-ui4/local-container-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
finally:
    # 只删除本次创建、含虚构配置且无持久卷的验收容器。
    subprocess.run(prefix+['rm','-f',name],capture_output=True)
