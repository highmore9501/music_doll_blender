# 远程投递器客户端示例（可选）。
#
# 演示一条通用链路：把本机的一个 UE 脚本传到目标机 → 交给那边常驻编辑器的「任务轮询器」执行 →
# 等结果 JSON → 解码打印。目标机上需要已经装好配套的轮询器，约定是：
#
#   轮询器监视 <RemoteJobsDir>\*.py，执行完把结果写到 <RemoteJobsDir>\out\<脚本名>.json
#   （编辑器启动时注册一个 slate post tick 回调、或由插件在 Initialize 里起线程，都能实现；
#    本文件只管客户端这一半。）
#
# 用法：
#   .\send_job.ps1 -JobPath .\build_player.py `
#                  -RemoteHost 10.0.0.5 -RemoteUser builder -KeyPath C:\path\to\id_ed25519 `
#                  -RemoteInboxDir D:/ue_jobs/incoming -RemoteJobsDir D:/ue_jobs
#
# 所有地址、账号、路径都必须由调用方传入，脚本里不留任何默认值。

param(
    [Parameter(Mandatory = $true)][string]$JobPath,
    [Parameter(Mandatory = $true)][string]$RemoteHost,
    [Parameter(Mandatory = $true)][string]$RemoteUser,
    [Parameter(Mandatory = $true)][string]$KeyPath,
    [Parameter(Mandatory = $true)][string]$RemoteInboxDir,    # 例如 D:/ue_jobs/incoming（先落这里，再 move）
    [Parameter(Mandatory = $true)][string]$RemoteJobsDir,     # 例如 D:/ue_jobs（轮询器看的目录）
    [int]$TimeoutSeconds = 120,
    [int]$PollSeconds = 5
)

$errorActionPreference = 'Stop'
$jobName = [System.IO.Path]::GetFileNameWithoutExtension($JobPath)
$target = "$($RemoteUser)@$($RemoteHost)"

# 1) 先传到 inbox 再原子 move 进被轮询的目录：避免轮询器读到写了一半的脚本（PermissionError / 语法错）
& scp -i $KeyPath $JobPath "${target}:$RemoteInboxDir/$jobName.py"
if ($LASTEXITCODE -ne 0) { throw "上传失败：$JobPath" }
# 目标机 shell 可能是 cmd（Windows）也可能是 sh（Linux），两种 move 都试一遍
$moved = $false
foreach ($moveCommand in @(
    "move /Y `"$RemoteInboxDir\$jobName.py`" `"$RemoteJobsDir\$jobName.py`"",
    "mv -f '$RemoteInboxDir/$jobName.py' '$RemoteJobsDir/$jobName.py'"
)) {
    & ssh -i $KeyPath $target $moveCommand 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $moved = $true; break }
}
if (-not $moved) { throw "把脚本移进任务目录失败：$RemoteJobsDir" }

# 2) 轮询结果。远程控制台编码不可靠（Windows 上常是 GBK），一律 base64 取回后本地解码
$resultPython = "$RemoteJobsDir/out/$jobName.json"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds $PollSeconds
    $probe = "if [ -f '$resultPython' ]; then base64 -w0 '$resultPython'; else echo PENDING; fi"
    $encoded = & ssh -i $KeyPath $target $probe 2>$null
    if (-not $encoded) { continue }
    $text = $encoded.Trim()
    if ($text -eq 'PENDING') { continue }
    $decoded = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($text))
    if ($decoded.Trim().Length -gt 0) { $decoded; return }
}
throw "任务 $jobName 在 $TimeoutSeconds 秒内没有产出结果（编辑器没起来 / 轮询器没装 / 脚本抛错都会这样）"
