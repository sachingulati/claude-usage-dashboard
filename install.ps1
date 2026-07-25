<#
.SYNOPSIS
  Start the Claude usage dashboard server and make it auto-start at logon.

  Tries Windows Task Scheduler first (gives crash-restart). If that's denied
  (it needs elevation), falls back automatically to a per-user logon Run key,
  which needs no admin rights. Either way the server starts now and at logon.

.EXAMPLE
  pwsh -File install.ps1            # install + start
  pwsh -File install.ps1 -Uninstall # remove (delegates to uninstall.ps1)
#>
param(
    [switch]$Uninstall,
    [string]$TaskName = "ClaudeUsageDashboard"
)

$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot
$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

if ($Uninstall) {
    & (Join-Path $PSScriptRoot "uninstall.ps1") -TaskName $TaskName
    return
}

# Prefer pythonw.exe (no console window); fall back to python.exe.
$pyCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($pyCmd) {
    $python = $pyCmd.Source
} else {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $pythonw = $python -replace 'python\.exe$', 'pythonw.exe'
    if (Test-Path $pythonw) { $python = $pythonw }
}
Write-Host "Using interpreter: $python"

$serve = Join-Path $ProjectDir "serve.py"

function Start-Now {
    Start-Process -FilePath $python -ArgumentList "`"$serve`"", "--no-browser" `
        -WorkingDirectory $ProjectDir -WindowStyle Hidden | Out-Null
}

$method = ""
try {
    # --- preferred: Task Scheduler (restart-on-crash + logon) ---
    $action = New-ScheduledTaskAction -Execute $python `
        -Argument "serve.py --no-browser" -WorkingDirectory $ProjectDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    $settings.ExecutionTimeLimit = "PT0S"
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal `
        -Description "Claude Code usage dashboard - refreshes on interval, serves on localhost." `
        -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    $method = "scheduled task (auto-restarts on crash)"
} catch {
    # --- fallback: per-user Run key (no admin) ---
    Write-Host "Task Scheduler unavailable ($($_.Exception.Message.Trim()))."
    Write-Host "Falling back to a per-user logon Run key (no admin needed)."
    $cmd = "`"$python`" `"$serve`" --no-browser"
    New-ItemProperty -Path $RunKey -Name $TaskName -Value $cmd -PropertyType String -Force | Out-Null
    Start-Now
    $method = "logon Run key (no crash-restart)"
}

# Figure out the port for the message.
$port = 8787
$cfg = Join-Path $ProjectDir "config.toml"
if (Test-Path $cfg) {
    $m = Select-String -Path $cfg -Pattern '^\s*port\s*=\s*(\d+)' | Select-Object -First 1
    if ($m) { $port = $m.Matches[0].Groups[1].Value }
}

Write-Host ""
Write-Host "Installed via $method."
Write-Host "Running now, and at every logon."
Write-Host "Open the dashboard at:  http://127.0.0.1:$port/"
Write-Host "Bookmark it. To remove:  pwsh -File uninstall.ps1"
