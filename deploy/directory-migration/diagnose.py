"""只读诊断迁移失败；不停止容器，不读取健康数据或输出环境凭据。"""
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path('/vol2/1000/Soft/mi-fitness-health')
NAMES = ['mi-fitness-health-' + x + '-1' for x in ['backend', 'web', 'worker']]


def run(*args):
    return subprocess.check_output(args, stderr=subprocess.PIPE, timeout=90)


items = json.loads(run('docker', 'inspect', *NAMES))
for item in items:
    print(json.dumps({'container': item['Name'], 'status': item['State']['Status'],
                      'health': item['State'].get('Health', {}).get('Status'),
                      'mounts': [{'source': m.get('Source'), 'destination': m['Destination']}
                                 for m in item['Mounts'] if m.get('Type') == 'bind']}, ensure_ascii=False))
events = run('docker', 'events', '--since', '2026-10-17T16:40:00+08:00',
             '--until', '2026-10-17T16:45:00+08:00', '--filter', 'type=container',
             '--filter', 'label=com.docker.compose.project=mi-fitness-health', '--format', '{{json .}}')
for line in events.splitlines():
    event = json.loads(line)
    action = event.get('Action', '')
    if action in {'create', 'start', 'stop', 'die', 'destroy', 'kill'} or action.startswith('health_status'):
        attrs = event.get('Actor', {}).get('Attributes', {})
        print(json.dumps({'event': action, 'time': event.get('time'),
                          'name': attrs.get('name'), 'exit_code': attrs.get('exitCode')}, ensure_ascii=False))
with tempfile.TemporaryDirectory(prefix='health-migration-readonly-') as directory:
    base = (ROOT/'compose.yml').read_text(encoding='utf-8')
    over = (ROOT/'compose.override.yml').read_text(encoding='utf-8')
    base = base.replace('./state:', './shared/state:').replace('./state/data:', './shared/state/data:').replace('./secrets/', './backend/secrets/')
    over = over.replace('./calendar:', './web/calendar:')
    paths = []
    for name, text in [('compose.yml', base), ('compose.override.yml', over)]:
        path = Path(directory)/name
        path.write_text(text, encoding='utf-8')
        paths.extend(['-f', str(path)])
    try:
        run('docker', 'compose', '--project-directory', str(ROOT), '--env-file', str(ROOT/'.env'),
            '-p', 'mi-fitness-health', *paths, 'config', '--quiet')
        print('候选挂载配置静态解析通过（未应用）。')
    except subprocess.CalledProcessError:
        print('候选挂载配置静态解析失败。')
print('只读诊断完成。')
