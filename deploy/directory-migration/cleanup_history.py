"""只清理明确列出的旧归档，不操作容器、镜像或运行数据。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from datetime import datetime, timezone

ROOT = Path('/vol2/1000/Soft/mi-fitness-health')
KEEP = 'directory-migration-retry-1792227666562967051'
OBSOLETE = ['initial-install', 'password-change', 'rollback-configs', 'ui4', 'ui5', 'ui6', 'ui7',
            'directory-migration', 'directory-migration-retry-1792227359874267909']
EXPECTED = {'compose.yml': 'b5c965c653948e97e02e22774bd15253dbde74d5e25616fa0115f047a36556dd',
            'compose.override.yml': 'd77485b3d3177def55c200478ba9e4645689f8476f46c13a47487be22edcd1c1'}


def candidates(root):
    root = Path(root)
    archive = root/'archive'
    if root.is_symlink() or root.resolve() != root or archive.is_symlink() or archive.resolve().parent != root:
        raise RuntimeError('项目或归档路径异常')
    paths = []
    for name in OBSOLETE:
        path = archive/name
        if path.is_symlink() or path.resolve().parent != archive or not path.is_dir():
            raise RuntimeError('历史目录缺失或路径异常，未清理任何文件')
        for child in path.rglob('*'):
            if not (stat.S_ISREG(child.lstat().st_mode) or stat.S_ISDIR(child.lstat().st_mode)):
                raise RuntimeError('历史目录包含链接或特殊文件，未清理任何文件')
        paths.append(path)
    return paths


def main():
    if os.geteuid() != 0:
        raise RuntimeError('需要通过 sudo 执行')
    paths = candidates(ROOT)
    keep = ROOT/'archive'/KEEP
    if keep.is_symlink() or json.loads((keep/'result.json').read_text(encoding='utf-8'))['status'] != 'complete':
        raise RuntimeError('成功迁移记录异常，停止')
    for name, expected in EXPECTED.items():
        path = ROOT/name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('当前配置已变化，停止')
    ids = subprocess.check_output(['docker', 'ps', '-aq']).decode().split()
    items = json.loads(subprocess.check_output(['docker','inspect',*ids],stderr=subprocess.PIPE)) if ids else []
    for item in items:
        for mount in item.get('Mounts', []):
            if mount.get('Type') != 'bind':
                continue
            source = Path(mount['Source']).resolve()
            if any(source == p or source.is_relative_to(p) or p.is_relative_to(source) for p in paths):
                raise RuntimeError('容器引用历史归档，停止')
    services = {'/mi-fitness-health-'+x+'-1' for x in ['web','backend','worker']}
    current = [i for i in items if i['Name'] in services]
    if len(current)!=3 or not all(i['State']['Running'] for i in current):
        raise RuntimeError('健康容器状态异常，停止')
    snapshots = [(i['Id'], i['State']['StartedAt']) for i in current]
    record = {'at': datetime.now(timezone.utc).isoformat(), 'directories':[], 'bytes_removed':0, 'files_removed':0}
    for path in paths:
        files = [p for p in path.rglob('*') if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        record['directories'].append({'name':path.name,'files':len(files),'bytes':size})
        record['bytes_removed'] += size
        record['files_removed'] += len(files)
    # 保留当前可用配置，而非仅留下引用旧路径的迁移前配置。
    for name in EXPECTED:
        shutil.copy2(ROOT/name, keep/('current-'+name))
    (keep/'cleanup-plan.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for path in paths:
        if path.is_symlink() or path.resolve().parent != ROOT/'archive':
            raise RuntimeError('删除前路径核对失败，停止')
        shutil.rmtree(path)
        print('已清理：'+path.name,flush=True)
    after = json.loads(subprocess.check_output(['docker','inspect',*[i['Id'] for i in current]],stderr=subprocess.PIPE))
    if snapshots != [(i['Id'],i['State']['StartedAt']) for i in after] or not all(i['State']['Running'] for i in after):
        raise RuntimeError('容器状态发生变化，需核对')
    for name, expected in EXPECTED.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
            raise RuntimeError('当前配置发生变化，需核对')
    record['status']='complete'
    record['containers_unchanged']=True
    (keep/'cleanup-result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('历史文件清理完成，释放约 %.1f MiB；三个容器未重启。' % (record['bytes_removed']/1024**2),flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print(str(error) if type(error) is RuntimeError else type(error).__name__,flush=True)
        raise SystemExit(1)
