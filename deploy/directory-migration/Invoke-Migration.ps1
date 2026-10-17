param([switch]$Run)
$ErrorActionPreference = 'Stop'
$migration = Join-Path $PSScriptRoot 'migrate.py'
$check = Join-Path $PSScriptRoot '../query-summary/check-ready.py'
if (-not $Run) { throw '仅在用户已批准目录迁移后使用 -Run。' }
$remote = '/tmp/mi-fitness-directory-migration-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
& ssh fn "umask 077; mkdir '$remote'"
if ($LASTEXITCODE -ne 0) { throw '创建传输目录失败' }
foreach ($file in @($migration, $check)) {
    & scp $file "fn:$remote/"
    if ($LASTEXITCODE -ne 0) { throw '迁移工具上传失败' }
    $name = Split-Path $file -Leaf
    $expected = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    $actual = (& ssh fn "sha256sum '$remote/$name'") -split '\s+'
    if ($LASTEXITCODE -ne 0 -or $actual[0] -ne $expected) { throw '传输校验未通过' }
}
Write-Host '仅整理健康项目目录并重建三个健康容器；不变更镜像、密码或端口。'
Write-Host '如出现 sudo 提示，请仅在此窗口输入 NAS 密码。'
& ssh -t fn "sudo python3 '$remote/migrate.py'"
$result = $LASTEXITCODE
$receipt = Join-Path $PSScriptRoot '../../artifacts/directory-migration'
New-Item -ItemType Directory -Path $receipt -Force | Out-Null
@{ exit_code=$result; completed_at=(Get-Date -Format o); remote_tools=$remote } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $receipt 'terminal-result.local.json') -Encoding utf8NoBOM
if ($result -ne 0) { throw '迁移未完成，请保留终端输出。' }
Write-Host '项目目录迁移完成，网站地址和密码保持不变。'
