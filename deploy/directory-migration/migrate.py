"""已授权的 NAS 目录整理；只移动本项目文件，失败时恢复原路径。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

ROOT = Path('/vol2/1000/Soft/mi-fitness-health')
SERVICES = ['backend', 'web', 'worker']
NAMES = ['mi-fitness-health-' + name + '-1' for name in SERVICES]
EXPECTED = {
    'compose.yml': '111fcd84b1740e377db958c459c922dda4191317e121267bdf3146a75e864ac0',
    'compose.override.yml': '054b4541a3a2e50d46473061822c637c4694fa210414d05b2b6aa43deabea0d3',
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(path):
    """仅在内存中核对内容和权限，不输出凭据或健康文件名。"""
    result = {}
    for item in [path, *sorted(path.rglob('*'))] if path.is_dir() else [path]:
        info = item.lstat()
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise RuntimeError('待迁移目录含链接或特殊文件，停止')
        result[str(item.relative_to(path))] = (
            stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode),
            info.st_uid, info.st_gid, digest(item) if item.is_file() else None,
        )
    return result


def environment_values(item):
    result = {}
    for entry in item['Config'].get('Env', []):
        key, separator, value = entry.partition('=')
        if not separator or key in result:
            raise RuntimeError('环境变量含缺失值或重复名称，停止核对')
        result[key] = value
    return result


class Migration:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.moves = []
        self.snapshots = {}
        self.original = {}
        self.stopped = False
        self.journal = self.root / 'archive' / 'directory-migration'
        self.stage = 'preflight'

    def run(self, *args):
        # Docker inspect/config 的完整结果不得输出到终端（可能包含环境凭据）。
        try:
            return subprocess.check_output(list(args), stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as error:
            if self.journal.is_dir():
                detail = (error.stderr or b'').decode('utf-8', errors='replace')[-16000:]
                for item in getattr(self, 'before', []):
                    for entry in item['Config'].get('Env', []):
                        key, _, value = entry.partition('=')
                        if len(value) >= 4 and any(word in key.upper() for word in ['PASSWORD', 'TOKEN', 'SECRET', 'KEY']):
                            detail = detail.replace(value, '[REDACTED]')
                path = self.journal / 'errors.log'
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(descriptor, 'a', encoding='utf-8') as stream:
                    stream.write(json.dumps({'stage': self.stage, 'exit_code': error.returncode,
                                             'stderr': detail}, ensure_ascii=False)+'\n')
            raise

    def compose(self, *args):
        return self.run('docker', 'compose', '--project-directory', str(self.root),
                        '-p', 'mi-fitness-health', '-f', str(self.root / 'compose.yml'),
                        '-f', str(self.root / 'compose.override.yml'), *args)

    def inspect(self):
        return json.loads(self.run('docker', 'inspect', *NAMES))

    def mapping(self):
        pairs = [('state', 'shared/state'), ('secrets', 'backend/secrets'),
                 ('calendar', 'web/calendar')]
        for name, destination in [
            ('.mi-fitness-health-stage-20261016-212720', 'initial-install'),
            ('.mi-fitness-health-password-change', 'password-change'),
            *[('.mi-fitness-health-ui%d-update' % n, 'ui%d' % n) for n in range(4, 8)],
        ]:
            pairs.append((self.root.parent / name, 'archive/' + destination))
        for item in sorted(self.root.iterdir()):
            if item.name.startswith(('compose.override.pre-', '.env.pre-')):
                pairs.append((item, 'archive/rollback-configs/' + item.name))
        return [(self.root / source, self.root / target) for source, target in pairs]

    def preflight(self):
        if self.root.is_symlink() or self.root.resolve() != self.root:
            raise RuntimeError('项目路径含符号链接，停止')
        for name, expected in EXPECTED.items():
            path = self.root / name
            if path.is_symlink() or digest(path) != expected:
                raise RuntimeError('当前配置已变化，需重新核对')
            self.original[name] = path.read_bytes()
        self.pairs = self.mapping()
        if self.journal.exists():
            result = self.journal / 'result.json'
            if self.journal.is_symlink() or result.is_symlink() or not result.is_file() or json.loads(result.read_text(encoding='utf-8')).get('status') != 'rolled_back':
                raise RuntimeError('已有未回退的迁移记录，拒绝重复运行')
            self.journal = self.root / 'archive' / ('directory-migration-retry-' + str(time.time_ns()))
        for name in ['shared', 'backend', 'web', 'worker']:
            path = self.root / name
            if path.exists() and (path.is_symlink() or not path.is_dir() or any(path.iterdir())):
                raise RuntimeError('容器专属目标目录不为空，停止')
        for source, target in self.pairs:
            if not source.exists() or source.is_symlink() or target.exists():
                raise RuntimeError('迁移源缺失或目标已存在，停止')
            if source.resolve().parent not in (self.root, self.root.parent):
                raise RuntimeError('迁移源超出授权目录')
            if not target.resolve().is_relative_to(self.root):
                raise RuntimeError('迁移目标超出项目目录')
            if source.stat().st_dev != self.root.stat().st_dev:
                raise RuntimeError('跨文件系统移动需另行处理，停止')
        self.before = self.inspect()
        expected_images = ['local/mi-fitness-nas:20261017-summary8',
                           'local/mi-fitness-nas:20261017-summary8',
                           'local/mi-fitness-nas:20261017-audit3']
        for item, name, image in zip(self.before, NAMES, expected_images):
            if item['Name'] != '/' + name or item['Config']['Image'] != image:
                raise RuntimeError('运行容器或镜像与已确认版本不符')
            if not item['State']['Running']:
                raise RuntimeError('原容器未运行，需先核对')
            labels = item['Config']['Labels']
            if Path(labels['com.docker.compose.project.working_dir']) != self.root:
                raise RuntimeError('容器项目目录不符')
            files = labels['com.docker.compose.project.config_files'].split(',')
            if set(files) != {str(self.root / n) for n in EXPECTED}:
                raise RuntimeError('存在额外 Compose 配置，停止')
        # 其他项目若引用待移动路径，不能继续。
        ids = self.run('docker', 'ps', '-aq').decode().split()
        containers = json.loads(self.run('docker', 'inspect', *ids)) if ids else []
        for item in containers:
            if item['Name'] in ['/' + n for n in NAMES]:
                continue
            for mount in item.get('Mounts', []):
                if mount.get('Type') != 'bind':
                    continue
                path = Path(mount.get('Source', '/'))
                for source, _ in self.pairs:
                    if path == source or path.is_relative_to(source) or source.is_relative_to(path):
                        raise RuntimeError('其他容器引用待迁移路径，停止')
        self.compose('config', '--quiet')
        print('配置、容器引用和迁移路径预检通过。', flush=True)

    def write_configs(self):
        for name, content in self.original.items():
            text = content.decode('utf-8')
            if name == 'compose.yml':
                if text.count('./state:') != 2 or text.count('./state/data:') != 1 or text.count('./secrets/') != 1:
                    raise RuntimeError('基础配置挂载数量不符')
                text = text.replace('./state:', './shared/state:').replace('./state/data:', './shared/state/data:')
                text = text.replace('./secrets/', './backend/secrets/')
            else:
                if text.count('./calendar:') != 1:
                    raise RuntimeError('日历挂载数量不符')
                text = text.replace('./calendar:', './web/calendar:')
            (self.root / name).write_bytes(text.encode('utf-8'))

    def ready(self):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            items = self.inspect()
            if all(item['State'].get('Running') and
                   item['State'].get('Health', {}).get('Status', 'healthy') == 'healthy'
                   for item in items):
                return items
            time.sleep(3)
        raise RuntimeError('容器未按时就绪')

    def verify(self):
        after = self.ready()
        replacements = {str(self.root / 'state'): str(self.root / 'shared/state'),
                        str(self.root / 'secrets/keyring_master'): str(self.root / 'backend/secrets/keyring_master'),
                        str(self.root / 'calendar'): str(self.root / 'web/calendar')}
        def mounts(item, translated=False):
            return sorted((replacements.get(m['Source'], m['Source']) if translated else m['Source'],
                           m['Destination'], m['RW']) for m in item['Mounts'])
        comparisons = []
        for old, new in zip(self.before, after):
            old_env, new_env = environment_values(old), environment_values(new)
            changed = sorted(key for key in old_env.keys() | new_env.keys()
                             if key not in old_env or key not in new_env or old_env[key] != new_env[key])
            comparisons.append({'container': old['Name'], 'same_image': old['Image'] == new['Image'],
                                'same_environment_values': not changed, 'changed_environment_names': changed,
                                'environment_order_changed': old['Config'].get('Env') != new['Config'].get('Env')})
        if self.journal.is_dir():
            (self.journal/'verification.json').write_text(json.dumps(comparisons, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        for old, new, comparison in zip(self.before, after, comparisons):
            if not comparison['same_image']:
                raise RuntimeError('镜像标识发生变化：' + old['Name'])
            if not comparison['same_environment_values']:
                raise RuntimeError('环境变量值发生变化：' + old['Name'] + ' ' + ','.join(comparison['changed_environment_names']))
            if comparison['environment_order_changed']:
                print(old['Name'] + ' 环境变量值逐项一致，仅排列顺序变化。', flush=True)
            for key in ['PortBindings', 'ReadonlyRootfs', 'RestartPolicy']:
                if old['HostConfig'][key] != new['HostConfig'][key]:
                    raise RuntimeError('端口或运行策略发生额外变化')
            if mounts(old, True) != mounts(new):
                raise RuntimeError('挂载与迁移计划不符')
        # 复用现有静态资源、鉴权和代理检查，不查询真实健康数据。
        self.stage = 'web-readiness'
        deadline = time.monotonic() + 90
        while True:
            try:
                self.run('python3', str(Path(__file__).with_name('check-ready.py')))
                break
            except subprocess.CalledProcessError:
                if time.monotonic() >= deadline:
                    raise
                print('网页仍在启动，等待实际 HTTP 鉴权和代理就绪。', flush=True)
                time.sleep(3)
        print('三个容器已就绪；镜像、密码环境、端口及迁移挂载核对通过。', flush=True)

    def execute(self):
        self.preflight()
        self.journal.mkdir(parents=True, mode=0o700)
        for name, content in self.original.items():
            path = self.journal / name
            path.write_bytes(content)
            shutil.copystat(self.root / name, path)
        # 两端目录仅在项目内创建，不改原有运行文件权限。
        for name in ['shared', 'backend', 'web', 'worker']:
            (self.root / name).mkdir(mode=0o700, exist_ok=True)
            shutil.copystat(self.root, self.root / name)
            if hasattr(os, 'chown'):
                info = self.root.stat()
                os.chown(self.root / name, info.st_uid, info.st_gid)
        try:
            self.stopped = True
            self.stage = 'stop-original-services'
            self.compose('stop', '-t', '60', 'worker', 'web', 'backend')
            if any(item['State']['Running'] for item in self.inspect()):
                raise RuntimeError('容器未完全停止')
            # 停止写入后再计算哈希；文件、权限、属主逐项核对。
            self.stage = 'move-and-verify-files'
            for source, target in self.pairs:
                self.snapshots[str(source)] = inventory(source)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                source.rename(target)
                self.moves.append((source, target))
                if inventory(target) != self.snapshots[str(source)]:
                    raise RuntimeError('移动后文件或权限校验失败')
            print('全部文件移动完成，内容校验及权限核对通过。', flush=True)
            self.write_configs()
            self.stage = 'validate-migrated-config'
            self.compose('config', '--quiet')
            self.stage = 'recreate-services'
            self.compose('up', '-d', '--no-build', '--pull', 'never', *SERVICES)
            self.stage = 'verify-services'
            self.verify()
            receipt = {'status': 'complete', 'file_trees_verified': len(self.moves),
                       'services': SERVICES, 'paths': [[str(a), str(b)] for a, b in self.moves]}
            (self.journal / 'result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            print('项目目录迁移完成。', flush=True)
        except BaseException:
            failed_stage = self.stage
            print('迁移未通过（阶段：' + failed_stage + '），正在恢复原路径和配置。', flush=True)
            self.stage = 'rollback'
            if self.stopped:
                self.compose('stop', '-t', '60', 'worker', 'web', 'backend')
            for source, target in reversed(self.moves):
                if source.exists():
                    raise RuntimeError('回退源路径被占用，已停止，需人工核对')
                target.rename(source)
            for name, content in self.original.items():
                (self.root / name).write_bytes(content)
            self.compose('up', '-d', '--no-build', '--pull', 'never', *SERVICES)
            self.ready()
            (self.journal / 'result.json').write_text(json.dumps({'status': 'rolled_back', 'failed_stage': failed_stage})+'\n', encoding='utf-8')
            print('已恢复原目录、配置并启动三个健康容器。', flush=True)
            raise


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('需要通过 sudo 在 NAS 本机执行')
    try:
        Migration().execute()
    except BaseException as error:
        # 不打印可能带容器环境变量的子进程输出。
        detail = str(error) if type(error) is RuntimeError else type(error).__name__
        print('迁移中止：' + detail, flush=True)
        raise SystemExit(1)
