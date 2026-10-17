"""显式运行的本机真实容器演练，全部使用合成配置，不连接 NAS。"""
import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
DOCKER = 'C:/Users/35861/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe'
PROJECT = 'health-directory-local-rebuild'


def main():
    if sys.argv[1:] != ['--run']:
        raise SystemExit('仅在本机运行时显式指定 --run')
    with tempfile.TemporaryDirectory(prefix='health-directory-local-') as directory:
        root = Path(directory)
        for name in ['state', 'secrets', 'calendar']:
            (root/name).mkdir()
        (root/'secrets/keyring_master').write_text('synthetic-local-master-value-1234567890123456789', encoding='utf-8')
        (root/'.env').write_text('MI_FITNESS_ADMIN_KEY=synthetic-local-admin\nMI_FITNESS_WEB_PASSWORD=synthetic-local-password\n', encoding='utf-8')
        base = (HERE.parent/'compose.yml').read_text(encoding='utf-8').replace('name: mi-fitness-health', 'name: '+PROJECT)
        over = (HERE.parent/'compose.override.yml').read_text(encoding='utf-8')
        base = base.replace('./shared/state:', './state:').replace('./shared/state/data:', './state/data:').replace('./backend/secrets/', './secrets/')
        over = over.replace('./web/calendar:', './calendar:')
        over = over.replace("      - '127.0.0.1:18322:8322'\n      - '192.168.31.201:18322:8322'", "      - '127.0.0.1:0:8322'")
        over += '\nnetworks:\n  default:\n    internal: true\n'
        def save():
            (root/'compose.yml').write_text(base, encoding='utf-8')
            (root/'compose.override.yml').write_text(over, encoding='utf-8')
        save()
        command = [DOCKER, '--context', 'desktop-linux', 'compose', '--project-directory', str(root),
                   '-p', PROJECT, '-f', str(root/'compose.yml'), '-f', str(root/'compose.override.yml')]
        def compose(*args):
            return subprocess.check_output([*command, *args], stderr=subprocess.STDOUT)
        def inspect():
            ids = compose('ps', '-aq').decode().split()
            return json.loads(subprocess.check_output([DOCKER, '--context', 'desktop-linux', 'inspect', *ids]))
        def ready():
            deadline = time.monotonic()+90
            while time.monotonic() < deadline:
                items = inspect()
                if len(items)==3 and all(i['State']['Running'] and i['State'].get('Health',{}).get('Status','healthy')=='healthy' for i in items):
                    return
                time.sleep(1)
            raise RuntimeError('本机容器就绪超时')
        module = ast.parse((HERE.parent/'query-summary/check-ready.py').read_text(encoding='utf-8'))
        probe = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id=='probe' for t in n.targets))
        try:
            compose('up','-d','--no-build','--pull','never','backend','web','worker')
            ready()
            compose('stop','-t','30','worker','web','backend')
            for source, target in [('state','shared/state'),('secrets','backend/secrets'),('calendar','web/calendar')]:
                destination=root/target
                destination.parent.mkdir(exist_ok=True)
                (root/source).rename(destination)
            base=base.replace('./state:', './shared/state:').replace('./state/data:', './shared/state/data:').replace('./secrets/', './backend/secrets/')
            over=over.replace('./calendar:', './web/calendar:')
            save()
            compose('config','--quiet')
            compose('up','-d','--no-build','--pull','never','backend','web','worker')
            ready()
            print('容器已标记就绪，立即执行实际网页探针：', flush=True)
            result=subprocess.run([DOCKER,'--context','desktop-linux','exec','-i',PROJECT+'-web-1','python','-'],
                                  input=probe.encode('utf-8'),capture_output=True)
            print(result.stdout.decode('utf-8',errors='replace'), flush=True)
            print(result.stderr.decode('utf-8',errors='replace'), flush=True)
            if result.returncode:
                print('首次探针失败，五秒后重复同一只读探针以区分启动时序。', flush=True)
                time.sleep(5)
                retry=subprocess.run([DOCKER,'--context','desktop-linux','exec','-i',PROJECT+'-web-1','python','-'],
                                     input=probe.encode('utf-8'),capture_output=True)
                print(retry.stdout.decode('utf-8',errors='replace'),flush=True)
                print(retry.stderr.decode('utf-8',errors='replace'),flush=True)
                if retry.returncode:
                    raise RuntimeError('本机网页探针持续失败')
            print('LOCAL_REAL_REBUILD_AND_WEB_PROBE_OK',flush=True)
        except subprocess.CalledProcessError as error:
            # 此处仅含本机合成配置，无真实凭据。
            print(error.output.decode('utf-8',errors='replace'),flush=True)
            raise
        finally:
            compose('down')


if __name__ == '__main__':
    main()
