# Start UnrealEditor inside the logged-on user's interactive session, so the author sees it on their desktop.
#
# Why this exists: an SSH login lands in session 0 (the services session). A GUI program started from there
# is invisible to the person sitting at the machine; with -nullrhi the editor still runs logic and accepts
# job scripts, but it has no window. A scheduled task created with /it runs its action in the interactive
# session of the logged-on user (measured: the spawned process reports SessionId = 1).
#
# schtasks mangles quoted paths that contain spaces, so the action is a tiny .cmd wrapper (see _start_editor.cmd).
# All files here are pure ASCII + CRLF: Windows PowerShell 5.1 reads a BOM-less file as the local codepage,
# and non-ASCII comments then break parsing.
param(
    [string]$Project = 'D:\KeyRipple\KeyRipple.uproject',
    [string]$Editor = 'F:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe',
    [string]$Level = '/Game/BigCollection',
    [string]$TaskName = 'DSH_UnrealEditor',
    [int]$WaitSeconds = 180,
    [string]$WrapperDir = 'D:\kr_import\tools'
)

$ErrorActionPreference = 'Continue'

$running = Get-Process UnrealEditor -ErrorAction SilentlyContinue
if ($running) {
    Write-Output ("ALREADY_RUNNING=" + (($running | ForEach-Object { "$($_.Id)@session$($_.SessionId)" }) -join ','))
    exit 0
}

$wrapper = Join-Path $WrapperDir '_start_editor.cmd'
$lines = @(
    '@echo off',
    'rem Start UnrealEditor. Used as a scheduled task action because schtasks mangles quoted paths.',
    ('start "" "' + $Editor + '" "' + $Project + '" ' + $Level + ' -nosplash -nopause -log')
)
Set-Content -Path $wrapper -Value $lines -Encoding ASCII

& schtasks /create /tn $TaskName /tr $wrapper /sc once /st 23:59 /ru "administrator" /it /f | Out-Null
& schtasks /run /tn $TaskName | Out-Null
Start-Sleep -Seconds 3
& schtasks /delete /tn $TaskName /f | Out-Null

# NOTE: from session 0 you cannot query windows that belong to another session: MainWindowHandle stays 0
# and tasklist /V prints no title even when the window is on the author's desktop. Only report the process.
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $editor = Get-Process UnrealEditor -ErrorAction SilentlyContinue
    if ($editor) {
        Write-Output ("STARTED=" + (($editor | ForEach-Object { "$($_.Id)@session$($_.SessionId)" }) -join ','))
        exit 0
    }
}
Write-Output 'NOT_STARTED'
