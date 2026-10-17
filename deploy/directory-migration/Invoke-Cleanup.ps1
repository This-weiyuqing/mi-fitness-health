$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'cleanup_history.py'
$remote = '/tmp/mi-fitness-cleanup-history-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.py'
& scp $script "fn:$remote"
if ($LASTEXITCODE -ne 0) { throw '清理工具上传失败' }
$expected = (Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant()
$actual = (& ssh fn "sha256sum '$remote'") -split '\s+'
if ($LASTEXITCODE -ne 0 -or $actual[0] -ne $expected) { throw '传输校验失败' }
Write-Host '仅删除已列出的过时归档。保留运行数据、最近成功迁移记录和当前配置备份，不重启容器。'
& ssh -t fn "sudo python3 '$remote'"
$code = $LASTEXITCODE
$directory = Join-Path $PSScriptRoot '../../artifacts/directory-migration'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
@{exit_code=$code;completed_at=(Get-Date -Format o)} | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $directory 'cleanup-terminal-result.local.json') -Encoding utf8NoBOM
if ($code -ne 0) { throw '清理未完成，请保留输出。' }
Write-Host '清理完成。'
