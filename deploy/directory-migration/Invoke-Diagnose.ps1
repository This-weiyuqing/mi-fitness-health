$ErrorActionPreference = 'Stop'
$remote = '/tmp/mi-fitness-migration-diagnose-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.py'
& scp (Join-Path $PSScriptRoot 'diagnose.py') "fn:$remote"
if ($LASTEXITCODE -ne 0) { throw '诊断脚本上传失败' }
Write-Host '此次仅收集容器状态、迁移时事件和候选配置检查，不迁移、不重启。'
$output = & ssh -t fn "sudo python3 '$remote'"
$code = $LASTEXITCODE
$output | ForEach-Object { Write-Host $_ }
$directory = Join-Path $PSScriptRoot '../../artifacts/directory-migration'
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$output | Set-Content -LiteralPath (Join-Path $directory 'diagnose.local.txt') -Encoding utf8NoBOM
if ($code -ne 0) { throw '诊断未完成，请保留输出。' }
Write-Host '诊断结果已保存到本机，可以回到聊天回复“已完成”。'
