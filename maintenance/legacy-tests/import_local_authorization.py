"""同一台本机内把已授权凭据从 Windows 密钥环传入加密容器；从不输出凭据。"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'work/mi-fitness-mcp-cn/src'))
from mi_fitness_mcp.security import load_api_key_secret

with sqlite3.connect(root / 'work/local-validation/state/mi_fitness.db') as conn:
    rows = conn.execute('SELECT key,user_id,region,pass_token FROM api_keys WHERE revoked=0').fetchall()
if len(rows) != 1 or rows[0][3]:
    raise SystemExit('本机授权状态不符合预期，停止')
key, user, region, _ = rows[0]
token = load_api_key_secret(key)
if not token:
    raise SystemExit('无法读取本机已授权凭据，停止')
code = r'''
import sys,json,sqlite3
sys.path.insert(0,'/opt/health')
import runtime
runtime.setup_credentials()
from mi_fitness_mcp.api import _create_key_record
from mi_fitness_mcp.storage import Database
from mi_fitness_mcp.security import load_api_key_secret
data=json.load(sys.stdin)
db=Database('/state/data/mi_fitness.db')
with db._get_connection() as c:
    if c.execute('SELECT count(*) FROM api_keys WHERE revoked=0').fetchone()[0]:
        raise SystemExit('目标不是空授权库，停止')
new_key=_create_key_record(db,data['user_id'],data['pass_token'],data['region'],'local-linux-verification')
with db._get_connection() as c:
    clear=c.execute("SELECT count(*) FROM api_keys WHERE pass_token!=''").fetchone()[0]
encrypted=load_api_key_secret(new_key)==data['pass_token']
not_plain=data['pass_token'] not in open('/state/credentials/encrypted-keyring.cfg',encoding='utf-8').read()
print(json.dumps({'active_authorizations':1,'plaintext_account_token_rows':clear,'encrypted_keyring_round_trip':encrypted,'token_absent_from_keyring_plaintext':not_plain}))
if clear or not encrypted or not not_plain: raise SystemExit(1)
'''
docker = r'C:/Users/35861/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe'
result = subprocess.run([docker,'--context','desktop-linux','exec','-i','mi-fitness-production-local-backend-1','python','-c',code],input=json.dumps({'user_id':user,'pass_token':token,'region':region}),capture_output=True,text=True,encoding='utf-8',timeout=60)
if result.returncode:
    # 错误输出可能包含第三方异常上下文，因此不直接转发。
    raise SystemExit('容器授权导入未通过，错误内容留在进程内，未输出凭据')
report = json.loads(result.stdout)
print(json.dumps(report))
(root / 'work/deployment-tests/linux-credential-proof.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
