"""本机合成文件演练；不连接 NAS、不读取真实数据。"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('directory_migration', HERE / 'migrate.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SimulatedMigration(module.Migration):
    def __init__(self, root):
        super().__init__(root)
        self.items = []
        self.other = []
        self.fail_verification = False
        self.events = []
        for name, image in zip(module.NAMES, ['summary8', 'summary8', 'audit3']):
            kind = name.split('-')[-2]
            mounts = ([('state', '/state', True)] if kind != 'web' else [('calendar', '/calendar', True)])
            if kind == 'backend':
                mounts.append(('secrets/keyring_master', '/run/secrets/keyring_master', False))
            self.items.append({'Name': '/' + name, 'Image': image,
                'State': {'Running': True, 'Health': {'Status': 'healthy'}},
                'Config': {'Image': 'local/mi-fitness-nas:20261017-' + image,
                           'Env': ['EXAMPLE=synthetic'], 'Labels': {
                               'com.docker.compose.project.working_dir': str(root),
                               'com.docker.compose.project.config_files': ','.join(str(root / n) for n in module.EXPECTED)}},
                'HostConfig': {'PortBindings': {}, 'ReadonlyRootfs': True, 'RestartPolicy': {'Name': 'unless-stopped'}},
                'Mounts': [{'Source': str(root / p), 'Destination': d, 'RW': rw, 'Type': 'bind'} for p, d, rw in mounts]})

    def run(self, *args):
        if args[:3] == ('docker', 'ps', '-aq'):
            return b'one\n'
        if args[:2] == ('docker', 'inspect'):
            return json.dumps(self.items + self.other).encode()
        if args[0] == 'python3':
            return b''
        raise AssertionError('unexpected command')

    def inspect(self):
        return copy.deepcopy(self.items)

    def compose(self, *args):
        self.events.append(args[0])
        if args[0] == 'stop':
            for item in self.items:
                item['State']['Running'] = False
        if args[0] == 'up':
            migrated = './shared/state:' in (self.root / 'compose.yml').read_text(encoding='utf-8')
            for item in self.items:
                item['State']['Running'] = True
                for mount in item['Mounts']:
                    mount['Source'] = str(self.root / ({'/state': 'shared/state' if migrated else 'state',
                        '/calendar': 'web/calendar' if migrated else 'calendar',
                        '/run/secrets/keyring_master': 'backend/secrets/keyring_master' if migrated else 'secrets/keyring_master'}[mount['Destination']]))
        return b''

    def verify(self):
        if self.fail_verification:
            raise RuntimeError('synthetic readiness failure')
        super().verify()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'mi-fitness-health'
        self.root.mkdir()
        for name in module.EXPECTED:
            data = (HERE.parent / name).read_bytes().replace(b'\r\n', b'\n')
            data = data.replace(b'./shared/state:', b'./state:').replace(b'./shared/state/data:', b'./state/data:')
            data = data.replace(b'./backend/secrets/', b'./secrets/').replace(b'./web/calendar:', b'./calendar:')
            (self.root / name).write_bytes(data)
        for folder in ['state', 'secrets', 'calendar']:
            (self.root / folder).mkdir()
            (self.root / folder / 'synthetic.txt').write_text('synthetic-only', encoding='utf-8')
        for name in ['.mi-fitness-health-stage-20261016-212720', '.mi-fitness-health-password-change',
                     *['.mi-fitness-health-ui%d-update' % n for n in range(4, 8)]]:
            path = self.root.parent / name
            path.mkdir()
            (path / 'example.txt').write_text('archive-example', encoding='utf-8')
        (self.root / 'compose.override.pre-synthetic.yml').write_text('old-config', encoding='utf-8')
        self.migration = SimulatedMigration(self.root)

    def test_success_keeps_contents_permissions_and_shared_mounts(self):
        original = module.inventory(self.root / 'state')
        self.migration.execute()
        self.assertEqual(module.inventory(self.root / 'shared/state'), original)
        self.assertFalse((self.root / 'state').exists())
        self.assertTrue((self.root / 'archive/ui7/example.txt').exists())
        self.assertTrue((self.root / 'archive/rollback-configs/compose.override.pre-synthetic.yml').exists())
        self.assertEqual(json.loads((self.migration.journal / 'result.json').read_text())['status'], 'complete')
        before = (self.root / 'compose.yml').read_text(encoding='utf-8')
        self.assertIn('./shared/state/data:/health:ro', before)

    def test_failed_readiness_restores_all_original_paths_and_configs(self):
        self.migration.fail_verification = True
        before = (self.root / 'compose.yml').read_bytes()
        with self.assertRaises(RuntimeError):
            self.migration.execute()
        self.assertEqual((self.root / 'compose.yml').read_bytes(), before)
        self.assertTrue((self.root / 'state/synthetic.txt').exists())
        self.assertFalse((self.root / 'shared/state').exists())
        self.assertTrue((self.root.parent / '.mi-fitness-health-ui7-update/example.txt').exists())
        self.assertTrue(all(item['State']['Running'] for item in self.migration.items))

    def test_other_container_reference_stops_before_mutation(self):
        self.migration.other = [{'Name': '/other-production', 'Mounts': [
            {'Type': 'bind', 'Source': str(self.root / 'state/data')}]}]
        with self.assertRaises(RuntimeError):
            self.migration.execute()
        self.assertNotIn('stop', self.migration.events)
        self.assertTrue((self.root / 'state').exists())

    def test_changed_config_stops_before_mutation(self):
        with (self.root / 'compose.yml').open('a', encoding='utf-8') as stream:
            stream.write('# changed\n')
        with self.assertRaises(RuntimeError):
            self.migration.execute()
        self.assertNotIn('stop', self.migration.events)

    def test_web_probe_waits_for_http_after_container_reports_running(self):
        self.migration.preflight()
        # 挂载保持未迁移时，同样模拟预期路径转换以独立验证网页启动等待。
        self.migration.before = []
        attempts = []
        original_run = self.migration.run
        def delayed_probe(*args):
            if args[0] == 'python3':
                attempts.append(1)
                if len(attempts) < 3:
                    raise subprocess.CalledProcessError(1, args, stderr=b'ConnectionRefusedError')
                return b''
            return original_run(*args)
        self.migration.run = delayed_probe
        with patch.object(module.time, 'sleep'):
            self.migration.verify()
        self.assertEqual(len(attempts), 3)

    def test_retry_preserves_previous_rollback_record(self):
        self.migration.fail_verification = True
        with self.assertRaises(RuntimeError):
            self.migration.execute()
        previous = self.migration.journal
        retry = SimulatedMigration(self.root)
        retry.execute()
        self.assertNotEqual(retry.journal, previous)
        self.assertEqual(json.loads((previous/'result.json').read_text())['status'], 'rolled_back')
        self.assertEqual(json.loads((retry.journal/'result.json').read_text())['status'], 'complete')

    def test_environment_order_does_not_count_as_value_change(self):
        for item in self.migration.items:
            item['Config']['Env'] = ['EXAMPLE=synthetic', 'SECOND=unchanged']
        original_compose = self.migration.compose
        def recreate_with_reordered_environment(*args):
            result = original_compose(*args)
            if args[0] == 'up':
                for item in self.migration.items:
                    item['Config']['Env'].reverse()
            return result
        self.migration.compose = recreate_with_reordered_environment
        self.migration.execute()
        self.assertEqual(json.loads((self.migration.journal/'result.json').read_text())['status'], 'complete')

    def test_real_environment_value_change_still_rolls_back(self):
        original_compose = self.migration.compose
        def recreate_with_changed_environment(*args):
            result = original_compose(*args)
            if args[0] == 'up':
                self.migration.items[0]['Config']['Env'] = ['EXAMPLE=changed']
            return result
        self.migration.compose = recreate_with_changed_environment
        with self.assertRaisesRegex(RuntimeError, '环境变量'):
            self.migration.execute()
        self.assertTrue((self.root/'state/synthetic.txt').exists())


if __name__ == '__main__':
    unittest.main()
