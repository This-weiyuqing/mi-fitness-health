"""主仓库产品代码同步到旧工作区；冲突时停止，不删除文件。"""
import hashlib
import json
import shutil
from pathlib import Path

root=Path(__file__).resolve().parents[1]
config=root/'.workspace-sync.local.json'
if not config.exists():
    raise SystemExit('此电脑尚未配置兼容同步；请保留源代码并核对目标目录')
settings=json.loads(config.read_text(encoding='utf-8'))
target=Path(settings['target']).resolve()
expected=Path('C:/Users/35861/Documents/Codex/2026-10-16/nas-mi-fitness-health-connect-aurboda/work/mi-fitness-mcp-cn').resolve()
if target!=expected or not (target/'.git').is_dir():
    raise SystemExit('同步目标不符或不是预期Git工作区，停止')

files=[]
for directory in ['src','tests']:
    files.extend(p for p in (root/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'})
for name in ['pyproject.toml','README.md','CHANGELOG.md','SECURITY.md']:
    if (root/name).is_file():files.append(root/name)
updates=[]
for source in files:
    name=source.relative_to(root).as_posix();destination=target/name
    if source.is_symlink() or destination.is_symlink() or not destination.resolve().is_relative_to(target):
        raise SystemExit('拒绝同步符号链接或目标目录之外的文件：'+name)
    new=hashlib.sha256(source.read_bytes()).hexdigest()
    actual=hashlib.sha256(destination.read_bytes()).hexdigest() if destination.exists() else None
    previous=settings['hashes'].get(name)
    if actual!=new and actual!=previous:
        raise SystemExit('旧工作区存在另行修改，未写入任何文件：'+name)
    if new!=actual:updates.append((source,destination,new,name))
for source,destination,new,name in updates:
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,destination)
    if hashlib.sha256(destination.read_bytes()).hexdigest()!=new:raise RuntimeError('写后校验失败：'+name)
    settings['hashes'][name]=new
config.write_text(json.dumps(settings,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'updated_files':len(updates),'direction':'主仓库到旧工作区','deletions':0},ensure_ascii=False))
