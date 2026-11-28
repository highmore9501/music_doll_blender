# 把本地一个 UE 端 Python 脚本投给常驻编辑器执行，并取回结果 JSON。
#
# 目标机上要有一个「盯目录 → 执行 → 写 out\<名字>.json」的轮询器（本工程是
# Content/Python/kr_agent_boot.py，编辑器启动时自动挂上）。
#
# 用法：
#   .\ue_job.ps1 -JobPath ..\scripts\verify_performer.py
#   .\ue_job.ps1 -JobPath ..\scripts\copy_control_rig_graphs.py -TimeoutSeconds 900
#
# 传文件用 scp、取结果也用 scp：Windows 远端控制台是 GBK，用 ssh 回显大段中文会乱码/被截断。
param(
    [Parameter(Mandatory = $true)][string]$JobPath,
    [int]$TimeoutSeconds = 300,
    [string]$RemoteHost = '192.168.31.99',
    [string]$RemoteUser = 'administrator',
    [string]$KeyPath = 'C:\Users\BigHippo78\.ssh\kr_render_ed25519',
    [string]$RemoteJobDir = 'D:/kr_import/ue_jobs',
    [string]$RemoteInboxDir = 'D:/kr_import/incoming',
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$target = "$RemoteUser@$RemoteHost"
$jobName = [System.IO.Path]::GetFileNameWithoutExtension($JobPath)
$localResult = Join-Path $PSScriptRoot ("results\" + $jobName + ".json")

New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'results') | Out-Null
if (Test-Path $localResult) { Remove-Item $localResult -Force }

# 清掉远端上一次的同名结果，避免读到旧值
& ssh -i $KeyPath $target "del /Q D:\kr_import\ue_jobs\out\$jobName.json" 2>$null | Out-Null

& scp -i $KeyPath -q $JobPath "${target}:$RemoteInboxDir/$jobName.py"
if ($LASTEXITCODE -ne 0) { throw "上传失败：$JobPath" }

# 先落 inbox 再原子 move 进被轮询的目录：避免轮询器读到写了一半的脚本
& ssh -i $KeyPath $target "move /Y D:\kr_import\incoming\$jobName.py D:\kr_import\ue_jobs\$jobName.py" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "移入任务目录失败：$RemoteJobDir" }

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 1200
    & scp -i $KeyPath -q "${target}:D:/kr_import/ue_jobs/out/$jobName.json" $localResult 2>$null
    if (Test-Path $localResult) { break }
}
if (-not (Test-Path $localResult)) {
    throw "任务 $jobName $TimeoutSeconds 秒内没有结果（编辑器没起 / 脚本卡住 / 脚本抛异常都会这样）"
}

$text = Get-Content $localResult -Raw -Encoding UTF8
if (-not $Quiet) { $text }
return $text
