"""实际部署验证：从运行容器内部读取鉴权配置，不输出秘密。"""
import base64
import json
import subprocess
import time
import urllib.error
import urllib.request

item=json.loads(subprocess.check_output(['docker','inspect','mi-fitness-health-web-1']))[0]
assert item['Config']['Image']=='local/mi-fitness-nas:20261017-ui7','网页镜像版本不符'
env=dict(line.split('=',1) for line in item['Config']['Env'])
token=base64.b64encode(('admin:'+env['MI_FITNESS_WEB_PASSWORD']).encode('utf-8')).decode('ascii')
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def fetch(path,auth=True):
    request=urllib.request.Request('http://127.0.0.1:18322'+path,headers={'Authorization':'Basic '+token} if auth else {})
    with opener.open(request,timeout=5) as response:return response.status,response.read(2000000).decode('utf-8')
for attempt in range(30):
    try:
        status,html=fetch('/')
        assert status==200 and '20261017-ui7' in html
        for path,marker in [('/static/js/health-views.js','HealthViews'),('/static/js/health-ui.js','loadHealthView'),('/static/css/health.css','health-cards')]:
            assert marker in fetch(path)[1]
        break
    except (OSError,ValueError,AssertionError):
        if attempt==29:raise RuntimeError('网页版本或资源就绪验证失败') from None
        time.sleep(2)
try:
    fetch('/',False)
except urllib.error.HTTPError as exc:
    assert exc.code==401,'匿名访问权限异常'
else:
    raise RuntimeError('匿名访问未被拒绝')
assert json.loads(fetch('/api/calendar?start=2026&end=2026')[1])['years']['2026']['days']
assert env.get('MI_FITNESS_CALENDAR_DIR')=='/calendar'
assert any(m['Destination']=='/calendar' and m['RW'] for m in item['Mounts'])
print('新版网页与三项新增资源就绪；当前自设密码验证通过，匿名访问仍需认证。')
