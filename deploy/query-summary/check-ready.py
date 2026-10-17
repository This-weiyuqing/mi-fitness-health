"""部署后最小就绪核对；不查询健康记录，不输出凭据。"""
import json
import subprocess
import sys

IMAGE = 'local/mi-fitness-nas:20261017-summary8'
items = json.loads(subprocess.check_output(['docker', 'inspect', 'mi-fitness-health-backend-1', 'mi-fitness-health-web-1', 'mi-fitness-health-worker-1']))
backend, web, worker = items
assert backend['Config']['Image'] == web['Config']['Image'] == IMAGE
assert worker['Config']['Image'] == 'local/mi-fitness-nas:20261017-audit3'
if len(sys.argv) > 1:
    assert backend['Image'] == web['Image'] == sys.argv[1]
assert backend['HostConfig']['ReadonlyRootfs'] and web['HostConfig']['ReadonlyRootfs']
assert any(m['Destination'] == '/state' for m in backend['Mounts'])
assert any(m['Destination'] == '/run/secrets/keyring_master' and not m['RW'] for m in backend['Mounts'])
assert any(m['Destination'] == '/calendar' for m in web['Mounts'])
assert set(web['HostConfig']['PortBindings']) == {'8322/tcp'}
assert {(p['HostIp'], p['HostPort']) for p in web['HostConfig']['PortBindings']['8322/tcp']} == {('127.0.0.1', '18322'), ('192.168.31.201', '18322')}
# 密码只在容器内部使用，不读取到控制端、不打印、不放在命令行。
probe = r'''
import base64,json,os,urllib.error,urllib.request
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
token=base64.b64encode(('admin:'+os.environ['MI_FITNESS_WEB_PASSWORD']).encode()).decode()
def get(path,auth=True):
    req=urllib.request.Request('http://127.0.0.1:8322'+path,headers={'Authorization':'Basic '+token} if auth else {})
    try:
        with opener.open(req,timeout=10) as r:return r.status,r.read(300000).decode()
    except urllib.error.HTTPError as e:return e.code,''
assert get('/',False)[0]==401
assert '20261017-summary8' in get('/')[1]
for path,marker in [('/static/js/health-views.js','fromSummary'),('/static/js/health-ui.js','/api/views/'),('/static/js/app.js','/api/overview')]:
    status,body=get(path);assert status==200 and marker in body
assert json.loads(get('/api/proxy_status')[1])['backend_reachable']
for path in ['/proxy/api/views/stress','/proxy/api/views/stress/records','/proxy/api/views/stress/export','/proxy/api/overview']:
    assert get(path+'?start_date=invalid&end_date=invalid')[0]==422
assert os.environ.get('MI_FITNESS_CALENDAR_DIR')=='/calendar'
assert json.loads(get('/api/calendar?start=2026&end=2026')[1])['years']['2026']['days']
print('backend/web资源、代理、匿名拒绝和新路由就绪；未查询健康记录。')
'''
subprocess.run(['docker', 'exec', '-i', 'mi-fitness-health-web-1', 'python', '-'], input=probe.encode('utf-8'), check=True)
