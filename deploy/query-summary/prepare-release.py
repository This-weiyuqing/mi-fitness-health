"""为现有summary8离线tar生成LF发布元数据；不构建镜像或连接NAS。"""
import hashlib
import json
import re
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / 'artifacts/query-summary/release'
TAG = 'local/mi-fitness-nas:20261017-summary8'
BASE_IMAGE_ID = 'sha256:f4cbe187a98e3d3223e28e79b6edd115446ba62a78931f54f3bb0a6991a9395d'
# 部署前只读快照；实际更新脚本仍会再次比对，漂移则停止。
EXPECTED_CURRENT = '3cdbdc882b169f5785d6d1c3c46ceb159e209c567d6e28ceb31b15d4280fcdd8'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_lf(name, value):
    assert '\r' not in value and not value.startswith('\ufeff')
    (RELEASE / name).write_bytes((value.rstrip('\n') + '\n').encode('utf-8'))


def main():
    tar = RELEASE / 'health-summary8.tar'
    # 仅读取索引/配置元数据，不展开镜像层，也不修改tar。
    with tarfile.open(tar) as archive:
        manifest = json.load(archive.extractfile('manifest.json'))
        assert len(manifest) == 1 and manifest[0]['RepoTags'] == [TAG]
        index = json.load(archive.extractfile('index.json'))
        assert len(index['manifests']) == 1
        image_id = index['manifests'][0]['digest']
        assert re.fullmatch(r'sha256:[0-9a-f]{64}', image_id)
        index_blob = archive.extractfile('blobs/sha256/' + image_id.split(':')[1]).read()
        assert hashlib.sha256(index_blob).hexdigest() == image_id.split(':')[1]
        config = archive.extractfile(manifest[0]['Config']).read()
        config_id = 'sha256:' + hashlib.sha256(config).hexdigest()
        assert manifest[0]['Config'] == 'blobs/sha256/' + config_id.split(':')[1]
    for name in ['compose.override.yml', 'update-health.sh', 'check-ready.py', 'Update-Nas.ps1']:
        content = (Path(__file__).resolve().parent / name).read_bytes()
        assert b'\r' not in content and not content.startswith(b'\xef\xbb\xbf'), name
        (RELEASE / name).write_bytes(content)
    for name, value in [('image-id.txt', image_id), ('image-config-id.txt', config_id),
            ('base-image-id.txt', BASE_IMAGE_ID), ('expected-current.sha256', EXPECTED_CURRENT)]:
        write_lf(name, value)
    files = sorted(path for path in RELEASE.iterdir() if path.is_file() and path.name != 'manifest.sha256')
    assert len(files) == 9, '发布目录包含非预期文件，停止生成清单'
    write_lf('manifest.sha256', ''.join(sha256(path) + '  ' + path.name + '\n' for path in files))
    print(json.dumps(dict(image_id=image_id, config_id=config_id, tar_sha256=sha256(tar),
        manifest_sha256=sha256(RELEASE / 'manifest.sha256')), ensure_ascii=False))


if __name__ == '__main__':
    main()
