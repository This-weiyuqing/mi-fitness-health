param(
    [Parameter(Mandatory=$true)][string]$Package,
    [string]$SshHost = 'fn',
    [switch]$Deploy
)
$ErrorActionPreference = 'Stop'
$release = (Resolve-Path -LiteralPath $Package).Path
$manifest = Join-Path $release 'manifest.sha256'
foreach ($line in Get-Content -LiteralPath $manifest -Encoding utf8) {
    if ($line -notmatch '^([a-f0-9]{64})  ([A-Za-z0-9._-]+)$') { throw '发布清单格式不符' }
    if ((Get-FileHash -LiteralPath (Join-Path $release $Matches[2]) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Matches[1]) { throw '本地发布文件校验失败' }
}
if (-not $Deploy) {
    Write-Output '本地发布包校验通过。仅更新backend/web，worker、端口、密码和数据挂载沿用。'
    Write-Output '得到明确部署确认后，在交互PowerShell使用同一命令加 -Deploy；sudo密码只在终端输入。'
    return
}
if ($SshHost -notmatch '^[A-Za-z0-9._-]+$') { throw 'SSH别名无效' }
$remote = '/tmp/mi-fitness-summary8-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
& ssh $SshHost "umask 077; mkdir '$remote'"
if ($LASTEXITCODE -ne 0) { throw '创建远程发布目录失败' }
foreach ($line in Get-Content -LiteralPath $manifest -Encoding utf8) {
    $name = ($line -split '  ',2)[1]
    & scp (Join-Path $release $name) "${SshHost}:$remote/$name"
    if ($LASTEXITCODE -ne 0) { throw '发布文件传输失败' }
}
& scp $manifest "${SshHost}:$remote/manifest.sha256"
if ($LASTEXITCODE -ne 0) { throw '发布清单传输失败' }
& ssh -t $SshHost "sudo sh '$remote/update-health.sh'"
if ($LASTEXITCODE -ne 0) { throw '部署未通过，请保留终端输出和回退备份。' }
